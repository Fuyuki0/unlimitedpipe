"""The ECB's reference rates of the US dollar against the baht, yen, yuan, rupee and euro, each
day all five were published, as items of the usd-rates feed (its titles), via the Frankfurter
API. The ECB allows reusing its reference rates with the source named.

    research/.venv/bin/python research/public/usd_rates_history.py OUT.jsonl FROM TO
"""

from __future__ import annotations

import json
import sys
import time

import httpx

API = "https://api.frankfurter.dev/v1/{start}..{end}"
SYMBOLS = ("THB", "JPY", "CNY", "INR", "EUR")
LINK = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html"


def main(out: str, start: str, end: str) -> None:
    written = 0
    with open(out, "w", encoding="utf-8") as lines:
        for year in range(int(start[:4]), int(end[:4]) + 1):
            first, last = max(start, f"{year}-01-01"), min(end, f"{year}-12-31")
            response = httpx.get(
                API.format(start=first, end=last),
                params={"base": "USD", "symbols": ",".join(SYMBOLS)},
                headers={"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"},
                timeout=60,
            )
            response.raise_for_status()
            for date, rates in sorted(response.json().get("rates", {}).items()):
                if not all(s in rates for s in SYMBOLS):
                    continue
                title = (
                    f"US dollar on {date}: {rates['THB']} baht, {rates['JPY']} yen, "
                    f"{rates['CNY']} yuan, {rates['INR']} rupees, {rates['EUR']} euro"
                )
                item = {
                    "feed": "usd-rates",
                    "title": title,
                    "summary": "ECB euro reference "
                    "rates, as dollar rates (via the Frankfurter API).",
                    "link": LINK,
                    "date": f"{date}T00:00:00Z",
                }
                lines.write(json.dumps(item, ensure_ascii=False) + "\n")
                written += 1
            time.sleep(1)
    print(written, "days")


if __name__ == "__main__":
    main(*sys.argv[1:4])
