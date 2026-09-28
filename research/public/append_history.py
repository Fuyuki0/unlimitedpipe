"""Add history items (JSONL with feed, title, summary, link and date) to a feeds site's archive,
each once, and rebuild its indexes.

    research/.venv/bin/python research/public/append_history.py SITE ITEMS.jsonl...
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

from unlimitedpipe.archive import append
from unlimitedpipe.event import utcnow


def main(site: str, files: list[str]) -> None:
    items = [
        json.loads(line)
        for file in files
        for line in Path(file).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    missing = [i for i in items if not (i.get("feed") and i.get("title") and i.get("date"))]
    if missing:
        raise SystemExit(f"{len(missing)} item(s) without feed, title or date: {missing[0]}")
    added = append(Path(site), items, utcnow())
    by_feed = collections.Counter(i["feed"] for i in items)
    print(f"{len(items)} item(s) given {dict(by_feed)}; added by month: {sum(added.values())}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
