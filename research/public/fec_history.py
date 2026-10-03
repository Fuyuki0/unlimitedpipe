"""Outside spending of $250K+ in US federal elections since the 2010 cycle, as items of the
us-outside-spending feed, from the FEC's bulk files (public). www.fec.gov asks for ten
seconds between requests.

    research/.venv/bin/python research/public/fec_history.py OUT.jsonl 2010 2026
"""

from __future__ import annotations

import json
import sys
import time

import httpx

from unlimitedpipe.sources.fec import BULK, committees, outside_spending

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}


def main(out: str, first: str, last: str) -> None:
    written = 0
    with (
        open(out, "w", encoding="utf-8") as lines,
        httpx.Client(headers=AGENT, timeout=300, follow_redirects=True) as http,
    ):
        for cycle in range(int(first), int(last) + 1, 2):
            base = BULK.format(cycle=cycle)
            names = committees(
                http.get(f"{base}cm{cycle % 100:02d}.zip").raise_for_status().content
            )
            time.sleep(10)
            table = http.get(f"{base}independent_expenditure_{cycle}.csv").raise_for_status()
            time.sleep(10)
            found = outside_spending(table.content.decode("utf-8", "replace"), names, 250000)
            for item in found:
                entry = {
                    "feed": "us-outside-spending",
                    "title": item["title"],
                    "summary": item["summary"],
                    "link": item["link"],
                    "date": item["published_at"],
                }
                lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
            written += len(found)
            print(cycle, len(found), flush=True)
    print(written, "expenditures")


if __name__ == "__main__":
    main(*sys.argv[1:4])
