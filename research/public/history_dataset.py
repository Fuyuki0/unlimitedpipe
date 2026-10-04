"""The feed catalog's public history as the Hugging Face dataset unlimitedpipe/feed-history:
one Parquet file per feed, with each item's feed, title, summary, link and date.

Only feeds whose items are works of the US government, or sentences UnlimitedPipe writes from
open data with attribution, are included; news headlines, WHO texts and licensed market
indices are left out.

    research/.venv/bin/python research/public/history_dataset.py SITE OUT [INSIDER.jsonl]
    hf upload unlimitedpipe/feed-history OUT --repo-type dataset
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

# feed -> (source, license)
FEEDS = {
    "insider-trades": ("SEC Form 4 filings (EDGAR, Form 345 data sets)", "public domain"),
    "sec-ipo-filings": ("SEC S-1 and F-1 registrations (EDGAR)", "public domain"),
    "activist-stakes": ("SEC Schedule 13D filings (EDGAR)", "public domain"),
    "sec-company-events": ("SEC 8-K filings (EDGAR)", "public domain"),
    "sec-cyber-incidents": ("SEC 8-K Item 1.05 filings (EDGAR)", "public domain"),
    "us-new-rules": ("Federal Register significant rules", "public domain"),
    "lobbying-big-spenders": ("Lobbying Disclosure Act reports (lda.gov)", "public domain"),
    "critical-vulnerabilities": ("NIST National Vulnerability Database", "public domain"),
    "exploited-vulnerabilities": ("CISA Known Exploited Vulnerabilities catalog", "public domain"),
    "earthquakes": ("US Geological Survey earthquake catalog", "public domain"),
    "drug-approvals": ("FDA novel drug approvals", "public domain"),
    "fda-recalls": ("FDA enforcement reports (openFDA), Class I recalls", "public domain (CC0)"),
    "court-rulings": (
        "Supreme Court (supremecourt.gov) and federal appeals court opinions (CourtListener)",
        "public domain",
    ),
    "us-indicators": ("BLS, Labor Department and Federal Reserve series via FRED", "public domain"),
    "data-breaches": ("Have I Been Pwned (haveibeenpwned.com)", "CC BY 4.0"),
    "crypto-hacks": ("DefiLlama hacks database", "open data, attribution to DefiLlama"),
    "fed-funds-target": (
        "Federal Reserve federal funds target (FRED: DFEDTAR, DFEDTARL, DFEDTARU)",
        "public domain",
    ),
    "sanctions-actions": ("US Treasury, OFAC recent actions", "public domain"),
    "natural-events": ("NASA Earth Observatory Natural Event Tracker (EONET)", "public domain"),
    "usd-rates": (
        "European Central Bank euro reference rates, as US dollar rates (via Frankfurter)",
        "reuse permitted with the ECB named as the source",
    ),
    "stablecoin-supply": ("DefiLlama stablecoin data", "open data, attribution to DefiLlama"),
    "us-disasters": ("FEMA disaster declarations (OpenFEMA)", "public domain"),
    "vehicle-recalls": (
        "NHTSA recalls (US Department of Transportation open data)",
        "public domain",
    ),
    "product-recalls": ("US Consumer Product Safety Commission recalls", "public domain"),
    "tsunami-alerts": (
        "NOAA tsunami messages and NCEI's historical tsunami database",
        "public domain",
    ),
    "volcanoes": ("NOAA NCEI significant volcanic eruptions database", "public domain"),
    "arxiv-llm": ("arXiv metadata (cs.CL, cs.AI; language models and agents)", "CC0 1.0"),
    "us-new-laws": ("Public laws (congress.gov API, Library of Congress)", "public domain"),
    "sec-press-releases": ("SEC press releases", "public domain"),
    "sec-enforcement": ("SEC litigation releases", "public domain"),
    "sec-private-raises": ("SEC Form D filings ($25M+ sold, as filed)", "public domain"),
    "sec-fund-holdings": ("SEC Form 13F holdings reports ($1B+, units checked)", "public domain"),
    "us-outside-spending": ("FEC independent expenditures ($250K+, as filed)", "public domain"),
    "drug-shortages": ("FDA drug shortage list (openFDA)", "public domain"),
    "us-contracts": ("USAspending.gov new contract awards ($100M+)", "public domain"),
    "us-grants": ("USAspending.gov new grant awards ($100M+)", "public domain"),
    "earnings-releases": (
        "SEC 8-K Item 2.02 filings of large accelerated filers (EDGAR)",
        "public domain",
    ),
    "world-events": ("Wikipedia, Current events portal (since 2002)", "CC BY-SA 4.0"),
    "typhoons": (
        "JMA RSMC Tokyo best track data (since 1951); JTWC warnings (US Navy)",
        "JMA terms of use (CC BY 4.0 compatible); public domain",
    ),
    "space-weather": (
        "GFZ Potsdam Kp index (Matzka et al. 2021) since 1932; NOAA SWPC alerts",
        "CC BY 4.0; public domain",
    ),
    "crypto-big-moves": ("DefiLlama coin prices", "open data, attribution to DefiLlama"),
    "stablecoin-depegs": ("DefiLlama stablecoin data", "open data, attribution to DefiLlama"),
    "defi-drops": ("DefiLlama protocol TVL", "open data, attribution to DefiLlama"),
    "uk-bills": ("UK Parliament bills service", "Open Parliament Licence v3.0"),
}
# Feeds whose other items come from sources that are not public: only these titles are kept.
ONLY = {"volcanoes": "Historical eruption:"}
LEFT_OUT = ("US 30-year mortgage rate",)  # Freddie Mac's survey, not a government series


def rows_of(site: Path, insider: Path | None) -> dict[str, list[dict]]:
    found: dict[str, dict[str, dict]] = collections.defaultdict(dict)
    from unlimitedpipe.archive import _month_files, _text

    sources = _month_files(site / "archive")  # compressed months too
    lines = (line for path in sources for line in _text(path).splitlines())
    if insider:
        lines = (*lines, *insider.open(encoding="utf-8"))
    for line in lines:
        item = json.loads(line)
        feed = item.get("feed")
        title = str(item.get("title") or "")
        if feed not in FEEDS or title.startswith(LEFT_OUT):
            continue
        if feed in ONLY and not title.startswith(ONLY[feed]):
            continue
        row = {k: item.get(k) for k in ("feed", "title", "summary", "link", "date")}
        found[feed].setdefault(f"{row['link']}\n{str(row['title']).casefold()}", row)
    return {
        feed: sorted(rows.values(), key=lambda r: r["date"] or "") for feed, rows in found.items()
    }


def card(counts: dict[str, int], spans: dict[str, tuple[str, str]]) -> str:
    table = "\n".join(
        f"| {feed} | {counts[feed]:,} | {spans[feed][0]} to {spans[feed][1]} | {FEEDS[feed][0]} |"
        f" {FEEDS[feed][1]} |"
        for feed in sorted(counts, key=lambda f: -counts[f])
    )
    return f"""---
