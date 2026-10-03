"""New US federal contracts or grants of $100M or more, year by year since 2008, as items of the
us-contracts and us-grants feeds, from USAspending.gov's API (public).

    research/.venv/bin/python research/public/usaspending_history.py OUT.jsonl 2008 2026
"""

from __future__ import annotations

import json
import sys
import time

import httpx

from unlimitedpipe.sources.usaspending import FIELDS, KINDS, SEARCH, award

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
FEEDS = {"contracts": "us-contracts", "grants": "us-grants"}
MIN_VALUE = 100_000_000


def year_of(http: httpx.Client, kind: str, year: int) -> list[dict]:
    found, page = [], 1
    while True:
        body = {
            "filters": {
                "award_type_codes": KINDS[kind],
                "time_period": [
                    {
                        "start_date": f"{year}-01-01",
                        "end_date": f"{year}-12-31",
                        "date_type": "new_awards_only",
                    }
                ],
                "award_amounts": [{"lower_bound": MIN_VALUE}],
            },
            "fields": FIELDS,
            "sort": "Award Amount",
            "order": "desc",
            "limit": 100,
            "page": page,
        }
        for attempt in range(4):
            response = http.post(SEARCH, json=body)
            if response.status_code < 500:
                break
            time.sleep(10 * (attempt + 1))
        response.raise_for_status()
        document = response.json()
        for row in document.get("results") or []:
            item = award(row, kind)
            if item and item["published_at"][:4] == str(year):
                found.append(item)
        if not (document.get("page_metadata") or {}).get("hasNext"):
            return found
        page += 1
        time.sleep(1)


def main(out: str, first: str, last: str) -> None:
    written = 0
    with (
        open(out, "w", encoding="utf-8") as lines,
        httpx.Client(headers=AGENT, timeout=120) as http,
    ):
        for kind, feed in FEEDS.items():
            for year in range(int(first), int(last) + 1):
                found = year_of(http, kind, year)
                for item in found:
                    entry = {
                        "feed": feed,
                        "title": item["title"],
                        "summary": item["summary"],
                        "link": item["link"],
                        "date": item["published_at"],
                    }
                    lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
                written += len(found)
                print(kind, year, len(found), flush=True)
    print(written, "awards")


if __name__ == "__main__":
    main(*sys.argv[1:4])
