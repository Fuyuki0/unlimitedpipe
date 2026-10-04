"""Government announcements as items of two feeds, written as those feeds write them:

- canada-government: Government of Canada news since 2015, from canada.ca's news API, read
  backwards a thousand at a time;
- australia-government: the Prime Minister of Australia's media releases, statements and
  transcripts, from pm.gov.au's media pages (the current site's whole archive).

    research/.venv/bin/python research/public/gov_news_history.py OUT.jsonl 2015-01-01
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime

import httpx
from bs4 import BeautifulSoup

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
CANADA = (
    "https://api.io.canada.ca/io-server/gc/news/en/v2?sort=publishedDate&orderBy=desc"
    "&pick=1000&format=json&publishedDate%3C={before}"
)
AUSTRALIA = "https://www.pm.gov.au/media?page={page}"


def _get(http: httpx.Client, url: str) -> httpx.Response:
    for attempt in range(5):
        try:
            response = http.get(url)
            if response.status_code < 500 and response.status_code != 429:
                response.raise_for_status()
                return response
        except httpx.TransportError:
            pass
        time.sleep(15 * (attempt + 1))
    raise SystemExit(f"no answer from {url}")


def _utc(stamp: str) -> str:
    return datetime.fromisoformat(stamp).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def canada(http: httpx.Client, lines, since: str) -> int:
    before, seen, written = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"), set(), 0
    while before >= since:
        entries = _get(http, CANADA.format(before=before)).json()["feed"].get("entry") or []
        fresh = [e for e in entries if e.get("link") not in seen]
        for entry in fresh:
            seen.add(entry.get("link"))
            if not (entry.get("title") and entry.get("publishedDate")):
                continue
            item = {
                "feed": "canada-government",
                "title": " ".join(entry["title"].split()),
                "summary": " ".join((entry.get("teaser") or "").split())[:500],
                "link": entry["link"],
                "date": _utc(entry["publishedDate"]),
            }
            lines.write(json.dumps(item, ensure_ascii=False) + "\n")
            written += 1
        print("canada", before, len(entries), written, flush=True)
        if not fresh:
            break
        before = min(e["publishedDate"] for e in entries)[:19]
        time.sleep(1)
    return written


def australia(http: httpx.Client, lines) -> int:
    written, page, empty = 0, 0, 0
    while empty < 6:  # a page can come back empty now and then: stop after six in a row
        soup = BeautifulSoup(_get(http, AUSTRALIA.format(page=page)).text, "lxml")
        cards = soup.select("div.card-body")
        found = 0
        for card in cards:
            link, stamp = card.select_one("h3.card-title a"), card.select_one("time[datetime]")
            if not (link and stamp):
                continue
            kind = card.select_one(".card-text.area")
            item = {
                "feed": "australia-government",
                "title": " ".join(link.get_text().split()),
                "summary": f"{kind.get_text(strip=True)}, Prime Minister of Australia."
                if kind
                else "Prime Minister of Australia.",
                "link": "https://www.pm.gov.au" + str(link["href"]),
                "date": str(stamp["datetime"])[:19] + "Z",
            }
            lines.write(json.dumps(item, ensure_ascii=False) + "\n")
            found += 1
        print("australia", page, found, flush=True)
        if not found:  # try the same page again a little later; six misses end the list
            empty += 1
            time.sleep(120)
            continue
        written, empty, page = written + found, 0, page + 1
        time.sleep(3)
    return written


def main(out: str, since: str, only: str = "") -> None:
    """ONLY: "canada" or "australia" to read one of the two."""
    with (
        httpx.Client(headers=AGENT, timeout=120) as http,
        open(out, "w", encoding="utf-8") as lines,
    ):
        written = 0
        if only in ("", "canada"):
            written += canada(http, lines, since)
        if only in ("", "australia"):
            written += australia(http, lines)
    print(written, "announcements")


if __name__ == "__main__":
    main(*sys.argv[1:4])
