"""Every day a large stablecoin's supply moved $100M or more (minted or burned), as items of the
stablecoin-supply feed with its titles, from DefiLlama's open stablecoin data. A coin counts
while its supply is $1B or more, so coins that were large once (BUSD, TUSD, TerraUSD) are in.

    research/.venv/bin/python research/public/stablecoin_history.py OUT.jsonl
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime

import httpx

from unlimitedpipe.expr import short_number

LIST = "https://stablecoins.llama.fi/stablecoins?includePrices=false"
ONE = "https://stablecoins.llama.fi/stablecoin/{}"
AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
ONCE_LARGE = {"BUSD", "TUSD", "UST", "USTC", "FDUSD", "USDP", "FRAX", "GUSD", "HUSD", "USDN"}


def supply(point: dict) -> float | None:
    value = (point.get("circulating") or {}).get("peggedUSD")
    return float(value) if isinstance(value, (int, float)) else None


def main(out: str) -> None:
    assets = httpx.get(LIST, headers=AGENT, timeout=60).json()["peggedAssets"]
    chosen = [a for a in assets if (supply(a) or 0) >= 1e9 or a.get("symbol") in ONCE_LARGE]
    written = 0
    with open(out, "w", encoding="utf-8") as lines:
        for asset in chosen:
            history = httpx.get(ONE.format(asset["id"]), headers=AGENT, timeout=120).json()
            points = sorted(
                (
                    (p["date"], supply(p))
                    for p in history.get("tokens", [])
                    if supply(p) is not None
                ),
                key=lambda p: int(p[0]),
            )
            count = 0
            for (_, before), (day, now) in zip(points, points[1:]):
                change = now - before
                if now < 1e9 or abs(change) < 1e8:
                    continue
                verb = "minted" if change > 0 else "burned"
                date = datetime.fromtimestamp(int(day), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                symbol = asset["symbol"]
                item = {
                    "feed": "stablecoin-supply",
                    "title": f"{symbol} {verb} ${short_number(abs(change))} in a day, "
                    f"supply now ${short_number(now)}",
                    "summary": f"{asset['name']} ({symbol}): supply {verb} "
                    f"${short_number(abs(change))} in 24 hours, from DefiLlama.",
                    "link": f"https://defillama.com/stablecoin/{asset.get('gecko_id') or asset['id']}",
                    "date": date,
                }
                lines.write(json.dumps(item, ensure_ascii=False) + "\n")
                count += 1
                written += 1
            print(asset["symbol"], count, flush=True)
            time.sleep(1)
    print(written, "moves")


if __name__ == "__main__":
    main(sys.argv[1])
