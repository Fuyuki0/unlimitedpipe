"""The weekly US regular gasoline price (EIA, via FRED's GASREGW) as items of the us-indicators
feed, with its titles, from 1990. Public data.

    research/.venv/bin/python research/public/gas_history.py OUT.jsonl
"""

from __future__ import annotations

import csv
import io
import json
import sys

import httpx

FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=GASREGW"
AGENT = "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"
NAME = "US regular gasoline price"


def main(out: str) -> None:
    response = httpx.get(FRED, headers={"User-Agent": AGENT}, timeout=60)
    response.raise_for_status()
    written = 0
    with open(out, "w", encoding="utf-8") as lines:
        for row in csv.DictReader(io.StringIO(response.text)):
            date, value = row["observation_date"], row["GASREGW"]
            if not value or value == ".":
                continue
            period = f"week of {date}"
            item = {
                "feed": "us-indicators",
                "title": f"{NAME}: ${value} a gallon ({period})",
                "summary": f"{NAME} for {period}, from FRED (Federal Reserve Bank of St. Louis). "
                "Data, not investment advice.",
                "link": "https://fred.stlouisfed.org/series/GASREGW",
                "date": f"{date}T12:30:00Z",
            }
            lines.write(json.dumps(item, ensure_ascii=False) + "\n")
            written += 1
    print(written, "weeks")


if __name__ == "__main__":
    main(sys.argv[1])
