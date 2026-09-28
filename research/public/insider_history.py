"""Past insider trades for the insider-trades feed's archive, from the SEC's quarterly Form 345
data sets (https://www.sec.gov/dera/data/form-345), written the way the feed writes them:
open-market purchases and sales worth $100,000 or more, one item per filing and code, titled by
`unlimitedpipe.sources.sec.headline`.

    research/.venv/bin/python research/public/insider_history.py OUT.jsonl 2024q4 2025q1 ...

The zip files are downloaded into the scratch folder next to OUT and read from there.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import httpx

from unlimitedpipe.sources.sec import ACTIONS, headline, person_name

BULK = "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{}_form345.zip"
CODES = ("P", "S")  # the feed's default: open-market purchases and sales
MIN_VALUE = 100_000
NO_TICKER = {"", "NA", "N/A", "NONE"}


def rows(archive: zipfile.ZipFile, name: str):
    with archive.open(name) as raw:
        yield from csv.DictReader(
            io.TextIOWrapper(raw, encoding="utf-8", errors="replace"), delimiter="\t"
        )


def day(text: str) -> str | None:
    try:
        return datetime.strptime(text, "%d-%b-%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def number(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def role(owner: dict[str, str]) -> str | None:
    """As the feed reads a Form 4: the officer's title, then director, then 10% owner."""
    relation = owner.get("RPTOWNER_RELATIONSHIP") or ""
    roles = []
    if "Officer" in relation:
        roles.append(owner.get("RPTOWNER_TITLE") or "officer")
    if "Director" in relation:
        roles.append("director")
    if "TenPercentOwner" in relation:
        roles.append("10% owner")
    return ", ".join(roles) or None


def items_of(archive: zipfile.ZipFile) -> list[dict]:
    filings = {
        r["ACCESSION_NUMBER"]: r
        for r in rows(archive, "SUBMISSION.tsv")
        if r["DOCUMENT_TYPE"] in ("4", "4/A")
    }
    owners: dict[str, dict[str, str]] = {}
    for r in rows(archive, "REPORTINGOWNER.tsv"):
        owners.setdefault(r["ACCESSION_NUMBER"], r)  # the first owner, as the feed reads it
    trades: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for r in rows(archive, "NONDERIV_TRANS.tsv"):
        if r["ACCESSION_NUMBER"] in filings and r["TRANS_CODE"] in CODES:
            trades[(r["ACCESSION_NUMBER"], r["TRANS_CODE"])].append(r)
    items = []
    for (accession, code), found in trades.items():
        filing, owner = filings[accession], owners.get(accession)
        shares = sum(number(t["TRANS_SHARES"]) or 0 for t in found)
        priced = [t for t in found if number(t["TRANS_PRICEPERSHARE"])]
        value = sum(
            (number(t["TRANS_SHARES"]) or 0) * (number(t["TRANS_PRICEPERSHARE"]) or 0)
            for t in priced
        )
        if not (owner and shares and value >= MIN_VALUE):
            continue
        priced_shares = sum(number(t["TRANS_SHARES"]) or 0 for t in priced)
        ticker = (filing["ISSUERTRADINGSYMBOL"] or "").strip().upper()
        trade = {
            "issuer": re.sub(r"(\s*/[A-Z]{2,5}/)+\s*$", "", filing["ISSUERNAME"]).strip(),
            "ticker": None if ticker in NO_TICKER else ticker,
            "owner": person_name(owner["RPTOWNERNAME"]),
            "role": role(owner),
            "action": ACTIONS[code],
            "shares": int(shares) if float(shares).is_integer() else shares,
            "price": round(value / priced_shares, 4) if priced_shares else None,
            "value": round(value, 2),
        }
        traded = min((d for t in found if (d := day(t["TRANS_DATE"]))), default=None)
        filed = day(filing["FILING_DATE"])
        if not filed:
            continue
        planned = (filing.get("AFF10B5ONE") or "").strip().lower() in ("1", "true")
        cik = str(int(filing["ISSUERCIK"]))
        items.append(
            {
                "feed": "insider-trades",
                "title": headline(trade),
                "summary": f"Traded {traded}."
                + (" A pre-planned trade (Rule 10b5-1)." if planned else ""),
                "link": f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                f"{accession.replace('-', '')}/{accession}-index.htm",
                "date": f"{filed}T00:00:00Z",
            }
        )
    return items


def main(out: str, quarters: list[str]) -> None:
    folder = Path(out).parent
    agent = f"UnlimitedPipe {os.environ['SEC_CONTACT']}"
    with Path(out).open("a", encoding="utf-8") as lines:
        for quarter in quarters:
            path = folder / f"{quarter}_form345.zip"
            if not path.exists():
                response = httpx.get(
                    BULK.format(quarter), headers={"User-Agent": agent}, timeout=300
                )
                response.raise_for_status()
                path.write_bytes(response.content)
            with zipfile.ZipFile(path) as archive:
                found = items_of(archive)
            for item in found:
                lines.write(json.dumps(item, ensure_ascii=False) + "\n")
            print(quarter, len(found), "trades")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
