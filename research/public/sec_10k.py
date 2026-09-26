"""SEC annual reports (Form 10-K), one record per filing, from EDGAR.

EDGAR's quarterly index lists every filing; for each 10-K, the filing's index page names its
main document, whose text is extracted (HTML and the hidden XBRL header removed). The SEC asks
automated readers to identify themselves with a contact email ($SEC_CONTACT) and to stay
under 10 requests a second; this makes at most 5.

Each record: id (accession number), cik, company, form, filed, text, url (the filing's index
page), source_url (the document), license, fetched_at.

    SEC_CONTACT=you@example.com research/.venv/bin/python research/public/sec_10k.py 2025 1 5
"""

from __future__ import annotations

import os
import re
import sys
import time
from datetime import UTC, datetime
from typing import Iterator

import httpx
from lxml import html as lxml_html

INDEX = "https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/form.idx"
ARCHIVES = "https://www.sec.gov/Archives/"
LICENSE = (
    "Public record filed with the US Securities and Exchange Commission (EDGAR); "
    "the text is the filing company's"
)


class Polite:
    """An HTTP client that keeps at least `gap` seconds between requests."""

    def __init__(self, contact: str, gap: float = 0.2) -> None:
        self.client = httpx.Client(
            headers={
                "User-Agent": f"UnlimitedPipe-research {contact}",
                "Accept-Encoding": "gzip, deflate",
            },
            follow_redirects=True,
            timeout=60,
        )
        self.gap, self.last = gap, 0.0

    def get(self, url: str) -> httpx.Response:
        wait = self.last + self.gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        for attempt in range(4):
            self.last = time.monotonic()
            response = self.client.get(url)
            if response.status_code in (429, 503):
                time.sleep(10 * (attempt + 1))  # the SEC asks to back off
                continue
            response.raise_for_status()
            return response
        response.raise_for_status()
        return response


def filings(client: Polite, year: int, quarter: int) -> Iterator[dict]:
    """10-K filings (not amendments) from the quarter's index."""
    lines = client.get(INDEX.format(year=year, quarter=quarter)).text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("----")) + 1
    for line in lines[start:]:
        if not line.startswith("10-K "):
            continue
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 5:
            continue
        form, company, cik, filed, path = parts[0], parts[1], parts[2], parts[3], parts[-1]
        accession = path.rsplit("/", 1)[-1].removesuffix(".txt")
        folder = f"{ARCHIVES}edgar/data/{cik}/{accession.replace('-', '')}/"
        yield {
            "id": accession,
            "cik": cik,
            "company": company,
            "form": form,
            "filed": filed,
            "url": f"{folder}{accession}-index.htm",
        }


def main_document(client: Polite, index_url: str) -> str | None:
    page = lxml_html.fromstring(client.get(index_url).content)
    for row in page.xpath("//table[@class='tableFile']//tr"):
        cells = row.xpath("./td")
        if len(cells) >= 4 and cells[3].text_content().strip() == "10-K":
            links = cells[2].xpath(".//a/@href")
            if links:
                href = links[0].replace("/ix?doc=", "")
                return href if href.startswith("http") else "https://www.sec.gov" + href
    return None


BLOCKS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "td"}


def document_text(content: bytes) -> str:
    root = lxml_html.fromstring(content)
    hidden = root.xpath(
        "//script|//style|//title|//*[contains(translate(@style, 'DISPLAYNOE ', "
        "'displaynoe'), 'display:none')]"
    )
    hidden += [n for n in root.iter() if isinstance(n.tag, str) and n.tag.lower() == "ix:header"]
    for node in hidden:
        node.drop_tree()  # the hidden XBRL facts, which are data, not text
    for node in root.iter():
        if isinstance(node.tag, str) and node.tag.lower() in BLOCKS:
            node.tail = "\n" + (node.tail or "")
    lines = (" ".join(line.split()) for line in root.text_content().splitlines())
    text = "\n".join(line for line in lines if line)
    return re.sub(r"\n{3,}", "\n\n", text)


def records(client: Polite, year: int, quarter: int, limit: int | None = None):
    for n, filing in enumerate(filings(client, year, quarter)):
        if limit is not None and n >= limit:
            return
        try:
            doc = main_document(client, filing["url"])
            if doc is None:
                continue
            text = document_text(client.get(doc).content)
        except (httpx.HTTPError, ValueError) as exc:
            print(f"skip {filing['id']}: {exc}", file=sys.stderr, flush=True)
            continue
        if len(text) < 2000:
            continue
        yield {
            **filing,
            "text": text,
            "source_url": doc,
            "license": LICENSE,
            "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


if __name__ == "__main__":
    contact = os.environ.get("SEC_CONTACT", "")
    if "@" not in contact:
        sys.exit("set SEC_CONTACT to a contact email, as the SEC asks")
    year, quarter, limit = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
    client = Polite(contact)
    for record in records(client, year, quarter, limit):
        words = len(record["text"].split())
        print(record["company"], record["filed"], f"{words:,} words", record["source_url"])
        print("   ", record["text"][:200].replace("\n", " | "))
