"""A catalog's archive: every item it ever listed, in one file per month.

`feeds.json` holds only the latest items of each feed. After every run, new items are also
appended to ``archive/YYYY-MM.jsonl`` (by the item's date, or when it was first seen), each
once, so `search --since` and `ask --since` can look back months. The files only grow at the
end, which keeps them cheap to store in Git and to serve.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ARCHIVE_DIR = "archive"
INDEX = "index.json"
SCHEMA = "unlimitedpipe.archive/1"
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_DATE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])(-\d{2})?")


def item_key(item: dict[str, Any]) -> str:
    """The identity of an item across runs: its feed and its link (or title)."""
    basis = f"{item.get('feed')}\n{item.get('link') or item.get('title') or ''}"
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def month_of(item: dict[str, Any], now: str) -> str:
    date = str(item.get("date") or "")
    return date[:7] if _DATE.match(date) else now[:7]


def _known(path: Path) -> set[str]:
    keys = set()
    try:
        with path.open(encoding="utf-8") as lines:
            for line in lines:
                try:
                    keys.add(json.loads(line)["key"])
                except (ValueError, KeyError, TypeError):
                    continue
    except OSError:
        pass
    return keys


def append(site: Path, items: list[dict[str, Any]], now: str) -> dict[str, int]:
    """Add the items the archive does not have yet; returns how many were added per month."""
    folder = site / ARCHIVE_DIR
    by_month: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_month.setdefault(month_of(item, now), []).append(item)
    added: dict[str, int] = {}
    for month, entries in sorted(by_month.items()):
        path = folder / f"{month}.jsonl"
        known = _known(path)
        new = []
        for item in entries:
            key = item_key(item)
            if key not in known:
                known.add(key)
                new.append({**item, "key": key, "seen": now})
        if new:
            folder.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as out:
                for entry in new:
                    out.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
            added[month] = len(new)
    if added:
        write_index(folder)
    return added


def write_index(folder: Path) -> None:
    months = []
    for path in sorted(folder.glob("*.jsonl"), reverse=True):
        if _MONTH.match(path.stem):
            with path.open(encoding="utf-8") as lines:
                count = sum(1 for line in lines if line.strip())
            months.append({"month": path.stem, "file": path.name, "items": count})
    index = {"schema": SCHEMA, "months": months}
    (folder / INDEX).write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")


def parse_since(value: str) -> str:
    """``2026-08`` or ``2026-08-15`` -> the same, checked."""
    value = value.strip()
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?", value):
        raise ValueError(
            f"--since takes a month or a day, like 2026-08 or 2026-08-15, not {value!r}"
        )
    return value
