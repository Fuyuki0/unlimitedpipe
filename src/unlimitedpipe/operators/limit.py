from __future__ import annotations

from unlimitedpipe.component import Operator, arg


class Limit(Operator):
    """Pass the first N events, then stop the pipeline."""

    name = "limit"
    bounded = True
    count: int = arg("How many events to pass")

    def __post_init__(self) -> None:
        if self.count < 0:
            raise ValueError("limit must be 0 or more")

    async def apply(self, events, ctx):
        if self.count == 0:
            return
        passed = 0
        async for event in events:
            yield event
            passed += 1
            if passed >= self.count:
                return
