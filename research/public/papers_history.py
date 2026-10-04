"""Research papers as items of two feeds, written as those feeds write them:

- ai-papers: Hugging Face Daily Papers, day by day since May 2023 (the papers' arXiv metadata);
- health-papers: medRxiv preprints since 2019, first versions only, from medRxiv's API. The
  abstract's opening is kept only for preprints under a Creative Commons licence; others keep
  their title.

    research/.venv/bin/python research/public/papers_history.py OUT.jsonl 2026-09-25
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import date, timedelta

import httpx

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
DAILY = "https://huggingface.co/api/daily_papers?date={day}"
MEDRXIV = "https://api.medrxiv.org/details/medrxiv/{start}/{end}/{cursor}"


def _get(http: httpx.Client, url: str):
    for attempt in range(5):
        try:
            response = http.get(url)
            if response.status_code < 500 and response.status_code != 429:
                response.raise_for_status()
                return response.json()
        except httpx.TransportError:
            pass
        time.sleep(15 * (attempt + 1))
    raise SystemExit(f"no answer from {url}")


def _abstract(text: str) -> str:
    text = re.sub(
        r"^(Background|Objectives?|Introduction|Aims?|Purpose|Importance|Context|Rationale)"
        r"(?=[A-Z])",
        r"\1: ",
        " ".join(text.split()),
    )
    return text[:300]


def main(out: str, until: str) -> None:
    stop = date.fromisoformat(until)
    written = 0
    with (
        httpx.Client(headers=AGENT, timeout=120) as http,
        open(out, "w", encoding="utf-8") as lines,
    ):
        day = date(2023, 5, 4)
        while day < stop:
            for paper in _get(http, DAILY.format(day=day)) or []:
                info = paper.get("paper") or {}
                if not (paper.get("title") and info.get("id")):
                    continue
                entry = {
                    "feed": "ai-papers",
                    "title": " ".join(paper["title"].split()),
                    "summary": " ".join((paper.get("summary") or "").split())[:300],
                    "link": f"https://huggingface.co/papers/{info['id']}",
                    "date": f"{day.isoformat()}T00:00:00Z",
                }
                lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
                written += 1
            print("ai-papers", day, written, flush=True)
            day += timedelta(days=1)
            time.sleep(0.5)
        start = date(2019, 6, 1)
        while start < stop:
            end = min(start + timedelta(days=29), stop - timedelta(days=1))
            cursor = 0
            while True:
                document = _get(http, MEDRXIV.format(start=start, end=end, cursor=cursor))
                papers = document.get("collection") or []
                for paper in papers:
                    if str(paper.get("version")) != "1" or not paper.get("title"):
                        continue
                    licence = str(paper.get("license") or "")
                    summary = _abstract(paper.get("abstract") or "") if "cc_" in licence else ""
                    if licence and licence != "cc_no":
                        summary = (summary + " " if summary else "") + (
                            f"medRxiv preprint ({paper.get('category')}), "
                            f"{licence.replace('_', '-').upper()}."
                        )
                    entry = {
                        "feed": "health-papers",
                        "title": "Preprint: " + " ".join(paper["title"].split()),
                        "summary": summary.strip(),
                        "link": f"https://www.medrxiv.org/content/{paper['doi']}v1",
                        "date": f"{paper['date']}T00:00:00Z",
                    }
                    lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    written += 1
                cursor += len(papers)
                total = int((document.get("messages") or [{}])[0].get("total") or 0)
                time.sleep(0.5)
                if not papers or cursor >= total:
                    break
            print("health-papers", start, written, flush=True)
            start = end + timedelta(days=1)
    print(written, "papers")


if __name__ == "__main__":
    main(*sys.argv[1:3])
