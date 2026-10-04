"""DeFi protocols losing 25% or more of their deposits (TVL) in a day, as items of the
defi-drops feed, from DefiLlama's per-protocol TVL history: protocols holding $10M or more
today (exchanges left out), written the way the feed writes them.

A drop counts when the day's TVL is still $10M or more (as the live feed asks) and is not a bad
data point: the day before must not itself be a spike (1.5x the day before it), and two days
later TVL must still be below 90% of where it was. Protocols drained to nothing are in the
crypto-hacks feed.

    research/.venv/bin/python research/public/defi_drops_history.py OUT.jsonl
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime

import httpx

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
PROTOCOLS = "https://api.llama.fi/protocols"
PROTOCOL = "https://api.llama.fi/protocol/{slug}"
ADVICE = "Data, not investment advice."


def _short(value: float) -> str:
    for size, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if value >= size:
            return f"{value / size:.3g}{unit}"
    return f"{value:.0f}"


def _get(http: httpx.Client, url: str):
    for attempt in range(5):
        response = http.get(url)
        if response.status_code < 500 and response.status_code != 429:
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        time.sleep(10 * (attempt + 1))
    response.raise_for_status()
    return None


def drops(protocol: dict, series: list[dict]) -> list[dict]:
    tvl: dict[str, float] = {}
    for point in series:
        day = datetime.fromtimestamp(int(point["date"]), UTC).strftime("%Y-%m-%d")
        tvl[day] = float(point.get("totalLiquidityUSD") or 0)
    days = sorted(tvl)
    found = []
    for index in range(2, len(days) - 2):
        day, before, earlier = days[index], tvl[days[index - 1]], tvl[days[index - 2]]
        now, later = tvl[day], tvl[days[index + 2]]
        if not before or now < 10e6 or earlier <= 0:
            continue
        change = (now / before - 1) * 100
        if change > -25 or before > 1.5 * earlier or later >= 0.9 * before:
            continue
        name, category = protocol["name"], protocol.get("category") or "DeFi"
        found.append(
            {
                "feed": "defi-drops",
                "title": f"{name} TVL down {abs(change):.0f}% in a day, to ${_short(now)}",
                "summary": f"{name} ({category}) held ${_short(now)} on {day} after a "
                f"{abs(change):.1f}% drop in 24 hours (DefiLlama). A sudden drop can mean a hack, "
                f"an exploit or users leaving. {ADVICE}",
                "link": f"https://defillama.com/protocol/{protocol['slug']}",
                "date": f"{day}T00:00:00Z",
            }
        )
    return found


def main(out: str) -> None:
    with (
        httpx.Client(headers=AGENT, timeout=180) as http,
        open(out, "w", encoding="utf-8") as lines,
    ):
        protocols = [
            p
            for p in _get(http, PROTOCOLS)
            if (p.get("tvl") or 0) >= 10e6 and p.get("category") != "CEX" and p.get("slug")
        ]
        written = 0
        for number, protocol in enumerate(protocols, 1):
            document = _get(http, PROTOCOL.format(slug=protocol["slug"]))
            found = drops(protocol, (document or {}).get("tvl") or [])
            for entry in found:
                lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
            written += len(found)
            print(number, len(protocols), protocol["slug"], len(found), flush=True)
            time.sleep(1)
    print(written, "drops")


if __name__ == "__main__":
    main(sys.argv[1])
