from __future__ import annotations

from collections import OrderedDict

from unlimitedpipe.component import Operator, opt
from unlimitedpipe.event import Event, content_hash
from unlimitedpipe.fields import MISSING, resolve, split_path


class Dedupe(Operator):
    """Drop events already seen in this stream.

    Identity is the event key by default (a product URL, a feed item id), else its content.
    ``--by url`` uses a field; ``--by content`` hashes the data. Memory stays bounded: only the
    last ``--window`` identities are remembered. To drop items seen in earlier runs, use
    ``diff --only added``.
    """

    name = "dedupe"
    by: list[str] = opt("Field(s) that identify an event, or `content`", metavar="PATH")
    window: int = opt("How many identities to remember", default=100_000)

    def __post_init__(self) -> None:
        if self.window < 1:
            raise ValueError("--window must be at least 1")
        self._paths = [split_path(path) for path in self.by if path != "content"]
        self._content = "content" in self.by

    def identity(self, event: Event) -> str:
        if self._paths or self._content:
            values = [resolve(event, parts) for parts in self._paths]
            values = [None if value is MISSING else value for value in values]
            if self._content:
                values.append(event.data)
            return content_hash(*values)
        return event.key or content_hash(event.data)

    async def apply(self, events, ctx):
        seen: OrderedDict[str, None] = OrderedDict()
        async for event in events:
            identity = self.identity(event)
            if identity in seen:
                seen.move_to_end(identity)
                continue
            seen[identity] = None
            if len(seen) > self.window:
                seen.popitem(last=False)
            yield event
