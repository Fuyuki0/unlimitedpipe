"""UK Parliament bills since 2007, each major stage (first, second and third readings in each
house, and Royal Assent) as an item of the uk-bills feed, written as the feed writes them, from
the UK Parliament's bills API (Open Parliament Licence).

    research/.venv/bin/python research/public/uk_bills_history.py OUT.jsonl 2026-09-26
"""

from __future__ import annotations

import json
import sys
import time

import httpx

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
BILLS = "https://bills-api.parliament.uk/api/v1/Bills?take=100&skip={skip}&SortOrder=DateUpdatedAscending"
STAGES = "https://bills-api.parliament.uk/api/v1/Bills/{bill}/Stages?take=100"
MAJOR = {"1st reading", "2nd reading", "3rd reading", "Royal Assent"}


def _get(http: httpx.Client, url: str):
    for attempt in range(5):
        response = http.get(url)
        if response.status_code < 500 and response.status_code != 429:
            response.raise_for_status()
            time.sleep(0.5)
            return response.json()
        time.sleep(10 * (attempt + 1))
    response.raise_for_status()
    return None


def main(out: str, before: str) -> None:
    written = 0
    with (
        httpx.Client(headers=AGENT, timeout=30) as http,
        open(out, "w", encoding="utf-8") as lines,
    ):
        skip, bills = 0, []
        while True:
            page = _get(http, BILLS.format(skip=skip))
            bills += page["items"]
            skip += 100
            if skip >= page["totalResults"]:
                break
        for number, bill in enumerate(bills, 1):
            title = bill["shortTitle"]
            for stage in _get(http, STAGES.format(bill=bill["billId"]))["items"]:
                name, house = stage.get("description"), stage.get("house") or ""
                sittings = [s["date"] for s in stage.get("stageSittings") or [] if s.get("date")]
                if name not in MAJOR or not sittings or min(sittings)[:10] >= before:
                    continue
                shown = "Royal Assent, now law" if name == "Royal Assent" else name
                where = f" ({house})" if house and house != "Unassigned" else ""
                summary = f"The {title} reached {name}" + (f" in the {house}" if where else "")
                entry = {
                    "feed": "uk-bills",
                    "title": f"{title}: {shown}{where}",
                    "summary": f"{summary}; it started in the {bill['originatingHouse']}. "
                    "UK Parliament bills service.",
                    "link": f"https://bills.parliament.uk/bills/{bill['billId']}",
                    "date": min(sittings)[:19] + "Z",
                }
                lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
                written += 1
            if number % 50 == 0:
                print(number, len(bills), written, flush=True)
    print(written, "stages")


if __name__ == "__main__":
    main(*sys.argv[1:3])
