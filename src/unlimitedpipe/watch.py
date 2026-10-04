"""Run a pipeline again and again on an interval, in one process.

A watch never dies of a bad run: failures are reported and the next run happens on schedule.
A pipeline file is reloaded when it changes; if the new version is invalid, the last valid one
keeps running.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import click

from unlimitedpipe.component import Output
from unlimitedpipe.config import Pipeline
from unlimitedpipe.errors import UnlimitedError, UsageError

log = logging.getLogger("unlimitedpipe.watch")

UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
MIN_INTERVAL = 30.0


def parse_duration(text: str) -> float:
    """``30s``, ``5m``, ``1h30m``, ``1d`` -> seconds."""
    cleaned = text.strip().lower().replace(" ", "")
    parts = re.findall(r"(\d+(?:\.\d+)?)([smhd])", cleaned)
    if not parts or "".join(n + u for n, u in parts) != cleaned:
        raise UsageError(
            f"invalid duration {text!r}", hint="use a number and a unit: 30s, 5m, 1h, 1h30m, 1d"
        )
    return sum(float(number) * UNITS[unit] for number, unit in parts)


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


class Watch:
    def __init__(
        self,
        load: Callable[[], Pipeline],
        *,
        every: float,
        jitter: float = 0.1,
        times: int | None = None,
        quiet: bool = False,
        reload_path: Path | None = None,
        default_outputs: Callable[[], list[Output]] = list,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.load = load
        self.every = every
        self.jitter = jitter
        self.times = times
        self.quiet = quiet
        self.reload_path = reload_path
        self.default_outputs = default_outputs
        self.sleep = sleep
        self.runs = 0

    def say(self, message: str, *, dim: bool = True) -> None:
        if not self.quiet:
            stamp = datetime.now().strftime("%H:%M:%S")
            click.echo(click.style(f"[{stamp}] {message}", dim=dim), err=True)

    def _mtime(self) -> float | None:
        try:
            return self.reload_path.stat().st_mtime if self.reload_path else None
        except OSError:
            return None

    def _timed(self) -> bool:
        """Whether the pipeline file refers to the date or time (then it is loaded each run)."""
        from unlimitedpipe.config import uses_time

        try:
            return bool(self.reload_path) and uses_time(self.reload_path.read_text("utf-8"))
        except OSError:
            return False

    def run_once(self, pipeline: Pipeline) -> tuple[int, int]:
        """One run. Returns (events, failures); never raises except for Ctrl+C."""
        from unlimitedpipe.context import Context
        from unlimitedpipe.engine import run_pipeline

        ctx = Context(errors_as_events=pipeline.errors_as_events, quiet=self.quiet)
        outputs = pipeline.outputs or self.default_outputs()
        try:
            count = asyncio.run(run_pipeline(pipeline.sources, pipeline.operators, outputs, ctx))
        except UnlimitedError as exc:
            message = exc.message + (f" ({exc.hint})" if exc.hint else "")
            click.echo(click.style("error: ", fg="red", bold=True) + message, err=True)
            return 0, ctx.failures + 1
        except Exception as exc:
            log.debug("run failed", exc_info=exc)
            click.echo(
                click.style("error: ", fg="red", bold=True)
                + f"run failed: {type(exc).__name__}: {exc} (run with -vv for details)",
                err=True,
            )
            return 0, ctx.failures + 1
        return count, ctx.failures

    def run(self) -> None:
        pipeline = self.load()
        mtime = self._mtime()
        every = format_duration(self.every)
        self.say(f"watching every {every}; Ctrl+C to stop")
        while True:
            current = self._mtime()
            if current != mtime or self._timed():
                changed, mtime = current != mtime, current
                try:
                    pipeline = self.load()
                    if changed:
                        self.say(f"reloaded {self.reload_path}")
                except UnlimitedError as exc:
                    self.say(f"{exc.message}; still running the previous version", dim=False)
            self.runs += 1
            started = time.monotonic()
            events, failures = self.run_once(pipeline)
            summary = f"run {self.runs}: {events} event(s)"
            if failures:
                summary += f", {failures} failure(s)"
            if self.times is not None and self.runs >= self.times:
                self.say(summary)
                return
            delay = self.every * (1 + random.uniform(0, self.jitter))
            wait = started + delay - time.monotonic()
            if wait < 0:
                self.say(f"{summary}; the run took longer than {every}, starting the next now")
                wait = 0
            else:
                next_at = (datetime.now() + timedelta(seconds=wait)).strftime("%H:%M:%S")
                self.say(f"{summary}; next run at {next_at}")
            self.sleep(wait)


class WatchMany(Watch):
    """Several pipeline files, run side by side each round in one process: a live lane for a
    catalog's time-sensitive feeds on a small server. Each file is reloaded when it changes.
    With ``catalog``, the round ends by writing feeds.json for these pipelines next to their
    outputs (no archive), for readers that merge it into the full catalog."""

    def __init__(
        self,
        paths: list[Path],
        *,
        catalog: bool = False,
        intervals: dict[Path, float] | None = None,
        **options,
    ) -> None:
        super().__init__(lambda: None, **options)  # type: ignore[arg-type, return-value]
        self.paths = paths
        self.catalog = catalog
        # a file's own interval (`filings.yml@30s`), else --every
        self.intervals = intervals or {}
        self.loaded: dict[Path, tuple[float | None, Pipeline]] = {}
        self.timed: set[Path] = set()  # files that refer to the date or time

    def _pipelines(self) -> list[tuple[Path, Pipeline]]:
        from unlimitedpipe.config import load_pipeline, uses_time

        for path in self.paths:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = None
            known = self.loaded.get(path)
            if known and known[0] == mtime and path not in self.timed:
                continue
            try:
                self.loaded[path] = (mtime, load_pipeline(path))
                if uses_time(path.read_text(encoding="utf-8")):
                    self.timed.add(path)  # ${TODAY}, ${HOURS_AGO_2}: new values each run
                else:
                    self.timed.discard(path)
                if known and known[0] != mtime:
                    self.say(f"reloaded {path}")
            except UnlimitedError as exc:
                self.say(f"{path}: {exc.message}; still running the previous version", dim=False)
        return [(path, self.loaded[path][1]) for path in self.paths if path in self.loaded]

    async def _round(self, pipelines: list[tuple[Path, Pipeline]]) -> dict[str, int]:
        from unlimitedpipe.context import Context
        from unlimitedpipe.engine import run_pipeline

        async def one(path: Path, pipeline: Pipeline) -> tuple[str, int, int]:
            ctx = Context(errors_as_events=pipeline.errors_as_events, quiet=self.quiet)
            try:
                count = await run_pipeline(
                    pipeline.sources, pipeline.operators, pipeline.outputs, ctx
                )
            except Exception as exc:  # one pipeline's failure never stops the others
                message = exc.message if isinstance(exc, UnlimitedError) else repr(exc)
                click.echo(
                    click.style("error: ", fg="red", bold=True) + f"{path}: {message}", err=True
                )
                return str(path), 0, 2
            finally:
                await ctx.aclose()
            return str(path), count, 1 if ctx.failures else 0

        done = await asyncio.gather(*(one(path, pipeline) for path, pipeline in pipelines))
        self.events = sum(count for _, count, _ in done)
        return {path: code for path, _, code in done}

    def _write_catalog(self, pipelines: list[tuple[Path, Pipeline]], codes: dict[str, int]) -> None:
        import json
        import os

        from unlimitedpipe.publish import CATALOG, catalog, plan

        p = plan(pipelines, 3600)
        path = p.root / p.site_dir / CATALOG
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = None
        results = {str(Path(k).resolve().relative_to(p.root)): v for k, v in codes.items()}
        text = json.dumps(catalog(p, results=results, previous=previous), ensure_ascii=False)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(text + "\n", encoding="utf-8")
        os.replace(tmp, path)

    def run(self) -> None:
        every = format_duration(self.every)
        self.say(f"watching {len(self.paths)} pipelines every {every}; Ctrl+C to stop")
        due: dict[Path, float] = {}
        codes: dict[str, int] = {}
        while True:
            self.runs += 1
            started = time.monotonic()
            pipelines = self._pipelines()
            ready = [(path, p) for path, p in pipelines if due.get(path, 0.0) <= started]
            codes.update(asyncio.run(self._round(ready)))
            stretch = 1 + random.uniform(0, self.jitter)  # one per round keeps files in step
            for path, _ in ready:
                due[path] = started + self.intervals.get(path, self.every) * stretch
            current = {str(path): codes[str(path)] for path, _ in pipelines if str(path) in codes}
            failed = sum(
                code > 0 for path, code in codes.items() if path in {str(p) for p, _ in ready}
            )
            if self.catalog and pipelines:
                try:
                    self._write_catalog(pipelines, current)
                except (UnlimitedError, OSError, ValueError) as exc:
                    self.say(f"feeds.json not written: {exc}", dim=False)
            summary = f"run {self.runs}: {self.events} event(s) from {len(ready)} pipeline(s)"
            if failed:
                summary += f", {failed} with failures"
            took = time.monotonic() - started
            summary += f" in {took:.1f}s"
            if self.times is not None and self.runs >= self.times:
                self.say(summary)
                return
            following = min(
                (due.get(path, started) for path, _ in pipelines), default=started + self.every
            )
            self.say(summary)
            self.sleep(max(0.0, following - time.monotonic()))
