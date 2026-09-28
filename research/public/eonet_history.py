"""NASA EONET's natural events (wildfires, storms, volcanoes, floods, ice, dust) as items of the
natural-events feed, with its titles, year by year. NASA data, public domain.

    research/.venv/bin/python research/public/eonet_history.py OUT.jsonl FROM_YEAR TO_YEAR
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime

import httpx

API = "https://eonet.gsfc.nasa.gov/api/v3/events"
AGENT = "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"


def main(out: str, first: str, last: str) -> None:
    seen: set[str] = set()
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(out, "w", encoding="utf-8") as lines:
        for year in range(int(first), int(last) + 1):
            response = httpx.get(
                API,
                params={"status": "all", "start": f"{year}-01-01", "end": f"{year}-12-31"},
                headers={"User-Agent": AGENT},
                timeout=120,
            )
            response.raise_for_status()
            count = 0
            for event in response.json().get("events", []):
                if event["id"] in seen or not (event.get("geometry") and event.get("sources")):
                    continue
                # no source to link to, or dated after today (EONET lists some ahead)
                if not event["sources"][0].get("url") or str(event["geometry"][0]["date"]) > now:
                    continue
                seen.add(event["id"])
                first_seen = str(event["geometry"][0]["date"])
                source = event["sources"][0]
                item = {
                    "feed": "natural-events",
                    "title": f"{event['categories'][0]['title']}: {event['title']}",
                    "summary": f"Reported by {source['id']}, first seen {first_seen[:10]}. "
                    "Tracked by NASA EONET.",
                    "link": source["url"],
                    "date": first_seen,
                }
                lines.write(json.dumps(item, ensure_ascii=False) + "\n")
                count += 1
            print(year, count, "events", flush=True)
            time.sleep(1)


if __name__ == "__main__":
    main(*sys.argv[1:4])
