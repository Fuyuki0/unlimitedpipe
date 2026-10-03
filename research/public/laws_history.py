"""Every US public law from the 93rd Congress (1973) on, as items of the us-new-laws feed, with
its titles, from the congress.gov API (Library of Congress; public domain). Needs a free
api.data.gov key in $CONGRESS_API_KEY (sent as a header, never in a URL).

    CONGRESS_API_KEY=... research/.venv/bin/python research/public/laws_history.py OUT.jsonl
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

import httpx

API = "https://api.congress.gov/v3/law/{}"
FIRST, LAST = 93, 119
KIND = {
    "HR": "house-bill",
    "S": "senate-bill",
    "HJRES": "house-joint-resolution",
    "SJRES": "senate-joint-resolution",
}
CODE = {"HR": "H.R.", "S": "S.", "HJRES": "H.J.Res.", "SJRES": "S.J.Res."}


def nth(number: int) -> str:
    if number % 100 in (11, 12, 13):
        return f"{number}th"
    return f"{number}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th') }"


def item(bill: dict) -> dict | None:
    action = bill.get("latestAction") or {}
    found = re.search(r"No: ([0-9-]+)", action.get("text") or "")
    laws = bill.get("laws") or []
    number = found[1] if found else (laws[0].get("number") if laws else None)
    kind = str(bill.get("type") or "")
    if not (number and action.get("actionDate") and kind in KIND):
        return None
    congress = nth(int(bill["congress"]))
    return {
        "feed": "us-new-laws",
        "title": f"New law: {bill.get('title')} (Public Law {number})",
        "summary": f"{CODE[kind]} {bill['number']} of the {congress} Congress became Public Law "
        f"{number} on {action['actionDate']}.",
        "link": f"https://www.congress.gov/bill/{congress}-congress/{KIND[kind]}/{bill['number']}",
        "date": f"{action['actionDate']}T00:00:00Z",
    }


def main(out: str) -> None:
    headers = {
        "X-Api-Key": os.environ["CONGRESS_API_KEY"],
        "User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)",
    }
    written = 0
    with (
        open(out, "w", encoding="utf-8") as lines,
        httpx.Client(headers=headers, timeout=120) as http,
    ):
        for congress in range(FIRST, LAST + 1):
            offset, count = 0, 0
            while True:
                response = http.get(
                    API.format(congress), params={"format": "json", "limit": 250, "offset": offset}
                )
                response.raise_for_status()
                bills = response.json().get("bills") or []
                for bill in bills:
                    if entry := item(bill):
                        lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
                        count += 1
                if len(bills) < 250:
                    break
                offset += 250
                time.sleep(1)
            written += count
            print(congress, count, flush=True)
            time.sleep(1)
    print(written, "laws")


if __name__ == "__main__":
    main(sys.argv[1])
