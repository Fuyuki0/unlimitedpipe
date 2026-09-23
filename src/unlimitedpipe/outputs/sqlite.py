"""Keep events in a SQLite database: a queryable history, one row per distinct observation."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from unlimitedpipe.component import Output, arg, opt
from unlimitedpipe.event import Event

COLUMNS = (
    "id",
    "source",
    "type",
    "key",
    "source_url",
    "timestamp",
    "observed_at",
    "data",
    "metadata",
    "provenance",
)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


class Sqlite(Output):
    """Store events in a SQLite table for SQL queries, one row per distinct observation.

    Data, metadata and provenance are JSON columns, so SQLite's JSON functions work:
    `SELECT json_extract(data, '$.title') FROM events WHERE type = 'change'`. An event already
    stored (same id: same source, key and data) is not stored twice, so re-running a pipeline
    only adds what is new.
    """

    name = "sqlite"
    examples = (
        "unlimited rss https://hnrss.org/frontpage | unlimited sqlite news.db",
        "sqlite3 news.db \"SELECT json_extract(data, '$.title') FROM events\"",
    )

    path: str = arg("Database file (created if missing)", metavar="FILE")
    table: str = opt("Table name", default="events")

    def __post_init__(self) -> None:
        if not _IDENTIFIER.match(self.table):
            raise ValueError("--table must be a plain name: letters, digits and _")

    async def open(self, ctx) -> None:
        target = Path(self.path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(target)
        self._db.execute(
            f"""CREATE TABLE IF NOT EXISTS {self.table} (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                type TEXT NOT NULL,
                key TEXT,
                source_url TEXT,
                timestamp TEXT,
                observed_at TEXT NOT NULL,
                data TEXT NOT NULL,
                metadata TEXT NOT NULL,
                provenance TEXT NOT NULL
            )"""
        )
        for column in ("key", "observed_at", "type"):
            self._db.execute(
                f"CREATE INDEX IF NOT EXISTS {self.table}_{column} ON {self.table} ({column})"
            )
        self._pending: list[tuple[Any, ...]] = []
        self._ctx = ctx
        self._added = 0

    def _row(self, event: Event) -> tuple[Any, ...]:
        record = event.to_dict()
        for column in ("data", "metadata", "provenance"):
            record[column] = json.dumps(record[column], ensure_ascii=False, default=str)
        return tuple(record[column] for column in COLUMNS)

    def _flush(self) -> None:
        if not self._pending:
            return
        columns = ", ".join(COLUMNS)
        placeholders = ", ".join("?" for _ in COLUMNS)
        with self._db:
            cursor = self._db.executemany(
                f"INSERT OR IGNORE INTO {self.table} ({columns}) VALUES ({placeholders})",
                self._pending,
            )
        self._added += max(cursor.rowcount, 0)
        self._pending.clear()

    async def write(self, event: Event) -> None:
        self._pending.append(self._row(event))
        if len(self._pending) >= 500:
            self._flush()

    async def close(self) -> None:
        try:
            self._flush()
        finally:
            self._db.close()
        self._ctx.notice(f"sqlite: {self._added} new row(s) in {self.path} ({self.table})")
