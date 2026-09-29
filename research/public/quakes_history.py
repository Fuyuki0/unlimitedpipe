"""Earthquakes of magnitude 5.5 and above from 1900 to 2015 (the earthquakes feed's archive
starts in 2016, at 4.5), as items of that feed with its titles, from the USGS catalog. Public
domain.

    research/.venv/bin/python research/public/quakes_history.py OUT.jsonl
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime

import httpx

API = "https://earthquake.usgs.gov/fdsnws/event/1/query"
AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}


def main(out: str, first: int = 1900, last: int = 2015, magnitude: float = 5.5) -> None:
    written = 0
    with open(out, "w", encoding="utf-8") as lines:
        for year in range(first, last + 1):
            response = httpx.get(
                API,
                params={
                    "format": "geojson",
                    "minmagnitude": magnitude,
                    "starttime": f"{year}-01-01",
                    "endtime": f"{year}-12-31T23:59:59",
                    "orderby": "time-asc",
                },
                headers=AGENT,
                timeout=120,
            )
            response.raise_for_status()
            count = 0
            for quake in response.json().get("features", []):
                p = quake["properties"]
                if p.get("time") is None or not p.get("title"):
                    continue
                when = datetime.fromtimestamp(p["time"] / 1000, UTC)
                item = {
                    "feed": "earthquakes",
                    "title": p["title"],
                    "summary": f"Magnitude {p.get('mag')}, {p.get('place')}",
                    "link": p.get("url"),
                    "date": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                lines.write(json.dumps(item, ensure_ascii=False) + "\n")
                count += 1
                written += 1
            if year % 10 == 0:
                print(year, count, flush=True)
            time.sleep(1)
    print(written, "earthquakes")


if __name__ == "__main__":
    main(sys.argv[1])
