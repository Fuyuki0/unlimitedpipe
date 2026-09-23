"""Dotted field paths: ``title``, ``offers.0.price``, ``metadata.status``.

Resolution rule for events: a path is looked up in ``data`` first, then in the envelope.
``data.title`` and ``metadata.status`` address a place explicitly.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from unlimitedpipe.event import Event


class _Missing:
    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING: Any = _Missing()

ENVELOPE_FIELDS = frozenset(
    {
        "id",
        "source",
        "type",
        "key",
        "source_url",
        "timestamp",
        "observed_at",
        "metadata",
        "provenance",
    }
)


def split_path(path: str) -> list[str]:
    parts = [part for part in path.strip().split(".") if part]
    if not parts:
        raise ValueError(f"empty field path {path!r}")
    return parts


def get_path(value: Any, parts: list[str]) -> Any:
    """Walk ``parts`` through dicts and lists. Returns ``MISSING`` when absent."""
    for part in parts:
        if isinstance(value, dict):
            if part not in value:
                return MISSING
            value = value[part]
        elif isinstance(value, list):
            try:
                value = value[int(part)]
            except (ValueError, IndexError):
                return MISSING
        else:
            return MISSING
    return value


def resolve(event: Event, path: str | list[str]) -> Any:
    """Look up a field on an event: ``data`` first, then the envelope."""
    parts = split_path(path) if isinstance(path, str) else path
    head = parts[0]
    if head == "data":
        return get_path(event.data, parts[1:])
    value = get_path(event.data, parts)
    if value is not MISSING:
        return value
    if head in ENVELOPE_FIELDS:
        return get_path(getattr(event, head), parts[1:])
    return MISSING


def set_path(target: dict[str, Any], parts: list[str], value: Any) -> None:
    for part in parts[:-1]:
        child = target.get(part)
        if not isinstance(child, dict):
            child = target[part] = {}
        target = child
    target[parts[-1]] = value


def delete_path(target: dict[str, Any], parts: list[str]) -> None:
    for part in parts[:-1]:
        child = target.get(part)
        if not isinstance(child, dict):
            return
        target = child
    target.pop(parts[-1], None)


def flatten(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested dicts to dotted keys; lists become JSON strings. Used by CSV output."""
    flat: dict[str, Any] = {}
    for key, item in value.items():
        name = f"{prefix}{key}"
        if isinstance(item, dict) and item:
            flat.update(flatten(item, f"{name}."))
        elif isinstance(item, (list, dict)):
            flat[name] = json.dumps(item, ensure_ascii=False, default=str)
        else:
            flat[name] = item
    return flat


def iter_strings(value: Any):
    """Yield every string inside a nested structure."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)
