"""Events from Wikipedia's Current events portal, month by month since 2002, as items of the
world-events feed. Text is Wikipedia's, under CC BY-SA 4.0 (credited in each summary).

    research/.venv/bin/python research/public/wikipedia_events_history.py OUT.jsonl 2002-01 2026-10
"""

from __future__ import annotations

import json
import sys
import time

import httpx

from unlimitedpipe.sources.wikipedia import event_item, events, month_page

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}


def months(first: str, last: str):
    year, month = map(int, first.split("-"))
    end = tuple(map(int, last.split("-")))
    while (year, month) <= end:
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def main(out: str, first: str, last: str) -> None:
    written = 0
    with (
        open(out, "w", encoding="utf-8") as lines,
        httpx.Client(headers=AGENT, timeout=60, follow_redirects=True) as http,
    ):
        for year, month in months(first, last):
            url = month_page(year, month)
            for attempt in range(4):
                response = http.get(url)
                if response.status_code < 500 and response.status_code != 429:
                    break
                time.sleep(15 * (attempt + 1))
            if response.status_code == 404:
                print(year, month, "no page", flush=True)
                continue
            response.raise_for_status()
            found = events(response.text)
            for event in found:
                item = event_item(event)
                entry = {
                    "feed": "world-events",
                    "title": item["title"],
                    "summary": item["summary"],
                    "link": item["link"],
                    "date": item["published_at"],
                }
                lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
            written += len(found)
            print(year, month, len(found), flush=True)
            time.sleep(1.5)
    print(written, "events")


if __name__ == "__main__":
    main(*sys.argv[1:4])
