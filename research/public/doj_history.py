"""The Justice Department's national press releases (justice.gov/opa) as items of the us-justice
feed, newest first back to a given year, from DOJ's press release API (works of the US
government). DOJ's robots.txt asks for ten seconds between requests, so this takes hours; it
appends to OUT as it goes and starts again where it stopped.

    research/.venv/bin/python research/public/doj_history.py OUT.jsonl 2018
"""

from __future__ import annotations

import html
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

API = "https://www.justice.gov/api/v1/press_releases.json"
AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
PAUSE = 10  # DOJ's Crawl-delay
PAGE = 50  # the most the API returns at once


def plain(text: str | None) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text or "")).split())


def main(out: str, first_year: str) -> None:
    target = Path(out)
    progress = target.with_suffix(".page")
    page = int(progress.read_text()) if progress.exists() else 0
    stop = datetime(int(first_year), 1, 1, tzinfo=UTC).timestamp()
    with httpx.Client(headers=AGENT, timeout=120) as client, target.open("a") as lines:
        while True:
            for attempt in range(5):
                try:
                    response = client.get(
                        API,
                        params={
                            "pagesize": PAGE,
                            "page": page,
                            "sort": "date",
                            "direction": "DESC",
                        },
                    )
                    if response.status_code < 500:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(60 * (attempt + 1))
            response.raise_for_status()
            results = response.json().get("results") or []
            if not results:
                break
            oldest = None
            for release in results:
                when = int(release.get("date") or 0)
                oldest = when if oldest is None else min(oldest, when)
                url = str(release.get("url") or "")
                # national releases; earlier administrations' are under /archives/opa/pr/
                if "/opa/pr/" not in url or not when:
                    continue
                item = {
                    "feed": "us-justice",
                    "title": plain(release.get("title")),
                    "summary": plain(release.get("teaser"))[:500],
                    "link": url,
                    "date": datetime.fromtimestamp(when, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                lines.write(json.dumps(item, ensure_ascii=False) + "\n")
            lines.flush()
            page += 1
            progress.write_text(str(page))
            if oldest is not None and oldest < stop:
                break
            time.sleep(PAUSE)
    print("done at page", page)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
