from __future__ import annotations

from typing import Any

from unlimitedpipe.component import Operator, opt
from unlimitedpipe.event import Event
from unlimitedpipe.fields import MISSING, resolve, split_path


def _sort_value(value: Any) -> tuple[int, Any]:
    """Order numbers, then text; missing values always sort last."""
    if value is MISSING or value is None:
        return (2, 0)
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, (int, float)):
        return (0, value)
    if isinstance(value, str):
        try:
            return (0, float(value))
        except ValueError:
            return (1, value.casefold())
    return (1, str(value))


class Sort(Operator):
    """Sort events by one or more fields. Reads the whole stream first.

    Numbers sort numerically (also numeric text), ISO dates sort chronologically, missing
    values go last.
    """

    name = "sort"
    buffering = True
    by: list[str] = opt(
        "Field(s) to sort by", default_factory=lambda: ["timestamp"], metavar="PATH"
    )
    reverse: bool = opt("Largest / newest first", short="-r", default=False)

    def __post_init__(self) -> None:
        if not self.by:
            raise ValueError("sort needs at least one --by field")
        self._paths = [split_path(path) for path in self.by]

    def _key(self, event: Event) -> tuple[Any, ...]:
        return tuple(_sort_value(resolve(event, parts)) for parts in self._paths)

    async def apply(self, events, ctx):
        buffered = [event async for event in events]
        present = [e for e in buffered if self._key(e)[0][0] != 2]
        missing = [e for e in buffered if self._key(e)[0][0] == 2]
        present.sort(key=self._key, reverse=self.reverse)
        for event in present + missing:
            yield event
