from __future__ import annotations

import json
from typing import TextIO

from unlimitedpipe.component import Output, arg, opt
from unlimitedpipe.event import Event
from unlimitedpipe.outputs import open_target


class Jsonl(Output):
    """Write one JSON object per line: full events by default, lossless and re-readable.

    This is the native stream format; ``unlimited file out.jsonl`` reads it back with
    provenance intact. ``--data`` writes only each event's data, for other tools.
    """

    name = "jsonl"
    path: str | None = arg("File to write (default: stdout)", default=None)
    data: bool = opt("Write only each event's data", default=False)
    append: bool = opt("Append to the file instead of replacing it", short="-a", default=False)

    async def open(self, ctx) -> None:
        self._stream: TextIO
        self._stream, self._stdout = open_target(self.path, append=self.append)

    async def write(self, event: Event) -> None:
        if self.data:
            line = json.dumps(event.data, ensure_ascii=False, separators=(",", ":"), default=str)
        else:
            line = event.to_json()
        self._stream.write(line + "\n")
        if self._stdout:
            self._stream.flush()

    async def close(self) -> None:
        if self._stdout:
            self._stream.flush()
        else:
            self._stream.close()
