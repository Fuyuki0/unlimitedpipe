"""Count events per value, over the whole stream or in time windows."""

from __future__ import annotations

import time
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from unlimitedpipe.component import Operator, opt
from unlimitedpipe.event import Event
from unlimitedpipe.fields import MISSING, resolve, split_path


def event_time(event: Event) -> float:
    """When the thing happened (``timestamp``), else when it was observed."""
    for value in (event.timestamp, event.observed_at):
        if value:
            try:
                parsed = datetime.fromisoformat(value)
                return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).timestamp()
            except ValueError:
                continue
    return datetime.now(UTC).timestamp()


def iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Tally:
    """Counts per value: events, or distinct keys (one author posting 100 times counts once)."""

    def __init__(self, distinct: bool) -> None:
        self.counts: Counter[str] = Counter()
        self._seen: dict[str, set[str]] | None = {} if distinct else None

    def add(self, values: list[str], key: str) -> None:
        if self._seen is None:
            self.counts.update(values)
            return
        for value in values:
            keys = self._seen.setdefault(value, set())
            if key not in keys:
                keys.add(key)
                self.counts[value] += 1


class Count(Operator):
    """Count events per value of a field, for the whole stream or per time window.

    A list value counts each element, so `extract hashtags | count --by hashtags` counts tags.
    With --every, windows follow each event's own time (published, else observed), so
    timestamped history such as a feed is bucketed correctly in any order; on a live stream
    each window is reported shortly after it ends. Emits one `count` event per value and
    window, most frequent first, marked `complete: false` when the data covers only part of
    the window (the first window of a live stream, the edges of a feed). Feed them to `trend`
    to spot spikes.
    """

    name = "count"
    examples = (
        "unlimited rss https://hnrss.org/frontpage | unlimited extract words -f title "
        "| unlimited count --by words --top 10",
        "unlimited bluesky -- extract hashtags -- count --by hashtags --every 10m -- trend",
    )

    by: str = opt("Field to count by (lists count each element)", metavar="PATH")
    every: str | None = opt(
        "Window length, e.g. 10m, 1h, 1d (default: the whole stream)", default=None
    )
    top: int = opt("Only the N most frequent values per window (0: all)", default=0)
    distinct: str | None = opt(
        "Count distinct values of this field instead of events, e.g. author_key",
        default=None,
        metavar="PATH",
    )

    def __post_init__(self) -> None:
        from unlimitedpipe.watch import parse_duration

        self._path = split_path(self.by)
        self._distinct = split_path(self.distinct) if self.distinct else None
        self._window = parse_duration(self.every) if self.every else None
        if self.top < 0:
            raise ValueError("--top must be 0 or more")

    def needs_whole_stream(self) -> bool:
        return self._window is None

    def _values(self, event: Event) -> list[str]:
        value = resolve(event, self._path)
        if value is MISSING or value is None:
            return []
        items = value if isinstance(value, list) else [value]
        return [str(item) for item in items if item is not None and item != ""]

    def _key(self, event: Event) -> str:
        if self._distinct is None:
            return ""
        value = resolve(event, self._distinct)
        return event.id if value is MISSING or value is None else str(value)

    def _report(
        self,
        start: float,
        end: float,
        tally: _Tally,
        events: int,
        sample: Event,
        complete: bool = True,
    ) -> list[Event]:
        ranked = tally.counts.most_common(self.top or None)
        truncated = len(ranked) < len(tally.counts)
        return [
            Event(
                source="count",
                type="count",
                key=f"{self.by}={value}@{iso(start)}",
                timestamp=iso(end),
                data={
                    "value": value,
                    "count": count,
                    "field": self.by,
                    "events": events,
                    "window_start": iso(start),
                    "window_end": iso(end),
                    "complete": complete,
                    # Lets `trend` act on a window as soon as its last value arrives, and
                    # know that values missing from a cut-off list were below the cut.
                    "rank": rank,
                    "values": len(ranked),
                    "truncated": truncated,
                },
                provenance=list(sample.provenance),
            )
            for rank, (value, count) in enumerate(ranked, 1)
        ]

    async def apply(self, events, ctx):
        if self._window is None:
            tally = _Tally(self._distinct is not None)
            first = last = None
            total = 0
            sample: Event | None = None
            async for event in events:
                moment = event_time(event)
                first = moment if first is None else min(first, moment)
                last = moment if last is None else max(last, moment)
                total += 1
                sample = sample or event
                tally.add(self._values(event), self._key(event))
            if sample is not None and first is not None and last is not None:
                for result in self._report(first, last, tally, total, sample):
                    yield result
            return

        # A window is reported once it has ended (by event time) and received nothing for a
        # moment of real time. Reading a finite feed takes seconds, so its windows all stay
        # open until the end, whatever the order of items (feeds list newest first); on a live
        # stream each window is reported shortly after it ends.
        size = self._window
        grace = min(size / 10, 60.0)
        slack = size / 10
        earliest = float("inf")
        windows: dict[float, list[Any]] = {}  # start -> [tally, events, sample, last update]
        newest = float("-inf")
        closed_before = float("-inf")
        late = 0
        async for event in events:
            moment = event_time(event)
            start = moment - moment % size
            if start < closed_before:
                late += 1
                continue
            now = time.monotonic()
            window = windows.setdefault(start, [_Tally(self._distinct is not None), 0, event, now])
            window[0].add(self._values(event), self._key(event))
            window[1] += 1
            window[3] = now
            newest = max(newest, moment)
            earliest = min(earliest, moment)
            ready_windows = sorted(
                s for s, w in windows.items() if s + size <= newest and now - w[3] >= grace
            )
            for ready in ready_windows:
                tally, seen, example, _ = windows.pop(ready)
                closed_before = max(closed_before, ready + size)
                # A window the data only partly covers (the stream began after it started, as
                # when joining a live stream mid-window) would distort comparisons.
                complete = earliest <= ready + slack
                for result in self._report(ready, ready + size, tally, seen, example, complete):
                    yield result
        for start in sorted(windows):
            tally, seen, example, _ = windows[start]
            complete = earliest <= start + slack and newest >= start + size - slack
            for result in self._report(start, start + size, tally, seen, example, complete):
                yield result
        if late:
            ctx.notice(f"count: {late} late event(s) arrived after their window was reported")
