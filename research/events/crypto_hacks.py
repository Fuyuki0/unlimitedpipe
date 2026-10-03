"""What happened to a protocol's token after it was hacked: its price change 1, 7 and 30 days
after the hack, raw and against Bitcoin over the same days, from DefiLlama's open data (hacks,
protocols and coin prices). As a control, the same token's change against Bitcoin over the same
spans 90 days before the hack (small tokens often lag Bitcoin anyway). Writes one row per hack
(CSV) and prints the summary.

    research/.venv/bin/python research/events/crypto_hacks.py OUT.csv

Read the caveats in docs/posts/what-happened-after-crypto-hacks.md before quoting a number.
"""

from __future__ import annotations

import csv
import statistics
import sys
import time
from datetime import UTC, datetime

import httpx

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
DAY = 86400
HORIZONS = (1, 7, 30)
CONTROL = 90 * DAY  # the control window starts this long before the hack


def price_at(points: list[dict], when: float, before: bool) -> float | None:
    """The last price at or before ``when`` (``before``), else the first at or after it, within
    two days."""
    if before:
        found = [p for p in points if when - 2 * DAY <= p["timestamp"] <= when]
        return found[-1]["price"] if found else None
    found = [p for p in points if when <= p["timestamp"] <= when + 2 * DAY]
    return found[0]["price"] if found else None


def main(out: str) -> None:
    http = httpx.Client(headers=AGENT, timeout=60)
    hacks = http.get("https://api.llama.fi/hacks").json()
    protocols = http.get("https://api.llama.fi/protocols").json()
    tokens = {str(p.get("id")): (p.get("gecko_id"), p.get("name")) for p in protocols}
    rows = []
    for hack in sorted(hacks, key=lambda h: h["date"]):
        gecko, _ = tokens.get(str(hack.get("defillamaId")), (None, None))
        if not gecko or not hack.get("amount"):
            continue
        when = float(hack["date"])
        coins = f"coingecko:{gecko},coingecko:bitcoin"
        try:
            chart = http.get(
                f"https://coins.llama.fi/chart/{coins}",
                params={"start": int(when - CONTROL - 3 * DAY), "span": 130, "period": "1d"},
            ).json()["coins"]
        except (httpx.HTTPError, ValueError, KeyError):
            continue
        time.sleep(0.5)
        token = (chart.get(f"coingecko:{gecko}") or {}).get("prices") or []
        bitcoin = (chart.get("coingecko:bitcoin") or {}).get("prices") or []
        base, btc_base = price_at(token, when - DAY, True), price_at(bitcoin, when - DAY, True)
        if not (base and btc_base):
            continue
        row = {
            "date": datetime.fromtimestamp(when, UTC).strftime("%Y-%m-%d"),
            "name": hack["name"],
            "token": gecko,
            "amount": hack["amount"],
            "technique": hack.get("technique") or "",
        }
        for days in HORIZONS:
            after = price_at(token, when + days * DAY, False)
            btc_after = price_at(bitcoin, when + days * DAY, False)
            if after and btc_after:
                raw = after / base - 1
                row[f"change_{days}d"] = round(raw, 4)
                row[f"vs_btc_{days}d"] = round(raw - (btc_after / btc_base - 1), 4)
            # the control: the same span, 90 days earlier
            start = when - CONTROL - DAY
            c_base, c_btc = price_at(token, start, True), price_at(bitcoin, start, True)
            c_after = price_at(token, start + (days + 1) * DAY, False)
            c_btc_after = price_at(bitcoin, start + (days + 1) * DAY, False)
            if c_base and c_btc and c_after and c_btc_after:
                row[f"control_{days}d"] = round(
                    (c_after / c_base - 1) - (c_btc_after / c_btc - 1), 4
                )
        rows.append(row)
    fields = ["date", "name", "token", "amount", "technique"] + [
        f"{kind}_{d}d" for d in HORIZONS for kind in ("change", "vs_btc", "control")
    ]
    with open(out, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    summarize(rows)


def summarize(rows: list[dict]) -> None:
    def line(label: str, group: list[dict]) -> None:
        parts = [f"{label}: {len(group)} hacks"]
        for days in HORIZONS:
            values = [r[f"vs_btc_{days}d"] for r in group if f"vs_btc_{days}d" in r]
            raw = [r[f"change_{days}d"] for r in group if f"change_{days}d" in r]
            control = [r[f"control_{days}d"] for r in group if f"control_{days}d" in r]
            if values:
                down = sum(v < 0 for v in values) / len(values)
                parts.append(
                    f"{days}d median {statistics.median(raw):+.1%} raw, "
                    f"{statistics.median(values):+.1%} vs BTC, {down:.0%} below BTC "
                    f"(n={len(values)})"
                    + (
                        f"; control {statistics.median(control):+.1%} vs BTC, "
                        f"{sum(v < 0 for v in control) / len(control):.0%} below (n={len(control)})"
                        if control
                        else ""
                    )
                )
        print(" | ".join(parts))

    line("all", rows)
    line("$100M+", [r for r in rows if r["amount"] >= 1e8])
    line("$10M-100M", [r for r in rows if 1e7 <= r["amount"] < 1e8])
    line("under $10M", [r for r in rows if r["amount"] < 1e7])


if __name__ == "__main__":
    main(sys.argv[1])
