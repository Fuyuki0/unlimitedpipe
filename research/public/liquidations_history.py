"""Aave liquidations of $100K or more, as items of the defi-liquidations feed, written the way
the feed writes them: Aave V2 (since December 2020) and V3 (since January 2023) on Ethereum, read
through Etherscan's free API (ETHERSCAN_API_KEY), and Aave V3 on Base (since August 2023), read
from Base's own public endpoint 2,000 blocks at a time. Debt is priced at the day's price from
DefiLlama.

    ETHERSCAN_API_KEY=... research/.venv/bin/python research/public/liquidations_history.py \\
        OUT.jsonl
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime

import httpx

from unlimitedpipe.expr import short_number
from unlimitedpipe.sources.evm import address_of, short_address, text_of, word

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
TOPIC = "0xe413a321e8681d831f4dbccbca790d2952b56f977908e45be37335533e005286"  # LiquidationCall
ETHERSCAN = "https://api.etherscan.io/v2/api"
POOLS = [  # (chain, version, pool, first block, how to read)
    ("ethereum", "V2", "0x7d2768de32b0b80b7a3454c06bdac94a69ddc7a9", 11362579, "etherscan"),
    ("ethereum", "V3", "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2", 16291127, "etherscan"),
    ("base", "V3", "0xa238dd80c259a72e81d7e4664a9801593f98d1c5", 2357134, "rpc"),
]
RPC = {"ethereum": "https://ethereum-rpc.publicnode.com", "base": "https://mainnet.base.org"}
EXPLORER = {"ethereum": "https://etherscan.io", "base": "https://basescan.org"}
NAMES = {"ethereum": "Ethereum", "base": "Base"}
PRICES = "https://coins.llama.fi/chart/{chain}:{token}?start={start}&span=500&period=1d"
MIN_VALUE = 100_000


def _post(http: httpx.Client, url: str, method: str, params: list) -> object:
    for attempt in range(6):
        try:
            body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
            answer = http.post(url, json=body).json()
            if "result" in answer:
                return answer["result"]
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(5 * (attempt + 1))
    raise SystemExit(f"{method} failed at {url}")


def etherscan_logs(http: httpx.Client, pool: str, first: int, key: str):
    start = first
    while True:
        for attempt in range(6):
            answer = http.get(
                ETHERSCAN,
                params={
                    "chainid": 1,
                    "module": "logs",
                    "action": "getLogs",
                    "address": pool,
                    "topic0": TOPIC,
                    "fromBlock": start,
                    "toBlock": "latest",
                    "page": 1,
                    "offset": 1000,
                    "apikey": key,
                },
            ).json()
            if isinstance(answer.get("result"), list):
                break
            time.sleep(5 * (attempt + 1))  # a rate limit message
        logs = answer["result"]
        time.sleep(0.3)
        yield from logs
        if len(logs) < 1000:
            return
        last = int(logs[-1]["blockNumber"], 16)
        start = last if last > start else last + 1  # a full page may end inside a block
        if last == start and all(int(x["blockNumber"], 16) == last for x in logs):
            start = last + 1


def rpc_logs(http: httpx.Client, pool: str, first: int):
    head = int(_post(http, RPC["base"], "eth_blockNumber", []), 16)
    for start in range(first, head, 2000):
        end = min(start + 1999, head)
        yield from _post(
            http,
            RPC["base"],
            "eth_getLogs",
            [{"address": pool, "topics": [TOPIC], "fromBlock": hex(start), "toBlock": hex(end)}],
        )
        time.sleep(0.25)
        if (start - first) % 1_000_000 == 0:
            print("base block", start, flush=True)


def token_info(http: httpx.Client, chain: str, token: str, cache: dict) -> tuple[str, int]:
    if (chain, token) not in cache:
        call = [{"to": token, "data": "0x95d89b41"}, "latest"]
        symbol = text_of(str(_post(http, RPC[chain], "eth_call", call))) or token[:8]
        call = [{"to": token, "data": "0x313ce567"}, "latest"]
        decimals = word(str(_post(http, RPC[chain], "eth_call", call)), 0)
        cache[(chain, token)] = (symbol, decimals)
    return cache[(chain, token)]


def daily_prices(http: httpx.Client, chain: str, token: str, cache: dict) -> dict[str, float]:
    if (chain, token) not in cache:
        prices, start = {}, int(datetime(2020, 11, 1, tzinfo=UTC).timestamp())
        while start < time.time():
            answer = http.get(PRICES.format(chain=chain, token=token, start=start)).json()
            points = (answer.get("coins") or {}).get(f"{chain}:{token}", {}).get("prices") or []
            for point in points:
                day = datetime.fromtimestamp(point["timestamp"], UTC).strftime("%Y-%m-%d")
                prices[day] = float(point["price"])
            start = int(points[-1]["timestamp"]) + 86400 if points else start + 500 * 86400
            time.sleep(0.5)
        cache[(chain, token)] = prices
    return cache[(chain, token)]


def main(out: str) -> None:
    key = os.environ["ETHERSCAN_API_KEY"]
    tokens: dict = {}
    prices: dict = {}
    written = 0
    with (
        httpx.Client(headers=AGENT, timeout=120) as http,
        open(out, "w", encoding="utf-8") as lines,
    ):
        for chain, version, pool, first, how in POOLS:
            logs = (
                etherscan_logs(http, pool, first, key)
                if how == "etherscan"
                else rpc_logs(http, pool, first)
            )
            seen, count = set(), 0
            for log in logs:
                mark = (log["transactionHash"], log["logIndex"])
                if mark in seen or len(log["topics"]) < 4:
                    continue
                seen.add(mark)
                collateral, debt = address_of(log["topics"][1]), address_of(log["topics"][2])
                user = address_of(log["topics"][3])
                debt_symbol, decimals = token_info(http, chain, debt, tokens)
                collateral_symbol, _ = token_info(http, chain, collateral, tokens)
                stamp = int(log.get("timeStamp") or log.get("blockTimestamp"), 16)
                when = datetime.fromtimestamp(stamp, UTC)
                price = daily_prices(http, chain, debt, prices).get(f"{when:%Y-%m-%d}")
                repaid = word(log["data"], 0) / 10**decimals
                value = repaid * price if price else None
                if value is None or value < MIN_VALUE:
                    continue
                name = NAMES[chain] if version == "V3" else f"{version} {NAMES[chain]}"
                entry = {
                    "feed": "defi-liquidations",
                    "title": f"Aave {name} liquidation: ${short_number(value)} of {debt_symbol} "
                    f"debt repaid, {collateral_symbol} collateral seized",
                    "summary": f"A borrower ({short_address(user)}) on Aave {version} "
                    f"({NAMES[chain]}) was liquidated: {repaid:,.2f} {debt_symbol} "
                    f"(${short_number(value)}) of debt repaid by a liquidator, who took "
                    f"{collateral_symbol} collateral. Data, not investment advice.",
                    "link": f"{EXPLORER[chain]}/tx/{log['transactionHash']}",
                    "date": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
                lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
                count += 1
            lines.flush()
            written += count
            print(chain, version, len(seen), "liquidations,", count, "of $100K or more", flush=True)
    print(written, "liquidations")


if __name__ == "__main__":
    main(sys.argv[1])
