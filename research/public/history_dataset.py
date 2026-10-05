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
    "uk-government": ("GOV.UK announcements (search API)", "Open Government Licence v3.0"),
    "uk-sanctions": ("GOV.UK and OFSI sanctions announcements", "Open Government Licence v3.0"),
    "canada-government": (
        "Government of Canada news (canada.ca news API)",
        "Open Government Licence - Canada",
    ),
    "australia-government": ("Prime Minister of Australia media (pm.gov.au)", "CC BY 4.0"),
    "nz-government": ("New Zealand Government releases (beehive.govt.nz)", "CC BY 4.0"),
    "eu-laws": (
        "EUR-Lex metadata (EU Publications Office)",
        "reuse authorised, source acknowledged (Commission Decision 2011/833/EU)",
    ),
    "world-bank-tenders": ("World Bank procurement notices API", "CC BY 4.0"),
    "us-justice": ("US Department of Justice press releases", "public domain"),
    "fda-news": ("FDA press announcements", "public domain"),
    "hurricanes": (
        "NOAA National Hurricane Center best track (HURDAT2) and advisories",
        "public domain",
    ),
    "us-flight-delays": (
        "Bureau of Transportation Statistics on-time data; FAA airport status",
        "public domain",
    ),
    "defi-liquidations": ("Aave events on Ethereum and Base (public chain data)", "public data"),
    "whale-transfers": ("USDT and USDC transfers on Ethereum (public chain data)", "public data"),
}
# Feeds that mix outlets' headlines (left out) with history from Wikipedia: only items whose
# summary says they come from Wikipedia are kept, under CC BY-SA 4.0.
FROM_WIKIPEDIA = "From Wikipedia's article"
for _feed in [
    "japan-news",
    "korea-news",
    "india-news",
    "china-news",
    "taiwan-news",
    "russia-news",
    "thailand-news",
    "singapore-news",
    "southeast-asia-news",
    "australia-news",
    "us-news",
    "europe-news",
    "middle-east-news",
    "africa-news",
    "latin-america-news",
]:
    FEEDS[_feed] = ('Wikipedia, "<year> in <country>" articles', "CC BY-SA 4.0")
# Feeds whose other items come from sources that are not public: only these titles are kept.
ONLY = {"volcanoes": "Historical eruption:"}
LEFT_OUT = ("US 30-year mortgage rate",)  # Freddie Mac's survey, not a government series


def rows_of(site: Path, insider: Path | None) -> dict[str, list[dict]]:
    found: dict[str, dict[str, dict]] = collections.defaultdict(dict)
    from unlimitedpipe.archive import _month_files, _text, lines_of

    sources = _month_files(site / "archive")  # compressed months too
    lines = (line for path in sources for line in lines_of(_text(path)))
    if insider:
        lines = (*lines, *insider.open(encoding="utf-8"))
    for line in lines:
        if not line.strip():
            continue
        item = json.loads(line)
        feed = item.get("feed")
        title = str(item.get("title") or "")
        if feed not in FEEDS or title.startswith(LEFT_OUT):
            continue
        if feed in ONLY and not title.startswith(ONLY[feed]):
            continue
        wikipedia_only = FEEDS[feed][1] == "CC BY-SA 4.0" and feed != "world-events"
        if wikipedia_only and FROM_WIKIPEDIA not in str(item.get("summary") or ""):
            continue
        row = {k: item.get(k) for k in ("feed", "title", "summary", "link", "date")}
        found[feed].setdefault(f"{row['link']}\n{str(row['title']).casefold()}", row)
    return {
        feed: sorted(rows.values(), key=lambda r: r["date"] or "") for feed, rows in found.items()
    }


def share_alike(feed: str) -> bool:
    """Feeds under CC BY-SA 4.0 (Wikipedia's): kept in their own config, so the default one
    carries no share-alike terms."""
    return "CC BY-SA" in FEEDS[feed][1]


