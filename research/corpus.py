"""Load the items of a downloaded feed catalog (`unlimited mirror --feeds DIR`) for research.

Each item comes from a feed's JSON file or from the monthly archive; the same item is kept
once. Items are news headlines and summaries owned by their publishers: use them for
research here, and do not publish them or models trained on them.
"""

from __future__ import annotations

import json
from pathlib import Path


def load(folder: str | Path) -> list[dict]:
    """Items as {feed, title, summary, link, date}, each once."""
    folder = Path(folder).expanduser()
    items: dict[tuple, dict] = {}

    def add(feed: str, title: str, summary: str, link: str, date: str) -> None:
        if title:
            key = (feed, link, " ".join(title.split()).casefold())
            items.setdefault(
                key,
                {
                    "feed": feed,
                    "title": title,
                    "summary": summary or "",
                    "link": link or "",
                    "date": date or "",
                },
            )

    for path in sorted(folder.glob("*.json")):
        if path.name == "feeds.json":
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for entry in document.get("items", []):
            text = entry.get("content_text") or ""
            add(
                path.stem,
                entry.get("title") or "",
                "" if text == entry.get("title") else text,
                entry.get("url") or "",
                entry.get("date_published") or "",
            )
    for path in sorted((folder / "archive").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            add(
                entry["feed"],
                entry.get("title") or "",
                entry.get("summary") or "",
                entry.get("link") or "",
                entry.get("date") or "",
            )
    return list(items.values())
