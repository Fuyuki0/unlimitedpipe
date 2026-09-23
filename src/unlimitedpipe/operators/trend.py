"""Spot spikes: values counted far more often than in earlier windows."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from unlimitedpipe.component import Operator, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import ConfigError
from unlimitedpipe.event import Event, content_hash
from unlimitedpipe.state import state_path, write_json_atomic

STATE_VERSION = 1


class Trend(Operator):
    """Report values that rise sharply compared with earlier windows.

    Reads `count` events (from `count --every`) and compares each value's count in a window
    with its average over the previous --history windows, which are kept on disk like `diff`
    state, so trends work across `watch` runs. A value is reported when it reaches
    --min-count and rises by at least --min-change percent; new values count as rising from
    zero. The first complete window only builds history; windows the data covers only in
    part are skipped.
    """

    name = "trend"
    examples = (
        "unlimited bluesky -- extract hashtags -- count --by hashtags --every 10m -- trend",
        "unlimited watch --every 1h rss https://hnrss.org/newest -- extract words -f title "
        "-- count --by words --every 1h -- trend --min-count 4",
    )

    history: int = opt("Earlier windows to compare with", default=6)
    min_count: int = opt("Ignore values counted fewer times in the window", default=3)
    min_change: float = opt("Report rises of at least this many percent", default=100.0)
    namespace: str | None = opt(
        "Name for this trend's history (default: from the counted field)", short="-n", default=None
    )
    state: str | None = opt(
        "History file path (overrides --namespace)", default=None, metavar="FILE"
    )
    reset: bool = opt("Forget the history", default=False)

    def __post_init__(self) -> None:
        if self.history < 1:
            raise ValueError("--history must be at least 1")

    def _load(self, ctx: Context, first: Event) -> tuple[Any, dict[str, dict[str, int]]]:
        namespace = self.namespace
        if namespace is None and not self.state:
            field = first.data.get("field", "value")
            origin = [step.get("step") for step in first.provenance]
            namespace = f"{field}-{content_hash(field, origin)[:8]}"
        path = state_path(ctx, "trend", namespace or "", self.state)
        if self.reset and path.exists():
            path.unlink()
        if not path.exists():
            return path, {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("version") != STATE_VERSION:
                raise ValueError("unknown format")
            return path, dict(raw["windows"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ConfigError(
                f"cannot read trend history {path}: {exc}", hint="start over with --reset"
            ) from None

    def _evaluate(
        self, start: str, window: list[Event], windows: dict[str, dict[str, int]]
    ) -> list[Event]:
        if window[0].data.get("complete") is False:
            self._partial += 1  # comparing a partly covered window would invent spikes
            return []
        earlier = sorted(s for s in windows if s < start)[-self.history :]
        counts = {str(e.data["value"]): int(e.data["count"]) for e in window}
        windows[start] = counts
        if not earlier:
            return []
        rising = []
        for value, count in counts.items():
            past = [windows[s].get(value, 0) for s in earlier]
            baseline = sum(past) / len(past)
            change = (count - baseline) / max(baseline, 1.0) * 100
            if count >= self.min_count and change >= self.min_change:
                rising.append((change, value, count, baseline, past))
        rising.sort(reverse=True)
        sample = window[0]
        results = []
        for change, value, count, baseline, past in rising:
            label = "new" if baseline == 0 else f"+{change:.0f}%"
            usually = f"{baseline:.1f}".removesuffix(".0")
            results.append(
                Event(
                    source="trend",
                    type="trend",
                    key=f"{value}@{start}",
                    timestamp=sample.data.get("window_end"),
                    data={
                        "title": f"{value} {label}: {count} in the window, usually {usually}",
                        "value": value,
                        "count": count,
                        "baseline": round(baseline, 2),
                        "change_pct": round(change, 1),
                        "history": past,
                        "field": sample.data.get("field"),
                        "window_start": start,
                        "window_end": sample.data.get("window_end"),
                    },
                    provenance=list(sample.provenance),
                )
            )
        return results

    async def apply(self, events: AsyncIterator[Event], ctx: Context):
        self._partial = 0
        path = None
        windows: dict[str, dict[str, int]] = {}
        current: str | None = None
        pending: list[Event] = []
        try:
            async for event in events:
                if event.type != "count":
                    continue
                if path is None:
                    path, windows = self._load(ctx, event)
                start = str(event.data.get("window_start"))
                if current is not None and start != current:
                    for result in self._evaluate(current, pending, windows):
                        yield result
                    pending = []
                current = start
                pending.append(event)
            if current is not None and pending:
                for result in self._evaluate(current, pending, windows):
                    yield result
        finally:
            if path is not None:
                keep = sorted(windows)[-(self.history + 1) :]
                write_json_atomic(
                    path, {"version": STATE_VERSION, "windows": {s: windows[s] for s in keep}}
                )
        if path is None:
            ctx.warn("trend: no `count` events; use count --by FIELD --every DURATION before trend")
        elif len(windows) < 2:
            ctx.notice("trend: history started; trends appear once there are earlier windows")
        if self._partial:
            ctx.notice(f"trend: skipped {self._partial} partly covered window(s)")
