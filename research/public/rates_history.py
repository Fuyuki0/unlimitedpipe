"""Central bank rate decisions, as items of the rate-decisions feed: the Federal Reserve (copied
from the site's fed-funds-target feed), the ECB (main refinancing and deposit facility rates,
ECB Data Portal), the Bank of England (Bank Rate), the Bank of Canada (overnight rate target,
Valet API) and the Reserve Bank of Australia (cash rate target, holds included). For the first
four only changes are listed: their published series show when a rate moved, not every meeting.

    research/.venv/bin/python research/public/rates_history.py SITE OUT.jsonl
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import httpx

from unlimitedpipe.archive import _month_files, _text, lines_of

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
ECB = "https://data-api.ecb.europa.eu/service/data/FM/B.U2.EUR.4F.KR.{series}.LEV?format=csvdata"
ECB_RATES = {"MRR_FR": "main refinancing rate", "DFR": "deposit facility rate"}
ECB_PAGE = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/key_ecb_interest_rates/html/index.en.html"
BOE = "https://www.bankofengland.co.uk/boeapps/database/Bank-Rate.asp"
BOC = "https://www.bankofcanada.ca/valet/observations/V39079/json?start_date=1990-01-01"
BOC_PAGE = "https://www.bankofcanada.ca/core-functions/monetary-policy/key-interest-rate/"
RBA = "https://www.rba.gov.au/statistics/cash-rate/"


def _cells(page: str) -> list[list[str]]:
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S)
    return [
        [
            " ".join(re.sub(r"<[^>]+>|&nbsp;", " ", c).split())
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
        ]
        for row in rows
    ]


def change(
    bank: str, rate: str, day: str, before: float | None, after: float, link: str, source: str
) -> dict:
    if before is None or abs(after - before) < 1e-9:
        verb, moved = "held", ""
        title = f"{bank} rate decision: {rate} held at {after:.2f}%"
    else:
        verb = "raised" if after > before else "cut"
        moved = f" by {abs(after - before):.2f} point"
        title = f"{bank} rate decision: {rate} {verb}{moved} to {after:.2f}%"
    summary = f"The {bank} {verb} its {rate}{moved} to {after:.2f}%"
    if before is not None and verb != "held":
        summary += f" (from {before:.2f}%)"
    summary += f", effective {day}. From {source}."
    return {
        "feed": "rate-decisions",
        "title": title + f" (effective {day})",
        "summary": summary,
        "link": link,
        "date": f"{day}T00:00:00Z",
    }


def changes(bank, rate, points, link, source):
    found, before = [], None
    for day, value in points:
        if before is not None and abs(value - before) > 1e-9:
            found.append(change(bank, rate, day, before, value, link, source))
        before = value
    return found


def main(site: str, out: str) -> None:
    found = []
    for path in _month_files(Path(site) / "archive"):
        for line in lines_of(_text(path)):
            if '"fed-funds-target"' in line:
                item = json.loads(line)
                found.append(
                    {k: item[k] for k in ("title", "summary", "link", "date")}
                    | {"feed": "rate-decisions"}
                )
    with httpx.Client(headers=AGENT, timeout=120, follow_redirects=True) as http:
        for series, rate in ECB_RATES.items():
            rows = csv.DictReader(io.StringIO(http.get(ECB.format(series=series)).text))
            points = [(r["TIME_PERIOD"], float(r["OBS_VALUE"])) for r in rows if r["OBS_VALUE"]]
            found += changes("ECB", rate, points, ECB_PAGE, "the ECB Data Portal")
        boe = [
            (datetime.strptime(c[0], "%d %b %y").date().isoformat(), float(c[1]))
            for c in _cells(http.get(BOE).text)
            if len(c) == 2 and re.match(r"\d\d \w{3} \d\d$", c[0])
        ]
        found += changes("Bank of England", "Bank Rate", sorted(boe), BOE, "the Bank of England")
        document = http.get(BOC).json()
        points = [
            (o["d"], float(o["V39079"]["v"])) for o in document["observations"] if o.get("V39079")
        ]
        found += changes(
            "Bank of Canada",
            "overnight rate target",
            points,
            BOC_PAGE,
            "the Bank of Canada (Valet)",
        )
        for cells in _cells(http.get(RBA).text):
            if len(cells) >= 3 and re.match(r"\d{1,2} \w{3} \d{4}$", cells[0]):
                try:
                    moved, level = float(cells[1].split()[0]), float(cells[2].split()[0])
                except ValueError:
                    continue  # ranges such as "17.00 to 17.50" in 1990
                day = datetime.strptime(cells[0], "%d %b %Y").date().isoformat()
                found.append(
                    change(
                        "Reserve Bank of Australia",
                        "cash rate target",
                        day,
                        level - moved,
                        level,
                        RBA,
                        "the Reserve Bank of Australia",
                    )
                )
    with open(out, "w", encoding="utf-8") as lines:
        for entry in found:
            lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(len(found), "decisions")


if __name__ == "__main__":
    main(*sys.argv[1:3])
