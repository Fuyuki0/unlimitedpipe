"""The ``file`` source: JSON, JSONL and CSV records, so any data can enter a pipeline."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any, Literal

from unlimitedpipe.component import Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import InputError, UnlimitedError
from unlimitedpipe.event import Event, is_envelope
from unlimitedpipe.fields import MISSING, get_path, split_path


def _detect(name: str, head: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in (".jsonl", ".ndjson"):
        return "jsonl"
    if suffix in (".csv", ".tsv"):
        return "csv"
    if suffix == ".json":
        return "json"
    stripped = head.lstrip()
    if stripped.startswith("["):
        return "json"
    if stripped.startswith("{"):
        first_line = stripped.split("\n", 1)[0].strip()
        try:
            json.loads(first_line)
            return "jsonl"
        except ValueError:
            return "json"
    return "csv"


class File(Source):
    """Read records from JSON, JSONL or CSV files, or from stdin with ``-``.

    Each record becomes a ``record`` event. JSONL written by UnlimitedPipe is read back as the
    original events, provenance included, so saved runs can be replayed through ``diff``.
    """

    name = "file"
    path: list[str] = arg("Files to read ('-' for stdin)", default_factory=list)
    format: Literal["auto", "json", "jsonl", "csv"] = opt(
        "File format (default: from the extension)", default="auto"
    )
    records: str | None = opt(
        "JSON only: path to the list of records, e.g. `data.items`", default=None, metavar="PATH"
    )
    delimiter: str | None = opt("CSV delimiter (default: `,`, or tab for .tsv)", default=None)

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("file needs a path (or '-' for stdin)")
        self._records_path = split_path(self.records) if self.records else None

    def _event(self, value: Any, source_url: str | None) -> Event:
        if is_envelope(value):
            return Event.from_dict(value)
        return Event(
            source=self.name,
            type="record",
            source_url=source_url,
            data=value if isinstance(value, dict) else {"value": value},
        )

    async def _stdin(self) -> AsyncIterator[Any]:
        """Stream JSONL from stdin line by line; JSON documents and CSV need the whole input."""
        from unlimitedpipe.jsonl import read_lines

        fmt = self.format
        buffered: list[str] = []
        lineno = 0
        async for raw in read_lines(sys.stdin.buffer):
            lineno += 1
            line = raw.decode("utf-8-sig" if lineno == 1 else "utf-8", errors="replace")
            if fmt == "auto":
                if not line.strip():
                    continue
                fmt = _detect("-", line)
            if fmt == "jsonl":
                if line.strip():
                    try:
                        yield json.loads(line)
                    except ValueError as exc:
                        raise InputError(f"stdin line {lineno} is not valid JSON: {exc}") from None
            else:
                buffered.append(line)
        if buffered:
            for value in self._parse(fmt, "stdin", "\n".join(buffered)):
                yield value

    async def collect(self, ctx: Context):
        for name in self.path:
            if name == "-":
                async for value in self._stdin():
                    yield self._event(value, None)
                continue
            try:
                text = self._read(name)
            except OSError as exc:
                error = ctx.fail(
                    UnlimitedError(f"cannot read {name}: {exc.strerror or exc}"),
                    source=self.name,
                    url=name,
                )
                if error is not None:
                    yield error
                continue
            source_url = None if name == "-" else Path(name).expanduser().resolve().as_uri()
            fmt = self.format if self.format != "auto" else _detect(name, text[:2000])
            for index, value in enumerate(self._parse(fmt, name, text)):
                if index % 1000 == 999:
                    await asyncio.sleep(0)
                yield self._event(value, source_url)

    def _read(self, name: str) -> str:
        return Path(name).expanduser().read_text(encoding="utf-8-sig", errors="replace")

    def _parse(self, fmt: str, name: str, text: str) -> Iterator[Any]:
        if fmt == "jsonl":
            for lineno, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except ValueError as exc:
                    raise InputError(f"{name} line {lineno} is not valid JSON: {exc}") from None
        elif fmt == "json":
            try:
                document = json.loads(text)
            except ValueError as exc:
                raise InputError(
                    f"{name} is not valid JSON: {exc}",
                    hint="for one JSON object per line use --format jsonl",
                ) from None
            if self._records_path is not None:
                document = get_path(document, self._records_path)
                if document is MISSING:
                    raise InputError(f"{name} has no field {self.records!r}")
            yield from document if isinstance(document, list) else [document]
        else:
            delimiter = self.delimiter or ("\t" if name.lower().endswith(".tsv") else ",")
            yield from csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
