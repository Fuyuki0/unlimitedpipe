"""Earnings releases (8-K Item 2.02, Results of Operations and Financial Condition) of large
accelerated filers (US-listed companies with $700M or more in public float) since 2018, as
items of the earnings-releases feed, from the SEC's bulk submissions data (EDGAR).

    curl -A "Name you@example.com" -O \\
        https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip
    research/.venv/bin/python research/public/earnings_history.py submissions.zip OUT.jsonl 2018
"""

from __future__ import annotations

import json
import sys
import zipfile

from unlimitedpipe.sources.sec import ITEMS, readable_name

ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{accession}-index.htm"


def releases(cik: int, name: str, filings: dict, since: str) -> list[dict]:
    found = []
    for index, form in enumerate(filings.get("form") or []):
        if form != "8-K" or filings["filingDate"][index] < since:
            continue
        items = [i.strip() for i in (filings["items"][index] or "").split(",") if i.strip()]
        if "2.02" not in items:
            continue
        accession = filings["accessionNumber"][index]
        accepted = filings["acceptanceDateTime"][index] or filings["filingDate"][index]
        found.append(
            {
                "feed": "earnings-releases",
                "title": f"{name}: earnings release",
                "summary": "\n".join(f"Item {i}: {ITEMS[i]}" for i in items if i in ITEMS),
                "link": ARCHIVE.format(
                    cik=cik, folder=accession.replace("-", ""), accession=accession
                ),
                "date": accepted[:19] + "Z" if "T" in accepted else accepted + "T00:00:00Z",
            }
        )
    return found


def main(source: str, out: str, first_year: str) -> None:
    since = f"{first_year}-01-01"
    with zipfile.ZipFile(source) as archive, open(out, "w", encoding="utf-8") as lines:
        large: dict[str, tuple[int, str]] = {}
        extra: list[tuple[str, str]] = []
        written = 0
        for member in archive.namelist():
            if "-submissions-" in member:
                continue
            try:
                document = json.loads(archive.read(member))
            except ValueError:  # a few members are empty
                continue
            if "Large accelerated" not in (document.get("category") or ""):
                continue
            cik = int(document["cik"])
            name = readable_name(document["name"]) or document["name"]
            large[member[:13]] = (cik, name)
            for entry in releases(cik, name, document["filings"]["recent"], since):
                lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
                written += 1
            extra += [
                (f["name"], member[:13])
                for f in document["filings"].get("files") or []
                if f.get("filingTo", "") >= since
            ]
        for member, company in extra:
            cik, name = large[company]
            try:
                filings = json.loads(archive.read(member))
            except ValueError:
                continue
            for entry in releases(cik, name, filings, since):
                lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
                written += 1
    print(len(large), "companies,", written, "earnings releases")


if __name__ == "__main__":
    main(*sys.argv[1:4])
