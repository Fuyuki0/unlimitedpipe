"""Crypto history from DefiLlama's public APIs, as items of the crypto-big-moves and
stablecoin-depegs feeds, written the way those feeds write them.

- crypto-big-moves: the feed's large coins moving 10% or more from one day's price (00:00 UTC)
  to the next, from the coin's 30th day of prices on. A jump of 20% or more undone within a
  week (back within 10% of where it started) is taken as bad prices and left out.
- stablecoin-depegs: dollar stablecoins with 100M or more in circulation closing a day at $0.99
  or less, one item a coin a day, for the first 14 days of a depeg (a coin that never comes back
  is not listed for years).

    research/.venv/bin/python research/public/crypto_history.py FEEDS_DIR OUT.jsonl
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
CHART = "https://coins.llama.fi/chart/{coins}?start={start}&span={span}&period=1d"
STABLES = "https://stablecoins.llama.fi/stablecoins?includePrices=true"
STABLE_PRICES = "https://stablecoins.llama.fi/stablecoinprices"
STABLE_CHART = "https://stablecoins.llama.fi/stablecoincharts/all?stablecoin={id}"
NAMES = {"ripple": "XRP", "binancecoin": "BNB", "crypto-com-chain": "Cronos"}
ADVICE = "Data, not investment advice."


def _get(http: httpx.Client, url: str):
    for attempt in range(5):
        response = http.get(url)
        if response.status_code < 500 and response.status_code != 429:
            response.raise_for_status()
            time.sleep(1)
            return response.json()
        time.sleep(10 * (attempt + 1))
    response.raise_for_status()
    return None


def _day(stamp: int | str) -> str:
    return datetime.fromtimestamp(int(stamp), UTC).strftime("%Y-%m-%d")


def coin_name(coin: str) -> str:
    return NAMES.get(coin) or coin.replace("-", " ").title()


def big_moves(http: httpx.Client, coins: list[str]) -> list[dict]:
    found = []
    for coin in coins:
        prices: dict[str, float] = {}
        start = int(datetime(2013, 1, 1, tzinfo=UTC).timestamp())
        now = time.time()
        while start < now:
            document = _get(http, CHART.format(coins=f"coingecko:{coin}", start=start, span=500))
            points = (document.get("coins") or {}).get(f"coingecko:{coin}", {}).get("prices") or []
            for point in points:
                prices[_day(point["timestamp"])] = float(point["price"])
            # a coin without prices yet at `start` gets an empty answer: try 500 days later
            start = int(points[-1]["timestamp"]) + 86400 if points else start + 500 * 86400
        days = sorted(prices)
        for index in range(30, len(days)):
            day, before = days[index], prices[days[index - 1]]
            if (
                not before
                or (datetime.fromisoformat(day) - datetime.fromisoformat(days[index - 1])).days != 1
            ):
                continue
            value = (prices[day] / before - 1) * 100
            if abs(value) < 10:
                continue
            later = [prices[d] for d in days[index + 1 : index + 8]]
            if abs(value) >= 20 and any(abs(p / before - 1) < 0.1 for p in later):
                continue  # a jump undone within a week, back near where it started: bad prices
            name = coin_name(coin)
            moved = f"{value:+.1f}"
            found.append(
                {
                    "feed": "crypto-big-moves",
                    "title": f"{name} {moved}% in 24 hours",
                    "summary": f"{name} moved {moved}% in the 24 hours to {day} 00:00 UTC, from "
                    f"DefiLlama prices. {ADVICE} One of the biggest "
                    f"{'gainers' if value > 0 else 'losers'} among large coins that day.",
                    "link": f"https://www.coingecko.com/en/coins/{coin}",
                    "date": f"{day}T00:00:00Z",
                }
            )
        print("moves", coin, len(prices), "days", flush=True)
    return found


def depegs(http: httpx.Client) -> list[dict]:
    coins = {
        c["gecko_id"]: c
        for c in _get(http, STABLES)["peggedAssets"]
        if c.get("pegType") == "peggedUSD" and c.get("gecko_id")
    }
    low: dict[str, dict[str, float]] = {}
    for row in _get(http, STABLE_PRICES):
        if int(row["date"]) < 1262304000:  # 1970 placeholders
            continue
        for gecko, price in (row.get("prices") or {}).items():
            if gecko in coins and price is not None:
                low.setdefault(gecko, {})[_day(row["date"])] = float(price)
    found = []
    for gecko, prices in low.items():
        if not any(p <= 0.99 for p in prices.values()):
            continue
        coin = coins[gecko]
        supply = {
            _day(row["date"]): float((row.get("totalCirculating") or {}).get("peggedUSD") or 0)
            for row in _get(http, STABLE_CHART.format(id=coin["id"]))
        }
        streak, known = 0, 0.0
        for day in sorted(prices):
            price = prices[day]
            known = supply.get(day) or known  # supply data can stop before prices do
            streak = streak + 1 if price <= 0.99 else 0
            if not (0 < price <= 0.99) or streak > 14 or known < 100e6:
                continue
            off = round((1 - price) * 100, 1)
            symbol = coin["symbol"]
            found.append(
                {
                    "feed": "stablecoin-depegs",
                    "title": f"{symbol} at ${round(price, 4)}, {off}% below its $1 peg",
                    "summary": f"{coin['name']} ({symbol}) traded at ${round(price, 4)}, {off}% "
                    f"below its $1 peg, on {day}, with ${_short(known)} in circulation "
                    f"(DefiLlama). {ADVICE}",
                    "link": f"https://defillama.com/stablecoin/{gecko}",
                    "date": f"{day}T00:00:00Z",
                }
            )
        print("depegs", gecko, flush=True)
    return found


def _short(value: float) -> str:
    for size, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if value >= size:
            return f"{value / size:.3g}{unit}"
    return f"{value:.0f}"


def main(feeds: str, out: str) -> None:
    spec = Path(feeds, "crypto-big-moves.yml").read_text(encoding="utf-8")
    coins = re.findall(r"coingecko:([a-z0-9-]+)", spec)
    with httpx.Client(headers=AGENT, timeout=120) as http:
        found = big_moves(http, coins) + depegs(http)
    with open(out, "w", encoding="utf-8") as lines:
        for entry in found:
            lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(len(found), "items")


if __name__ == "__main__":
    main(*sys.argv[1:3])
