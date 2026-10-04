"""USDT and USDC transfers of $25M or more on Ethereum since 2017 (mints and burns included,
flash-loan legs that send money out and back in one transaction left out), as items of the
whale-transfers feed, written as the feed writes them, from Google BigQuery's public Ethereum
data (bigquery-public-data.crypto_ethereum.token_transfers). Needs a service account key in
$GOOGLE_APPLICATION_CREDENTIALS and a project (a free BigQuery sandbox will do: the query reads
about 1,000 GB for 2017 to 2026, so split the years over two months; each run is costed
first and refused above MAX_GB).

    GOOGLE_APPLICATION_CREDENTIALS=key.json \\
        research/.venv/bin/python research/public/whale_history.py PROJECT OUT.jsonl 2017 2024

The years are read one query each (the table is partitioned by time); items are added to OUT.
"""

from __future__ import annotations

import json
import sys

from google.cloud import bigquery

from unlimitedpipe.expr import short_number
from unlimitedpipe.sources.evm import short_address

TOKENS = {
    "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
}
ZERO = "0x0000000000000000000000000000000000000000"
MIN_UNITS = 25_000_000 * 10**6  # both have 6 decimals
MAX_GB = 600  # of the sandbox's free 1,000 GB a month
QUERY = """
SELECT token_address, from_address, to_address, value, transaction_hash, block_number,
       block_timestamp
FROM `bigquery-public-data.crypto_ethereum.token_transfers`
WHERE token_address IN ({tokens})
  AND LENGTH(value) >= 14  -- $10M or more: the rest is checked below
  AND block_timestamp >= '{first}-01-01' AND block_timestamp < '{end}-01-01'
"""


def main(project: str, out: str, first: str, last: str) -> None:
    client = bigquery.Client(project=project)
    tokens = ", ".join(f"'{t}'" for t in TOKENS)
    queries = [
        QUERY.format(tokens=tokens, first=year, end=year + 1)
        for year in range(int(first), int(last) + 1)
    ]
    dry = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    gigabytes = sum(client.query(q, job_config=dry).total_bytes_processed for q in queries) / 1e9
    print(f"queries read {gigabytes:.0f} GB", flush=True)
    if gigabytes > MAX_GB:
        raise SystemExit(f"refused: more than {MAX_GB} GB")
    written = 0
    with open(out, "a", encoding="utf-8") as lines:
        for year, query in zip(range(int(first), int(last) + 1), queries, strict=True):
            rows = [r for r in client.query(query).result() if int(r.value) >= MIN_UNITS]
            for entry in transfers(rows):
                lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
                written += 1
            lines.flush()
            print(year, len(rows), "rows", flush=True)
    print(written, "transfers")


def transfers(rows: list) -> list[dict]:
    legs = {
        (r.transaction_hash, r.token_address, r.value, r.from_address, r.to_address) for r in rows
    }
    found = []
    for r in rows:
        if (r.transaction_hash, r.token_address, r.value, r.to_address, r.from_address) in legs:
            continue  # one leg of a flash loan
        symbol, amount = TOKENS[r.token_address], int(r.value) / 10**6
        if r.from_address == ZERO:
            what = f"${short_number(amount)} {symbol} minted on Ethereum"
        elif r.to_address == ZERO:
            what = f"${short_number(amount)} {symbol} burned on Ethereum"
        else:
            what = (
                f"${short_number(amount)} {symbol} moved on Ethereum: "
                f"{short_address(r.from_address)} to {short_address(r.to_address)}"
            )
        found.append(
            {
                "feed": "whale-transfers",
                "title": what,
                "summary": f"{what} (from {r.from_address} to {r.to_address}), in block "
                f"{r.block_number}. Data, not investment advice.",
                "link": f"https://etherscan.io/tx/{r.transaction_hash}",
                "date": r.block_timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    return found


if __name__ == "__main__":
    main(*sys.argv[1:5])
