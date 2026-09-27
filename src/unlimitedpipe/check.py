"""`unlimited check`: try a pipeline before it joins a catalog.

A good feed loads, runs, writes a JSON feed of readable items (a title, a web link, a date),
and a second run finds nothing new: its items keep their identity between runs, so readers
are not shown the same thing twice. Problems fail the check; warnings are for the reviewer.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from unlimitedpipe.config import env_references, load_pipeline
from unlimitedpipe.errors import ConfigError

RUN_TIMEOUT = 900
UNSTABLE = 0.2  # more than this share of items new on a second run: their keys change
STALE_DAYS = 14


@dataclass
class FeedCheck:
    path: str
    name: str = ""
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    items: int = 0
    new_on_second_run: int = 0
    samples: list[dict[str, Any]] = field(default_factory=list)
    secrets: list[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.problems


def _run(path: Path, state: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "UNLIMITEDPIPE_STATE_DIR": state}
    return subprocess.run(
        [sys.executable, "-m", "unlimitedpipe", "run", str(path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )


def _items(files: list[Path]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for file in files:
        try:
            document = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        found += [i for i in document.get("items", []) if isinstance(i, dict)]
    return found


def _last_line(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1][:200] if lines else "no message"


def check(path: Path, readme: str | None = None) -> FeedCheck:
    """Load, run twice (with a state folder of its own) and inspect one pipeline."""
    from unlimitedpipe.event import parse_time

    result = FeedCheck(path=str(path))
    try:
        pipeline = load_pipeline(path)
    except ConfigError as exc:
        result.problems.append(f"does not load: {exc.message}")
        return result
    result.name = pipeline.name
    result.secrets = [n for n in env_references(path.read_text()) if n != "GITHUB_TOKEN"]
    if not pipeline.description:
        result.warnings.append("has no description of what it follows")
    if readme is not None and pipeline.name not in readme:
        result.warnings.append("is not in the README's list of feeds")
    files = [
        Path(str(getattr(o, "path", ""))).resolve()
        for o in pipeline.outputs
        if str(getattr(o, "path", "")).endswith(".json")
    ]
    if not files:
        result.problems.append("writes no JSON feed (an output with a .json path)")
        return result
    start = time.time()
    with tempfile.TemporaryDirectory() as state:
        first = _run(path, state)
        if first.returncode >= 2:
            result.problems.append(f"the run failed: {_last_line(first.stderr)}")
            return result
        if first.returncode == 1:
            result.warnings.append(f"some sources failed: {_last_line(first.stderr)}")
        before = _items(files)
        second = _run(path, state)
        after = _items(files)
    result.seconds = round(time.time() - start, 1)
    if second.returncode >= 2:
        result.problems.append(f"the second run failed: {_last_line(second.stderr)}")
    result.items = len(after)
    seen = {i.get("id") for i in before}
    result.new_on_second_run = sum(1 for i in after if i.get("id") not in seen)
    result.samples = [
        {"title": i.get("title"), "link": i.get("url"), "date": i.get("date_published")}
        for i in after[:5]
    ]
    if not after:
        result.problems.append(
            "wrote no items: check the source and filters; a diff needs emit_initial: true "
            "for a new feed to start with its current items"
        )
        return result
    if before and result.new_on_second_run > UNSTABLE * len(before):
        result.problems.append(
            f"{result.new_on_second_run} of {len(after)} items were new on a second run moments "
            "later: their keys change between runs (key the diff on a stable field)"
        )
    elif result.new_on_second_run:
        result.warnings.append(
            f"{result.new_on_second_run} item(s) were new on a second run moments later: "
            "check that their keys stay the same between runs"
        )
    dates = [d for d in (parse_time(i.get("date_published")) for i in after) if d is not None]
    if dates:
        from datetime import UTC, datetime

        age = (datetime.now(UTC) - max(dates)).days
        if age > STALE_DAYS:
            result.warnings.append(
                f"its newest item is {age} days old: check that it follows new and updated items"
            )
    untitled = sum(1 for i in after if not str(i.get("title") or "").strip())
    if untitled:
        result.problems.append(f"{untitled} item(s) have no title")
    linkless = sum(
        1 for i in after if not str(i.get("url") or "").startswith(("http://", "https:"))
    )
    if linkless:
        result.problems.append(f"{linkless} item(s) have no web link to their source")
    undated = sum(1 for i in after if parse_time(i.get("date_published")) is None)
    if undated:
        result.warnings.append(f"{undated} item(s) have no date")
    long = sum(1 for i in after if len(str(i.get("title") or "")) > 300)
    if long:
        result.warnings.append(f"{long} title(s) are longer than 300 characters")
    titles = [str(i.get("title") or "").casefold() for i in after]
    if len(set(titles)) < len(titles):
        result.warnings.append(f"{len(titles) - len(set(titles))} title(s) repeat")
    if result.secrets:
        result.warnings.append(
            f"needs repository secret(s) {', '.join(result.secrets)} to run on GitHub"
        )
    return result


def markdown(results: list[FeedCheck]) -> str:
    """A report for a pull request: a verdict per feed, what is wrong, and sample items."""
    lines = ["## Feed check", ""]
    for r in results:
        verdict = "passed" if r.ok else "failed"
        lines.append(f"### {'✅' if r.ok else '❌'} `{r.path}`: {verdict}")
        lines.append("")
        lines.append(
            f"{r.items} item(s); {r.new_on_second_run} new on a second run; {r.seconds} s."
        )
        for problem in r.problems:
            lines.append(f"- **Problem:** {problem}")
        for warning in r.warnings:
            lines.append(f"- Warning: {warning}")
        if r.samples:
            lines += ["", "| Date | Item |", "| --- | --- |"]
            for s in r.samples:
                title = str(s["title"] or "").replace("|", "\\|")[:120]
                lines.append(f"| {str(s['date'] or '')[:10]} | [{title}]({s['link']}) |")
        lines.append("")
    return "\n".join(lines)
