"""Hacker News stories with 300 points or more (hn-top) and Show HN posts with 100 or more
(show-hn) since 2007, from the official Hacker News search API (Algolia), written as those
feeds write them.

    research/.venv/bin/python research/public/hn_history.py OUT.jsonl 2007-01-01 2026-09-26
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime

import httpx

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
SEARCH = "https://hn.algolia.com/api/v1/search_by_date"
FEEDS = {"hn-top": ("story", 300), "show-hn": ("show_hn", 100)}


def window(http: httpx.Client, tag: str, points: int, start: int, end: int) -> list[dict]:
    params = {
        "tags": tag,
        "numericFilters": f"points>{points},created_at_i>={start},created_at_i<{end}",
        "hitsPerPage": 1000,
    }
    for attempt in range(5):
        response = http.get(SEARCH, params=params)
        if response.status_code < 500 and response.status_code != 429:
            break
        time.sleep(10 * (attempt + 1))
    response.raise_for_status()
    document = response.json()
    time.sleep(0.5)
    if document.get("nbHits", 0) > len(document.get("hits") or []) and end - start > 3600:
        middle = (start + end) // 2
        return window(http, tag, points, start, middle) + window(http, tag, points, middle, end)
    return document.get("hits") or []


def main(out: str, first: str, last: str) -> None:
    start = int(datetime.fromisoformat(first).replace(tzinfo=UTC).timestamp())
    stop = int(datetime.fromisoformat(last).replace(tzinfo=UTC).timestamp())
    written = 0
    with (
        httpx.Client(headers=AGENT, timeout=60) as http,
        open(out, "w", encoding="utf-8") as lines,
    ):
        for feed, (tag, points) in FEEDS.items():
            at = start
            while at < stop:
                end = min(at + 30 * 86400, stop)
                hits = window(http, tag, points, at, end)
                for hit in hits:
                    if not hit.get("title"):
                        continue
                    hn = f"https://news.ycombinator.com/item?id={hit['objectID']}"
                    entry = {
                        "feed": feed,
                        "title": hit["title"],
                        "summary": f"{hit.get('points')} points and {hit.get('num_comments') or 0} "
                        f"comments on Hacker News: {hn}",
                        "link": hit.get("url") or hn,
                        "date": hit["created_at"][:19] + "Z",
                    }
                    lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
                written += len(hits)
                at = end
            print(feed, written, flush=True)
    print(written, "stories")


if __name__ == "__main__":
    main(*sys.argv[1:4])
