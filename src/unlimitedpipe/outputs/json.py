from __future__ import annotations

import json
from typing import Any

from unlimitedpipe.component import Output, arg, opt
from unlimitedpipe.event import Event
from unlimitedpipe.outputs import open_target


class Json(Output):
    """Write all events as one JSON array. Holds the stream in memory until it ends.

    Writes each event's data by default (what you selected); ``--full`` writes whole events
    including provenance.
    """

    name = "json"
    path: str | None = arg("File to write (default: stdout)", default=None)
    full: bool = opt("Write whole events, including source and provenance", default=False)
    indent: int = opt("Indentation (0 for one line)", default=2)

    async def open(self, ctx) -> None:
        self._items: list[Any] = []

    async def write(self, event: Event) -> None:
        self._items.append(event.to_dict() if self.full else event.data)

    async def close(self) -> None:
        stream, is_stdout = open_target(self.path)
        text = json.dumps(self._items, ensure_ascii=False, indent=self.indent or None, default=str)
        stream.write(text + "\n")
        if is_stdout:
            stream.flush()
        else:
            stream.close()
