from __future__ import annotations

import csv
from typing import Any

from unlimitedpipe.component import Output, arg, opt
from unlimitedpipe.event import Event
from unlimitedpipe.fields import flatten
from unlimitedpipe.outputs import open_target


class Csv(Output):
    """Write events' data as CSV. Nested fields become dotted columns (``offers.price``).

    Columns are the union of all fields in order of appearance, so the stream is held in
    memory until it ends. Pass ``--columns`` to fix them and stream row by row.
    """

    name = "csv"
    path: str | None = arg("File to write (default: stdout)", default=None)
    columns: list[str] = opt(
        "Column to write (repeatable; default: all fields)", short="-c", default_factory=list
    )
    source_url: bool = opt("Add a source_url column", default=False)

    async def open(self, ctx) -> None:
        self._rows: list[dict[str, Any]] = []
        self._writer: csv.DictWriter[str] | None = None
        if self.columns:
            self._start(list(self.columns))

    def _start(self, columns: list[str]) -> None:
        self._stream, self._stdout = open_target(self.path)
        self._writer = csv.DictWriter(self._stream, fieldnames=columns, extrasaction="ignore")
        self._writer.writeheader()

    def _row(self, event: Event) -> dict[str, Any]:
        row = flatten(event.data)
        if self.source_url:
            row["source_url"] = event.source_url
        return row

    async def write(self, event: Event) -> None:
        if self._writer is not None:
            self._writer.writerow(self._row(event))
            if self._stdout:
                self._stream.flush()
        else:
            self._rows.append(self._row(event))

    async def close(self) -> None:
        if self._writer is None:
            columns: dict[str, None] = {}
            for row in self._rows:
                columns.update(dict.fromkeys(row))
            self._start(list(columns))
            assert self._writer is not None
            self._writer.writerows(self._rows)
        if self._stdout:
            self._stream.flush()
        else:
            self._stream.close()