license: other
license_name: public-domain-cc-by-and-cc-by-sa
language: [en]
pretty_name: UnlimitedPipe feed history (public records)
task_categories: [text-retrieval, question-answering]
configs:
  - config_name: default
    data_files: data/*.parquet
---

# feed-history

The history of UnlimitedPipe's public-record feeds (https://feeds.daemonfill.dev):
{sum(counts.values()):,} items, each with the feed it belongs to, a readable title, a short
summary, a link to the record at its source, and its date. Built with `unlimited backfill`,
which runs each feed's own pipeline over the past; from the SEC's Form 345 data sets for
insider trades; and, where a source keeps its history elsewhere, with the scripts in
research/public (FRED, the ECB, NASA EONET, OFAC, DefiLlama), which write the feeds' own
titles (https://github.com/Fuyuki0/unlimitedpipe).

| Feed | Items | Dates | Source | License |
| --- | --- | --- | --- | --- |
{table}

Titles and summaries are written by UnlimitedPipe from the records ("NVIDIA (NVDA): Jensen Huang
(CEO) sold 120,000 shares at $180.50 ($21.7M)"); every item links to the record it comes from.
Insider trades are open-market purchases and sales of $100,000 or more.

Attribution: breach data by Have I Been Pwned (CC BY 4.0); crypto data by DefiLlama; world
events from Wikipedia's Current events portal by Wikipedia contributors (CC BY-SA 4.0: the
world-events file is shared under the same licence); Kp index by GFZ Potsdam (CC BY 4.0,
doi:10.5880/Kp.0001); typhoon tracks by the Japan Meteorological Agency; UK bills contain
Parliamentary information licensed under the Open Parliament Licence v3.0.
"""


def main(site: str, out: str, insider: str | None = None) -> None:
    rows = rows_of(Path(site), Path(insider) if insider else None)
    folder = Path(out) / "data"
    folder.mkdir(parents=True, exist_ok=True)
    counts, spans = {}, {}
    for feed, items in rows.items():
        pq.write_table(pa.Table.from_pylist(items), folder / f"{feed}.parquet", compression="zstd")
        counts[feed] = len(items)
        spans[feed] = (str(items[0]["date"])[:7], str(items[-1]["date"])[:7])
        print(feed, len(items), spans[feed])
    (Path(out) / "README.md").write_text(card(counts, spans), encoding="utf-8")


if __name__ == "__main__":
    main(*sys.argv[1:4])
