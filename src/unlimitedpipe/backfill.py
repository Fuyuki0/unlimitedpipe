"""`unlimited backfill`: fill a catalog's archive with a feed's past items.

A feed follows what is new, but many of its sources can also be asked about the past: an API
that takes a date range (the USGS, NVD, FRED, the Federal Register, SEC full-text search) or a
list that keeps every item it ever had (CISA's exploited vulnerabilities, Have I Been Pwned).
Backfill runs a feed's own sources and operators once per window of time, with ``${TODAY}``
and ``${YEAR}`` as the window's last day and its year and every ``${DAYS_AGO_N}`` as its first
day, and adds what they find to the archive the way a run does, so past items read exactly
like new ones. The feed's `diff` and `limit` operators (which keep a feed to what is new and
short) and its outputs are left out, and it runs with a state folder of its own: the feed's
files and state stay as they are.
"""

from __future__ import annotations

import asyncio
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from unlimitedpipe.component import Output
from unlimitedpipe.errors import UsageError
from unlimitedpipe.event import Event, utcnow

EVERY = re.compile(r"[1-9]\d*d|week|month|quarter|year")
LEFT_OUT = {"diff", "limit"}  # what keeps a feed to what is new and short
USES_DATES = re.compile(r"\$\{(TODAY|YEAR|DAYS_AGO_\d+)\}")


def parse_every(text: str) -> str:
    every = text.strip().lower()
    if not EVERY.fullmatch(every):
        raise UsageError(
            f"--every takes a number of days or a calendar period, not {text!r}",
            hint="for example 30d, week, month, quarter or year",
        )
    return every


def parse_day(text: str, *, end: bool = False) -> date:
    """``2020``, ``2020-03`` or ``2020-03-15``: the first day of it, or its last with ``end``."""
    text = text.strip()
    match = re.fullmatch(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", text)
    try:
        if match is None:
            raise ValueError
        year, month, day = int(match[1]), match[2], match[3]
        if day:
            return date(year, int(month), int(day))
        if month:
            first = date(year, int(month), 1)
            return _next(first, "month") - timedelta(days=1) if end else first
        return date(year, 12, 31) if end else date(year, 1, 1)
    except ValueError:
        raise UsageError(f"not a date: {text!r}", hint="like 2020, 2020-03 or 2020-03-15") from None


def _next(day: date, every: str) -> date:
    """The first day of the window after the one that starts on ``day``."""
    if every.endswith("d"):
        return day + timedelta(days=int(every[:-1]))
    if every == "week":
        return day + timedelta(days=7)
    if every == "year":
        return date(day.year + 1, 1, 1)
    months = 3 if every == "quarter" else 1
    index = day.year * 12 + day.month - 1
    index = (index // months + 1) * months  # the start of the next month or quarter
    return date(index // 12, index % 12 + 1, 1)


def windows(start: date, end: date, every: str) -> list[tuple[date, date]]:
    """Back-to-back windows from ``start`` to ``end``, both days included. Calendar periods
    end where the calendar does: ``month`` from 2020-01-15 gives 2020-01-15 to 2020-01-31,
    then all of February."""
    found = []
    while start <= end:
        after = _next(start, every)
        found.append((start, min(after - timedelta(days=1), end)))
        start = after
    return found


class _Collect(Output):
    """Keeps the events a window's run produces."""

    events: list[Event] = field(default_factory=list)

    async def write(self, event: Event) -> None:
        self.events.append(event)


@dataclass
class WindowResult:
    start: date
    end: date
    found: int = 0  # items the run produced
    kept: int = 0  # of those, dated inside the backfill's range
    added: int = 0  # of those, new to the archive
    failed: bool = False


@dataclass
class Backfill:
    feed: str
    windows: list[WindowResult] = field(default_factory=list)
    undated: int = 0
    months: dict[str, int] = field(default_factory=dict)
    samples: list[dict[str, Any]] = field(default_factory=list)

    @property
    def added(self) -> int:
        return sum(self.months.values())


def backfill(
    path: Path,
    site: Path,
    start: date,
    end: date,
    every: str,
    *,
    dry_run: bool = False,
    pause: float = 1.0,
    quiet: bool = False,
    progress: Callable[[WindowResult], None] | None = None,
) -> Backfill:
    """Run the pipeline at ``path`` over the past, from ``start`` to ``end``, and add its items
    to the archive in ``site`` (or with ``dry_run`` only count them)."""
    from unlimitedpipe import archive
    from unlimitedpipe.config import WINDOW, load_pipeline
    from unlimitedpipe.context import Context
    from unlimitedpipe.engine import run_pipeline
    from unlimitedpipe.event import iso
    from unlimitedpipe.outputs.feed import feed_item
    from unlimitedpipe.publish import listed_item

    text = path.read_text(encoding="utf-8")
    spans = windows(start, end, every) if USES_DATES.search(text) else [(start, end)]
    first, last = start.isoformat(), (end + timedelta(days=1)).isoformat()
    result: Backfill | None = None
    seen: set[str] = set()
    with tempfile.TemporaryDirectory() as scratch:
        for index, (begin, finish) in enumerate(spans):
            token = WINDOW.set((begin, finish))
            try:
                pipeline = load_pipeline(path)
            finally:
                WINDOW.reset(token)
            if result is None:
                result = Backfill(feed=pipeline.name)
            collect = _Collect()
            ctx = Context(
                quiet=quiet,
                state_dir=Path(scratch) / "state",
                cache_dir=Path(scratch) / "cache",
            )
            operators = [op for op in pipeline.operators if op.name not in LEFT_OUT]
            asyncio.run(run_pipeline(pipeline.sources, operators, [collect], ctx))
            window = WindowResult(begin, finish, found=len(collect.events), failed=ctx.failures > 0)
            items = []
            for event in collect.events:
                item = feed_item(event)
                if not item["dated"]:
                    result.undated += 1
                    continue
                entry = {
                    "title": item["title"],
                    "content_text": item["summary"] or item["title"],
                    "url": item["link"],
                    "date_published": iso(item["date"]),
                }
                listed = listed_item(pipeline.name, entry)
                if not first <= str(listed["date"]) < last:
                    continue
                if (key := archive.item_key(listed)) in seen:
                    continue
                seen.add(key)
                items.append(listed)
            window.kept = len(items)
            if items and len(result.samples) < 5:
                result.samples += items[: 5 - len(result.samples)]
            if dry_run:
                window.added = len(items)
            else:
                added = archive.append(site, items, utcnow())
                window.added = sum(added.values())
                for month, count in added.items():
                    result.months[month] = result.months.get(month, 0) + count
            result.windows.append(window)
            if progress:
                progress(window)
            if pause and index < len(spans) - 1:
                import time

                time.sleep(pause)
    assert result is not None
    return result
