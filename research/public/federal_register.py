"""Federal Register documents, one record per document, from govinfo's bulk data.

The Federal Register is the US government's daily journal of rules, proposed rules, notices
and presidential documents. Works of the US government are in the public domain. govinfo
publishes each month as one zip of daily XML issues at https://www.govinfo.gov/bulkdata/FR,
which robots.txt allows; this reads one month at a time, politely.

Each record: id (the FR document number), date, type, agency, title, text, url, source_url,
license, fetched_at. Records are written as zstandard-compressed JSONL, one file per month.

    research/.venv/bin/python research/public/federal_register.py 2026-09 out/
"""

from __future__ import annotations

import io
import json
import re
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

import httpx

BULK = "https://www.govinfo.gov/bulkdata/FR/{year}/{month}/FR-{year}-{month}.zip"
AGENT = "UnlimitedPipe-research/0.1 (public-domain corpus; github.com/Fuyuki0/unlimitedpipe)"
SECTIONS = {
    "RULE": "rule",
    "PRORULE": "proposed rule",
    "NOTICE": "notice",
    "PRESDOCU": "presidential document",
}
FRDOC = re.compile(r"FR Doc\.\s*([\dE]+-\d+)")


def text_of(node: ElementTree.Element) -> str:
    """The document's paragraphs and headings, one per line, without the XML."""
    lines = []
    for element in node.iter():
        if element.tag in ("P", "FP", "HD", "SUBJECT", "AGENCY", "SUBAGY", "EXTRACT"):
            line = " ".join("".join(element.itertext()).split())
            if line:
                lines.append(line)
    return "\n".join(dict.fromkeys(lines))  # EXTRACT repeats its paragraphs


def documents(xml: bytes, date: str, fetched_at: str, source_url: str):
    root = ElementTree.fromstring(xml)
    for tag, kind in SECTIONS.items():
        for node in root.iter(tag):
            number = FRDOC.search(" ".join(node.itertext()))
            if not number:
                continue
            agency = (
                " ".join("".join(n.itertext()).split())
                if (n := node.find(".//AGENCY")) is not None
                else ""
            )
            subject = (
                " ".join("".join(n.itertext()).split())
                if (n := node.find(".//SUBJECT")) is not None
                else ""
            )
            text = text_of(node)
            if len(text) < 200:
                continue
            yield {
                "id": number.group(1),
                "date": date,
                "type": kind,
                "agency": agency,
                "title": subject,
                "text": text,
                "url": f"https://www.federalregister.gov/d/{number.group(1)}",
                "source_url": source_url,
                "license": "Public domain (work of the US government)",
                "fetched_at": fetched_at,
            }


def month(year: int, month: int, folder: Path, client: httpx.Client) -> dict:
    """Download one month, write its records; returns counts."""
    import zstandard

    url = BULK.format(year=year, month=f"{month:02d}")
    fetched_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    response = client.get(url, timeout=120)
    response.raise_for_status()
    out = folder / f"federal-register-{year}-{month:02d}.jsonl.zst"
    counts = {"documents": 0, "words": 0, "bytes_in": len(response.content)}
    seen = set()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive, out.open("wb") as raw:
        writer = zstandard.ZstdCompressor(level=10).stream_writer(raw)
        for name in sorted(n for n in archive.namelist() if n.endswith(".xml")):
            day = re.search(r"(\d{4}-\d{2}-\d{2})", name)
            for record in documents(
                archive.read(name), day.group(1) if day else "", fetched_at, url
            ):
                if record["id"] in seen:
                    continue
                seen.add(record["id"])
                writer.write((json.dumps(record, ensure_ascii=False) + "\n").encode())
                counts["documents"] += 1
                counts["words"] += len(record["text"].split())
        writer.flush(zstandard.FLUSH_FRAME)
    counts["bytes_out"] = out.stat().st_size
    counts["file"] = out.name
    return counts


def main(spec: str, out: str) -> None:
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    first, _, last = spec.partition("..")
    y, m = map(int, first.split("-"))
    ly, lm = map(int, (last or first).split("-"))
    with httpx.Client(headers={"User-Agent": AGENT}, follow_redirects=True) as client:
        while (y, m) <= (ly, lm):
            counts = month(y, m, folder, client)
            print(json.dumps({"month": f"{y}-{m:02d}", **counts}), flush=True)
            time.sleep(2)  # polite: one month at a time
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "research/public/out")
