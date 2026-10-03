"""Form D raises ($25M+ sold) and 13F holdings reports ($1B+) from the SEC's quarterly data
sets, as items of the sec-private-raises and sec-fund-holdings feeds, with the titles the live
feeds write (unlimitedpipe.sources.sec). One zip at a time, deleted once read. Works of the US
government; the SEC asks for a contact email in $SEC_CONTACT.

    SEC_CONTACT=you@example.com \\
        research/.venv/bin/python research/public/sec_datasets_history.py OUT.jsonl
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

import httpx

from unlimitedpipe.sources.sec import fund_holdings, private_raise

SITE = "https://www.sec.gov"
PAGES = {
    "d": "/data-research/sec-markets-data/form-d-data-sets",
    "13f": "/data-research/sec-markets-data/form-13f-data-sets",
}
MIN_RAISE, MIN_HOLDINGS = 25e6, 1e9
DOLLARS_FROM = "2023-01-03"  # 13F values were in thousands before


def day(text: str) -> str:
    """31-MAR-2026, or 2008-09-29 16:26:03 in the oldest data sets."""
    text = text.strip()
    if re.match(r"\d{4}-\d\d-\d\d", text):
        return text[:10]
    return datetime.strptime(text, "%d-%b-%Y").strftime("%Y-%m-%d")


def table(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    member = next(n for n in archive.namelist() if n.upper().endswith(f"{name}.TSV"))
    with archive.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
        return list(csv.DictReader(text, delimiter="\t", quoting=csv.QUOTE_NONE))


def link(cik: str, accession: str) -> str:
    return (
        f"{SITE}/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{accession}-index.htm"
    )


def raises(archive: zipfile.ZipFile) -> list[dict]:
    filed = {r["ACCESSIONNUMBER"]: r for r in table(archive, "FORMDSUBMISSION")}
    issuers = {
        r["ACCESSIONNUMBER"]: r
        for r in table(archive, "ISSUERS")
        if r.get("IS_PRIMARYISSUER_FLAG", "").upper() in ("YES", "Y", "TRUE")
    }
    found = []
    for offer in table(archive, "OFFERING"):
        accession = offer["ACCESSIONNUMBER"]
        submission, issuer = filed.get(accession), issuers.get(accession)
        if not (submission and issuer) or submission.get("SUBMISSIONTYPE") != "D":
            continue
        try:
            if float(offer.get("TOTALAMOUNTSOLD") or 0) < MIN_RAISE:
                continue
        except ValueError:
            continue
        xml = (
            f"<entityName>{escape(issuer['ENTITYNAME'])}</entityName>"
            f"<stateOrCountryDescription>{escape(issuer.get('STATEORCOUNTRYDESCRIPTION') or '')}"
            "</stateOrCountryDescription>"
            f"<industryGroupType>{escape(offer.get('INDUSTRYGROUPTYPE') or 'Other')}"
            "</industryGroupType>"
            + (
                f"<investmentFundType>{escape(offer['INVESTMENTFUNDTYPE'])}</investmentFundType>"
                if offer.get("INVESTMENTFUNDTYPE")
                else ""
            )
            + f"<isAmendment>{offer.get('ISAMENDMENT') or 'false'}</isAmendment>"
            f"<totalOfferingAmount>{offer.get('TOTALOFFERINGAMOUNT') or ''}</totalOfferingAmount>"
            f"<totalAmountSold>{offer.get('TOTALAMOUNTSOLD') or ''}</totalAmountSold>"
        )
        shaped = private_raise(xml)
        if shaped:
            when = day(submission["FILING_DATE"])
            found.append(
                {
                    "feed": "sec-private-raises",
                    "title": shaped["title"],
                    "summary": shaped["summary"],
                    "link": link(issuer["CIK"], accession),
                    "date": f"{when}T00:00:00Z",
                }
            )
    return found


def holdings(archive: zipfile.ZipFile) -> list[dict]:
    covers = {r["ACCESSION_NUMBER"]: r for r in table(archive, "COVERPAGE")}
    sums = {r["ACCESSION_NUMBER"]: r for r in table(archive, "SUMMARYPAGE")}
    found = []
    for submission in table(archive, "SUBMISSION"):
        accession = submission["ACCESSION_NUMBER"]
        cover, summary = covers.get(accession), sums.get(accession)
        if not (cover and summary) or submission.get("SUBMISSIONTYPE") != "13F-HR":
            continue
        when = day(submission["FILING_DATE"])
        try:
            value = float(summary.get("TABLEVALUETOTAL") or 0)
        except ValueError:
            continue
        if when < DOLLARS_FROM:
            value *= 1000
        if value < MIN_HOLDINGS:
            continue
        quarter = datetime.strptime(day(cover["REPORTCALENDARORQUARTER"]), "%Y-%m-%d")
        xml = (
            f"<reportType>{escape(cover.get('REPORTTYPE') or '')}</reportType>"
            f"<filingManager><name>{escape(cover['FILINGMANAGER_NAME'])}</name></filingManager>"
            f"<tableValueTotal>{value:.0f}</tableValueTotal>"
            f"<tableEntryTotal>{summary.get('TABLEENTRYTOTAL') or ''}</tableEntryTotal>"
            f"<reportCalendarOrQuarter>{quarter:%m-%d-%Y}</reportCalendarOrQuarter>"
        )
        shaped = fund_holdings(xml)
        if shaped:
            found.append(
                {
                    "feed": "sec-fund-holdings",
                    "title": shaped["title"],
                    "summary": shaped["summary"],
                    "link": link(submission["CIK"], accession),
                    "date": f"{when}T00:00:00Z",
                }
            )
    return found


AMOUNT = re.compile(r"\$([\d.]+)([KMBT])")
SCALE = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


def amount(title: str) -> float:
    found = AMOUNT.search(title)
    return float(found[1]) * SCALE[found[2]] if found else 0.0


def fix_units(items: list[dict]) -> list[dict]:
    """13F totals before 2023 were due in thousands, but some managers filed dollars, which the
    thousands rule turns 1,000 times too big ("$10T"). Such a total is read as dollars when the
    same manager (by CIK) reported far less once dollars became the rule, or, for one that never
    filed since, when it is $200B or more; read so, under $1B is left out."""
    from unlimitedpipe.expr import short_number

    def cik(item: dict) -> str:
        return item["link"].split("/data/", 1)[1].split("/", 1)[0]

    later: dict[str, float] = {}
    for item in items:
        if item["feed"] == "sec-fund-holdings" and item["date"] >= DOLLARS_FROM:
            later[cik(item)] = max(later.get(cik(item), 0.0), amount(item["title"]))
    fixed = []
    for item in items:
        if item["feed"] != "sec-fund-holdings" or item["date"] >= DOLLARS_FROM:
            fixed.append(item)
            continue
        value = amount(item["title"])
        top = later.get(cik(item))
        if (top and value > 20 * top) or (not top and value >= 2e11):
            value /= 1000
            if value < MIN_HOLDINGS:
                continue
            item = {**item, "title": AMOUNT.sub(f"${short_number(value)}", item["title"], 1)}
        fixed.append(item)
    # Then any report 20 times its manager's usual size, in either era ("$3T" in 2024, "$3B"
    # in 2025, from the same trust company), is read as 1,000 times too big.
    from statistics import median

    sizes: dict[str, list[float]] = {}
    for item in fixed:
        if item["feed"] == "sec-fund-holdings":
            sizes.setdefault(cik(item), []).append(amount(item["title"]))
    usual = {key: median(values) for key, values in sizes.items()}
    final = []
    for item in fixed:
        if item["feed"] == "sec-fund-holdings":
            value = amount(item["title"])
            if value > 20 * usual[cik(item)]:
                value /= 1000
                if value < MIN_HOLDINGS:
                    continue
                item = {**item, "title": AMOUNT.sub(f"${short_number(value)}", item["title"], 1)}
        final.append(item)
    return final


def main(out: str) -> None:
    agent = {"User-Agent": f"UnlimitedPipe {os.environ['SEC_CONTACT']}"}
    seen: set[str] = set()
    with (
        open(out, "w", encoding="utf-8") as lines,
        httpx.Client(headers=agent, timeout=600, follow_redirects=True) as http,
    ):
        for kind, page in PAGES.items():
            listing = http.get(SITE + page).text
            zips = sorted(set(re.findall(r'href="([^"]+\.zip)"', listing)))
            shape = raises if kind == "d" else holdings
            total = 0
            for path in zips:
                with tempfile.TemporaryFile() as data:
                    with http.stream("GET", SITE + path) as response:
                        response.raise_for_status()
                        for chunk in response.iter_bytes():
                            data.write(chunk)
                    with zipfile.ZipFile(data) as archive:
                        items = shape(archive)
                for item in items:
                    if item["link"] in seen:
                        continue  # in two data sets
                    seen.add(item["link"])
                    lines.write(json.dumps(item, ensure_ascii=False) + "\n")
                    total += 1
                print(kind, path.rsplit("/", 1)[-1], len(items), flush=True)
                time.sleep(1)
            print(kind, total, "items", flush=True)
    with open(out, encoding="utf-8") as lines:
        found = [json.loads(line) for line in lines]
    with open(out, "w", encoding="utf-8") as lines:
        for item in fix_units(found):
            lines.write(json.dumps(item, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