def card(counts: dict[str, int], spans: dict[str, tuple[str, str]], day: str) -> str:
    def table(feeds: list[str]) -> str:
        return "\n".join(
            f"| {feed} | {counts[feed]:,} | {spans[feed][0]} to {spans[feed][1]} | "
            f"{FEEDS[feed][0]} | {FEEDS[feed][1]} |"
            for feed in sorted(feeds, key=lambda f: -counts[f])
        )

    open_feeds = [f for f in counts if not share_alike(f)]
    wiki_feeds = [f for f in counts if share_alike(f)]
    total = sum(counts.values())
    in_open = sum(counts[f] for f in open_feeds)
    header = "| Feed | Items | Dates | Source | License |\n| --- | --- | --- | --- | --- |"
    return f"""---
license: other
license_name: public-domain-open-licences-and-cc-by-sa
language: [en]
pretty_name: UnlimitedPipe feed history (public records)
task_categories: [text-retrieval, question-answering, time-series-forecasting]
tags: [public-records, events, sec, government, disasters, crypto, time-series]
size_categories: [1M<n<10M]
configs:
  - config_name: default
    data_files: data/*.parquet
  - config_name: wikipedia
    data_files: wikipedia/*.parquet
---

# feed-history

The history of UnlimitedPipe's public-record feeds (https://feeds.daemonfill.dev): {total:,}
dated events back to 1851, each with a readable title, a short summary and a link to the record
at its official source. SEC filings and insider trades, new laws and rules, sanctions, rate
decisions, earnings releases, earthquakes, hurricanes, typhoons and solar storms, recalls,
vulnerabilities, government announcements of the US, UK, Canada, the EU, Australia and New
Zealand, federal contracts and grants, and crypto market and on-chain events. Updated {day}.

## Load it

```python
from datasets import load_dataset

events = load_dataset("unlimitedpipe/feed-history", split="train")  # every open-licence feed
quakes = load_dataset("unlimitedpipe/feed-history", data_files="data/earthquakes.parquet")
world = load_dataset("unlimitedpipe/feed-history", "wikipedia", split="train")  # CC BY-SA
```

Each feed is one Parquet file, so a single feed can be read on its own (`pandas.read_parquet`).

An example notebook, [examples/explore.ipynb](examples/explore.ipynb), charts great earthquakes
by decade, money lost to crypto hacks, insider buying and selling, and strong hurricanes.

## Columns

| Column | Type | Meaning |
| --- | --- | --- |
| `feed` | string | The feed it belongs to (the file's name) |
| `title` | string | One line written by UnlimitedPipe from the record ("M 9.1 - Tohoku, Japan") |
| `summary` | string | A short summary, or null (about 0.03% of rows) |
| `link` | string | The record at its official source |
| `date` | string | When it happened or was published, ISO 8601 (UTC) |

## The default config: public domain and open licences ({in_open:,} items)

{header}
{table(open_feeds)}

## The wikipedia config: CC BY-SA 4.0 ({total - in_open:,} items)

The world's events day by day since 2002 (Wikipedia's Current events portal) and each
country's year by year ("<year> in <country>" articles). Anything built from them must be
shared under CC BY-SA 4.0 too, which is why they are kept apart.

{header}
{table(wiki_feeds)}

## How it was made, and its limits

Built with `unlimited backfill`, which runs each feed's own pipeline over the past, and the
scripts in [research/public](https://github.com/Fuyuki0/unlimitedpipe/tree/main/research/public)
(FRED, the ECB, NASA EONET, OFAC, DefiLlama, BigQuery's public Ethereum data, JMA, HURDAT2 and
more), all through official APIs, bulk files and robots.txt-allowed pages.

- Titles and summaries are UnlimitedPipe's sentences, not the documents' full text ("NVIDIA
  (NVDA): Jensen Huang (CEO) sold 120,000 shares at $180.50 ($21.7M)"); follow `link` for the
  record. For full text of US government documents, see
  [unlimitedpipe/public-records](https://huggingface.co/datasets/unlimitedpipe/public-records).
- Feeds keep what crosses their bar: insider trades of $100,000 or more, earthquakes of
  magnitude 4.5 or more (6 and more before 1973), stablecoin transfers of $25M or more,
  and so on, as each feed's description on the site says.
- Coverage is strongest for the United States. Some old place names keep the "?" the source
  itself has (USGS: "47 km E of ?arai, Japan").
- News headlines, Hacker News titles and licensed market indices (S&P 500, Dow, Nasdaq,
  Nikkei, VIX) are left out.

## Updates

Rebuilt from the live catalog's archive about once a month; the catalog itself adds new
items every minute to every hour at https://feeds.daemonfill.dev.

## Cite

```bibtex
@misc{{unlimitedpipe_feed_history,
  title  = {{feed-history: dated public-record events with their sources}},
  author = {{UnlimitedPipe}},
  year   = {{2026}},
  url    = {{https://huggingface.co/datasets/unlimitedpipe/feed-history}}
}}
```

Attribution: breach data by Have I Been Pwned (CC BY 4.0); crypto data by DefiLlama; world
events from Wikipedia's Current events portal by Wikipedia contributors (CC BY-SA 4.0: the
world-events file is shared under the same licence); Kp index by GFZ Potsdam (CC BY 4.0,
doi:10.5880/Kp.0001); typhoon tracks by the Japan Meteorological Agency; UK bills contain
Parliamentary information licensed under the Open Parliament Licence v3.0.
"""


def main(site: str, out: str, insider: str | None = None) -> None:
    from datetime import UTC, datetime

    rows = rows_of(Path(site), Path(insider) if insider else None)
    counts, spans = {}, {}
    for feed, items in rows.items():
        folder = Path(out) / ("wikipedia" if share_alike(feed) else "data")
        folder.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(items), folder / f"{feed}.parquet", compression="zstd")
        counts[feed] = len(items)
        spans[feed] = (str(items[0]["date"])[:7], str(items[-1]["date"])[:7])
        print(feed, len(items), spans[feed])
    day = datetime.now(UTC).strftime("%Y-%m-%d")
    (Path(out) / "README.md").write_text(card(counts, spans, day), encoding="utf-8")


if __name__ == "__main__":
    main(*sys.argv[1:4])
