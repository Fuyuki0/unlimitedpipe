"""The Event: the one structure every stage of a pipeline exchanges.

Sources emit events, operators transform them, outputs consume them. Between processes they
travel as one JSON object per line (JSONL) with the envelope below.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from unlimitedpipe.errors import InputError

SCHEMA = "unlimitedpipe.event/1"
SCHEMA_PREFIX = "unlimitedpipe.event/"


_now_cache: tuple[int, str] = (0, "")


def utcnow() -> str:
    """Current time as an ISO 8601 UTC string, second precision (formatted once per second)."""
    global _now_cache
    second = int(time.time())
    if _now_cache[0] != second:
        _now_cache = (second, datetime.fromtimestamp(second, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return _now_cache[1]


def iso(value: datetime | str | None) -> str | None:
    """Normalize a datetime to an ISO 8601 UTC string; strings pass through."""
    if value is None or isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value: Any) -> datetime | None:
    """A point in time from ISO 8601 or RFC 2822 text, or a Unix time in seconds,
    milliseconds (as JavaScript and the USGS API send it) or microseconds. Naive times are
    taken as UTC; anything else is None."""
    if isinstance(value, str):
        text = value.strip()
        try:
            value = float(text)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                try:
                    parsed = parsedate_to_datetime(text)
                except (TypeError, ValueError, IndexError):
                    return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    seconds = float(value)
    if abs(seconds) >= 1e14:
        seconds /= 1e6
    elif abs(seconds) >= 1e11:
        seconds /= 1e3
    try:
        return datetime.fromtimestamp(seconds, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def content_hash(*parts: Any) -> str:
    """Stable SHA-256 over JSON-serializable parts."""
    return hashlib.sha256(canonical_json(parts).encode()).hexdigest()


@dataclass(slots=True)
class Event:
    """A single observation of public data, with its provenance.

    ``key`` is the stable identity of the thing observed (a product URL + SKU, a feed item GUID).
    ``diff`` and ``dedupe`` use it. ``id`` identifies this observation: it changes when the data
    changes.
    """

    source: str
    type: str = "record"
    data: dict[str, Any] = field(default_factory=dict)
    source_url: str | None = None
    key: str | None = None
    timestamp: str | None = None
    observed_at: str = field(default_factory=utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: list[dict[str, Any]] = field(default_factory=list)
    id: str = ""

    def __post_init__(self) -> None:
        self.timestamp = iso(self.timestamp)
        if not self.id:
            self.id = content_hash(self.source, self.key or self.source_url, self.data)[:20]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "id": self.id,
            "source": self.source,
            "type": self.type,
            "key": self.key,
            "source_url": self.source_url,
            "timestamp": self.timestamp,
            "observed_at": self.observed_at,
            "data": self.data,
            "metadata": self.metadata,
            "provenance": self.provenance,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"), default=str)

    @classmethod
    def from_dict(cls, obj: Any) -> Event:
        """Build an event from a JSON value.

        Objects carrying the ``unlimitedpipe.event/N`` schema marker are read as envelopes.
        Anything else (plain JSON from jq, an API, a file) is wrapped as a ``record`` event, so
        UnlimitedPipe composes with tools that know nothing about it.
        """
        if not is_envelope(obj):
            data = obj if isinstance(obj, dict) else {"value": obj}
            return cls(source="stdin", type="record", data=data)
        schema = obj["schema"]
        if schema != SCHEMA:
            raise InputError(
                f"unsupported event schema {schema!r}",
                hint=f"this version reads {SCHEMA!r}; upgrade UnlimitedPipe to read newer events",
            )
        data = obj.get("data")
        return cls(
            source=str(obj.get("source") or "unknown"),
            type=str(obj.get("type") or "record"),
            data=data if isinstance(data, dict) else {"value": data},
            source_url=obj.get("source_url"),
            key=obj.get("key"),
            timestamp=obj.get("timestamp"),
            observed_at=obj.get("observed_at") or utcnow(),
            metadata=obj.get("metadata") or {},
            provenance=list(obj.get("provenance") or []),
            id=obj.get("id") or "",
        )

    @classmethod
    def from_json(cls, line: str | bytes) -> Event:
        return cls.from_dict(json.loads(line))

    @property
    def label(self) -> str:
        """Short human name for the thing this event describes."""
        for name in ("title", "name", "label"):
            value = self.data.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return self.key or self.source_url or self.id


def is_envelope(obj: Any) -> bool:
    return (
        isinstance(obj, dict)
        and isinstance(obj.get("schema"), str)
        and obj["schema"].startswith(SCHEMA_PREFIX)
    )
