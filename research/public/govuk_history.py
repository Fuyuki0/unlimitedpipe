"""UK government announcements from GOV.UK's search API (Open Government Licence v3.0), month
by month, as items of the uk-government feed (press releases, news stories, speeches, and
statements and responses to Parliament) and the uk-sanctions feed (everything OFSI published,
and government news about sanctions), written as those feeds write them.

    research/.venv/bin/python research/public/govuk_history.py OUT.jsonl 2012-01 2026-09
"""

from __future__ import annotations

import calendar
import json
import re
import sys
import time

import httpx

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
SEARCH = "https://www.gov.uk/api/search.json"
FIELDS = ["title", "link", "public_timestamp", "description", "content_store_document_type"]
NEWS = ["press_release", "news_story", "speech", "oral_statement", "written_statement",
        "government_response"]  # fmt: skip
SANCTIONS = re.compile(
    r"sanction|general licence|penalt|designation|designated|asset freeze", re.IGNORECASE
)


def search(http: httpx.Client, params: list[tuple[str, str]]) -> list[dict]:
    found, start = [], 0
    while True:
        query = [*params, ("count", "1000"), ("start", str(start)), ("order", "public_timestamp")]
        query += [("fields", f) for f in FIELDS]
        for attempt in range(5):
            try:
                response = http.get(SEARCH, params=query)
                if response.status_code < 500 and response.status_code != 429:
                    break
            except httpx.TransportError:
                pass
            time.sleep(20 * (attempt + 1))
        response.raise_for_status()
        document = response.json()
        found += document["results"]
        start += 1000
        time.sleep(0.5)
        if start >= document["total"]:
            return found


def item(feed: str, result: dict) -> dict | None:
    if not (result.get("title") and result.get("public_timestamp") and result.get("link")):
        return None
    link = result["link"]
    return {
        "feed": feed,
        "title": result["title"].strip(),
        "summary": (result.get("description") or "").strip()[:500],
        "link": link if link.startswith("http") else f"https://www.gov.uk{link}",
        "date": result["public_timestamp"][:19] + "Z",
    }


def main(out: str, first: str, last: str) -> None:
    year, month = map(int, first.split("-"))
    end = tuple(map(int, last.split("-")))
    written = 0
    with (
        httpx.Client(headers=AGENT, timeout=60) as http,
        open(out, "w", encoding="utf-8") as lines,
    ):
        while (year, month) <= end:
            days = calendar.monthrange(year, month)[1]
            window = f"from:{year}-{month:02d}-01,to:{year}-{month:02d}-{days}"
            news = search(
                http,
                [("filter_public_timestamp", window)]
                + [("filter_content_store_document_type", kind) for kind in NEWS],
            )
            ofsi = search(
                http,
                [
                    ("filter_public_timestamp", window),
                    ("filter_organisations", "office-of-financial-sanctions-implementation"),
                ],
            )
            fcdo = [r for r in news if SANCTIONS.search(r.get("title") or "")]
            entries = [item("uk-government", r) for r in news]
            entries += [item("uk-sanctions", r) for r in ofsi]
            entries += [item("uk-sanctions", r) for r in fcdo]
            for entry in entries:
                if entry:
                    lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    written += 1
            print(year, month, len(news), len(ofsi), len(fcdo), flush=True)
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    print(written, "items")


if __name__ == "__main__":
    main(*sys.argv[1:4])
