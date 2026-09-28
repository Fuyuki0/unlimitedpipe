"""Every Federal Reserve decision that changed its federal funds target since 1990, as items of
the fed-funds-target feed (the same titles its pipeline writes), from FRED: the single target
(DFEDTAR) until 2008-12-15, then the target range (DFEDTARL, DFEDTARU).

    research/.venv/bin/python research/public/fed_history.py OUT.jsonl
"""

from __future__ import annotations

import csv
import io
import json
import sys

import httpx

FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv"
AGENT = "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"


def rows(series: str) -> list[dict[str, str]]:
    response = httpx.get(FRED, params={"id": series}, headers={"User-Agent": AGENT}, timeout=60)
    response.raise_for_status()
    return list(csv.DictReader(io.StringIO(response.text)))


def item(date: str, change: float, target: str) -> dict:
    action = "cut" if change < 0 else "raised"
    amount = f"{abs(change):.2f}"
    return {
        "feed": "fed-funds-target",
        "title": f"Federal Reserve rate decision: {action} by {amount} point, to a {target} "
        f"(effective {date})",
        "summary": f"The FOMC {action} its target for the federal funds rate by {amount} "
        f"percentage point, to {target.replace(' target range', '').replace('target of ', '')}, "
        f"effective {date}. From FRED.",
        "link": "https://fred.stlouisfed.org/series/"
        + ("DFEDTARU" if "range" in target else "DFEDTAR"),
        "date": f"{date}T00:00:00Z",
    }


def main(out: str) -> None:
    found = []
    previous = None
    for row in rows("DFEDTAR"):  # 1982-09-27 to 2008-12-15
        value = row["DFEDTAR"]
        if not value or value == ".":
            continue
        level = float(value)
        if previous is not None and level != previous and row["observation_date"] >= "1990-01-01":
            found.append(item(row["observation_date"], level - previous, f"target of {level:.2f}%"))
        previous = level
    low_rows = {r["observation_date"]: r["DFEDTARL"] for r in rows("DFEDTARL")}
    for row in rows("DFEDTARU"):  # from 2008-12-16
        value = row["DFEDTARU"]
        if not value or value == ".":
            continue
        high = float(value)
        if previous is not None and high != previous:
            low = float(low_rows[row["observation_date"]])
            found.append(
                item(
                    row["observation_date"], high - previous, f"{low:.2f}-{high:.2f}% target range"
                )
            )
        previous = high
    with open(out, "w", encoding="utf-8") as lines:
        for entry in found:
            lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(len(found), "decisions;", found[-1]["title"])


if __name__ == "__main__":
    main(sys.argv[1])
