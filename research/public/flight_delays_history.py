"""US airports' worst days since October 1987, from the Bureau of Transportation Statistics'
on-time data (every domestic flight of the large airlines; public domain), as items of the
us-flight-delays feed: an airport's day with 100 departures or more where a quarter or more were
cancelled, or a quarter or more left an hour late or more. One month's file (about 27 MB) is
read at a time and deleted.

    research/.venv/bin/python research/public/flight_delays_history.py OUT.jsonl 1987-10 2026-07
"""

from __future__ import annotations

import collections
import csv
import io
import json
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import httpx

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
FILE = (
    "https://transtats.bts.gov/PREZIP/"
    "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{year}_{month}.zip"
)
LINK = "https://www.transtats.bts.gov/ONTIME/Departures.aspx"
MIN_FLIGHTS, SHARE = 100, 0.25
CAUSES = {"A": "airline", "B": "weather", "C": "air traffic control", "D": "security"}


def month_days(path: Path) -> list[dict]:
    days: dict[tuple[str, str], collections.Counter] = collections.defaultdict(collections.Counter)
    cities: dict[str, str] = {}
    with zipfile.ZipFile(path) as archive:
        name = next(n for n in archive.namelist() if n.endswith(".csv"))
        rows = csv.DictReader(io.TextIOWrapper(archive.open(name), encoding="latin-1"))
        for row in rows:
            day, origin = row["FlightDate"], row["Origin"]
            count = days[(day, origin)]
            count["flights"] += 1
            cities.setdefault(origin, row["OriginCityName"])
            if row["Cancelled"] in ("1", "1.00"):
                count["cancelled"] += 1
                count[f"cause:{row.get('CancellationCode') or ''}"] += 1
            elif row["DepDelayMinutes"] and float(row["DepDelayMinutes"]) >= 60:
                count["hour"] += 1
    found = []
    for (day, origin), count in days.items():
        flights = count["flights"]
        if flights < MIN_FLIGHTS:
            continue
        cancelled, hour = count["cancelled"] / flights, count["hour"] / flights
        if cancelled < SHARE and hour < SHARE:
            continue
        parts = []
        if cancelled >= 0.01:
            parts.append(f"{cancelled:.0%} cancelled")
        parts.append(f"{hour:.0%} delayed an hour or more")
        causes = {k[6:]: v for k, v in count.items() if k.startswith("cause:") and k[6:]}
        cause = CAUSES.get(max(causes, key=causes.get)) if causes else None
        city = cities.get(origin, "")
        title = f"Bad day at {origin} ({city}): {' and '.join(parts)} of {flights:,} departures"
        summary = (
            f"On {day}, of {flights:,} departures from {origin} ({city}) by the large US "
            f"airlines, {count['cancelled']:,} were cancelled and {count['hour']:,} left an hour "
            "late or more"
            + (f"; most cancellations were put down to {cause}" if cause else "")
            + ". Bureau of Transportation Statistics on-time data."
        )
        found.append(
            {
                "feed": "us-flight-delays",
                "title": title,
                "summary": summary,
                "link": LINK,
                "date": f"{day}T00:00:00Z",
                "size": cancelled + hour,
            }
        )
    return found


def main(out: str, first: str, last: str) -> None:
    year, month = map(int, first.split("-"))
    end = tuple(map(int, last.split("-")))
    written = 0
    with (
        httpx.Client(headers=AGENT, timeout=600, follow_redirects=True) as http,
        open(out, "a", encoding="utf-8") as lines,
        tempfile.TemporaryDirectory() as folder,
    ):
        while (year, month) <= end:
            path = Path(folder) / "month.zip"
            for attempt in range(5):
                try:
                    with http.stream("GET", FILE.format(year=year, month=month)) as response:
                        if response.status_code == 404:
                            break
                        response.raise_for_status()
                        with path.open("wb") as data:
                            for chunk in response.iter_bytes(1 << 20):
                                data.write(chunk)
                    break
                except httpx.HTTPError:
                    time.sleep(30 * (attempt + 1))
            if path.exists():
                found = month_days(path)
                for entry in found:
                    entry.pop("size")
                    lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
                lines.flush()
                written += len(found)
                path.unlink()
                print(year, month, len(found), flush=True)
            else:
                print(year, month, "no file", flush=True)
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
            time.sleep(2)
    print(written, "bad days")


if __name__ == "__main__":
    main(*sys.argv[1:4])
