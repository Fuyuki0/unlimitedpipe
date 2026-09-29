"""arXiv papers in cs.CL and cs.AI about language models and agents (matched on titles, as the
arxiv-llm feed matches them), month by month, as items of that feed. arXiv's metadata is CC0;
its API asks for three seconds between requests.

    research/.venv/bin/python research/public/arxiv_history.py OUT.jsonl FROM_YEAR TO_YEAR
"""

from __future__ import annotations

import calendar
import json
import re
import sys
import time
import xml.etree.ElementTree as ET

import httpx

API = "https://export.arxiv.org/api/query"
AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
ATOM = "{http://www.w3.org/2005/Atom}"
WORDS = [
    "LLM",
    "LLMs",
    "language model",
    "language models",
    "agent",
    "agents",
    "agentic",
    "reasoning",
]
MATCH = re.compile(r"\b(" + "|".join(re.escape(w) for w in WORDS) + r")\b", re.IGNORECASE)
TITLES = " OR ".join(
    f'ti:"{w}"' for w in ("LLM", "language model", "agent", "agentic", "reasoning")
)
PAGE = 1000


def month_items(year: int, month: int) -> list[dict]:
    last = calendar.monthrange(year, month)[1]
    window = f"submittedDate:[{year}{month:02d}010000 TO {year}{month:02d}{last}2359]"
    query = f"(cat:cs.CL OR cat:cs.AI) AND ({TITLES}) AND {window}"
    found, start = [], 0
    while True:
        for attempt in range(6):  # arXiv answers 503 when busy: wait and ask again
            response = httpx.get(
                API,
                params={
                    "search_query": query,
                    "start": start,
                    "max_results": PAGE,
                    "sortBy": "submittedDate",
                    "sortOrder": "ascending",
                },
                headers=AGENT,
                timeout=180,
            )
            if response.status_code != 503:
                break
            time.sleep(30 * (attempt + 1))
        response.raise_for_status()
        entries = ET.fromstring(response.content).findall(f"{ATOM}entry")
        for entry in entries:
            title = " ".join((entry.findtext(f"{ATOM}title") or "").split())
            if not MATCH.search(title):
                continue
            link = re.sub(r"v\d+$", "", (entry.findtext(f"{ATOM}id") or "").strip())
            found.append(
                {
                    "feed": "arxiv-llm",
                    "title": title,
                    "summary": " ".join((entry.findtext(f"{ATOM}summary") or "").split())[:500],
                    "link": link.replace("http://", "https://"),
                    "date": (entry.findtext(f"{ATOM}published") or "").strip(),
                }
            )
        time.sleep(3)
        if len(entries) < PAGE:
            return found
        start += PAGE


def main(out: str, first: str, last: str) -> None:
    written = 0
    with open(out, "w", encoding="utf-8") as lines:
        for year in range(int(first), int(last) + 1):
            for month in range(1, 13):
                for item in month_items(year, month):
                    lines.write(json.dumps(item, ensure_ascii=False) + "\n")
                    written += 1
            print(year, written, flush=True)
    print(written, "papers")


if __name__ == "__main__":
    main(*sys.argv[1:4])
