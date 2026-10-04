"""Add history items (JSONL with feed, title, summary, link and date) to a feeds site's archive,
each once, and rebuild its indexes. Plain and compressed months are both handled.

Items of a feed dated on or after the oldest record the archive holds for that feed from the
items' own start on are left out: that period is the live feed's, written its own way, and
history items would double it. (Measured from the items' start, a feed whose older history was
added earlier can still have a later gap filled.)

    research/.venv/bin/python research/public/append_history.py SITE ITEMS.jsonl...
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

from unlimitedpipe.archive import _month_files, _text, append, lines_of
from unlimitedpipe.event import utcnow


def oldest_dates(site: Path, starts: dict[str, str]) -> dict[str, str]:
    """The oldest date of each feed's records in the archive, on or after the given start."""
    oldest: dict[str, str] = {}
    for path in _month_files(site / "archive"):
        for line in lines_of(_text(path)):
            if not line.strip():
                continue
            item = json.loads(line)
            feed, date = item.get("feed"), item.get("date")
            if feed not in starts or not date or date < starts[feed]:
                continue
            if feed not in oldest or date < oldest[feed]:
                oldest[feed] = date
    return oldest


def main(site: str, files: list[str]) -> None:
    items = [
        json.loads(line)
        for file in files
        for line in lines_of(Path(file).read_text(encoding="utf-8"))
        if line.strip()
    ]
    missing = [i for i in items if not (i.get("feed") and i.get("title") and i.get("date"))]
    if missing:
        raise SystemExit(f"{len(missing)} item(s) without feed, title or date: {missing[0]}")
    starts: dict[str, str] = {}
    for i in items:
        if i["feed"] not in starts or i["date"] < starts[i["feed"]]:
            starts[i["feed"]] = i["date"]
    oldest = oldest_dates(Path(site), starts)
    live = collections.Counter(
        i["feed"] for i in items if i["feed"] in oldest and i["date"] >= oldest[i["feed"]]
    )
    items = [i for i in items if not (i["feed"] in oldest and i["date"] >= oldest[i["feed"]])]
    added = append(Path(site), items, utcnow())
    by_feed = collections.Counter(i["feed"] for i in items)
    print(
        f"{len(items)} item(s) given {dict(by_feed)}; left out as the live period {dict(live)}; "
        f"added by month: {sum(added.values())}"
    )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
