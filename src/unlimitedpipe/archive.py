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
    """The identity of an item across runs: its feed, link and title. Both, because some feeds
    link every item to the same page (a list of hacks, a weekly volcano report), and the same
    story can arrive twice from two sources with a title that differs only in case."""
    title = " ".join(str(item.get("title") or "").split()).casefold()
    basis = f"{item.get('feed')}\n{item.get('link') or ''}\n{title}"
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
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict):
                    keys.add(item_key(entry))  # not the stored key: older ones were link-only
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


MONTH_NAMES = {
    name: number
    for number, names in enumerate(
        (
            "january jan",
            "february feb",
            "march mar",
            "april apr",
            "may",
            "june jun",
            "july jul",
            "august aug",
            "september sep sept",
            "october oct",
            "november nov",
            "december dec",
        ),
        1,
    )
    for name in names.split()
}
_PERIOD = re.compile(
    r"\b(?:(?P<month>" + "|".join(sorted(MONTH_NAMES, key=len, reverse=True)) + r")\.?\s+)?"
    r"(?P<year>(?:19|20)\d\d)(?:-(?P<iso>0[1-9]|1[0-2]))?\b"
    r"|\b(?P<relative>last|this)\s+year\b",
    re.IGNORECASE,
)


def named_period(text: str, today: str) -> tuple[str, str, list[str]] | None:
    """The months a question names, as the first and last (YYYY-MM), and the words that named
    them: "earthquakes in 2023", "rules in march 2025", "2025-03", "last year". None when it
    names no period, or one after ``today`` (an ISO date)."""
    match = _PERIOD.search(text)
    if match is None:
        return None
    this_year = int(today[:4])
    if match["relative"]:
        year = this_year - (match["relative"].casefold() == "last")
        return f"{year}-01", f"{year}-12", [w.casefold() for w in match[0].split()]
    year = int(match["year"])
    if year > this_year:
        return None  # "python 2027 roadmap" is not in the past
    said = [match["year"] if not match["iso"] else f"{year}-{match['iso']}"]
    if match["iso"]:
        month = f"{year}-{match['iso']}"
        return month, month, said
    if match["month"]:
        month = f"{year}-{MONTH_NAMES[match['month'].casefold()]:02d}"
        return month, month, [match["month"].casefold(), *said]
    return f"{year}-01", f"{year}-12", said


def parse_since(value: str) -> str:
    """``2026-08`` or ``2026-08-15`` -> the same, checked."""
    value = value.strip()
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?", value):
        raise ValueError(
            f"--since takes a month or a day, like 2026-08 or 2026-08-15, not {value!r}"
        )
    return value
