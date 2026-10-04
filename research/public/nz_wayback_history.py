"""New Zealand government press releases (beehive.govt.nz) since 2008, from the Internet
Archive's copies of each release page: beehive.govt.nz turns automated readers away, the
Wayback Machine keeps the pages it captured. One page a second; a page that holds no release
(a captured bot check) is skipped. Items of the nz-government feed (New Zealand Government,
CC BY 4.0).

    research/.venv/bin/python research/public/nz_wayback_history.py SLUGS.txt OUT.jsonl

SLUGS.txt lines are "slug url timestamp", from the Wayback CDX API:
    https://web.archive.org/cdx/search/cdx?url=beehive.govt.nz/release/&matchType=prefix
        &collapse=urlkey&filter=statuscode:200&filter=mimetype:text/html&fl=original,timestamp
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
SNAPSHOT = "https://web.archive.org/web/{stamp}id_/{url}"
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE = re.compile(rf"\b(\d{{1,2}}) ({MONTHS}),? ((?:19|20)\d\d)\b")


def release(page: str) -> tuple[str, str | None, str] | None:
    """The release's title, date (when the page states one) and opening, or None."""
    soup = BeautifulSoup(page, "lxml")
    heading = soup.find("h1")
    title = " ".join(heading.get_text().split()) if heading else ""
    if len(title) < 8:
        return None
    body = soup.select_one(".field-name-body, .article__body, .body, article")
    text = " ".join(body.get_text(" ").split()) if body else ""
    when = None
    stamp = soup.find("time", attrs={"datetime": True})
    shown = soup.select_one(".date-display-single")
    if stamp and re.match(r"\d{4}-\d\d-\d\d", str(stamp["datetime"])):
        when = str(stamp["datetime"])[:10]
    elif match := _DATE.search(shown.get_text() if shown else text[:400]):
        when = datetime.strptime(" ".join(match.groups()), "%d %B %Y").date().isoformat()
    _, found, after = text.partition(title)  # the page repeats the title before the text
    return title, when, (after if found else text).strip()[:300]


def main(slugs: str, out: str) -> None:
    done = set()
    target = Path(out)
    if target.exists():
        done = {json.loads(line)["link"] for line in target.read_text().split("\n") if line}
    written = 0
    with (
        httpx.Client(headers=AGENT, timeout=60, follow_redirects=True) as http,
        target.open("a", encoding="utf-8") as lines,
    ):
        for number, line in enumerate(Path(slugs).read_text().split("\n"), 1):
            if not line.strip():
                continue
            slug, url, stamp = line.split()
            link = f"https://www.beehive.govt.nz/release/{slug}"
            if link in done:
                continue
            page = None
            for attempt in range(4):
                try:
                    response = http.get(SNAPSHOT.format(stamp=stamp, url=url))
                    if response.status_code == 200:
                        page = response.text
                        break
                    if response.status_code == 404:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(20 * (attempt + 1))
            time.sleep(1)
            found = release(page) if page else None
            if found is None:
                continue
            title, when, opening = found
            day = when or f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}"
            entry = {
                "feed": "nz-government",
                "title": title,
                "summary": opening,
                "link": link,
                "date": f"{day}T00:00:00Z",
            }
            lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
            lines.flush()
            written += 1
            if number % 200 == 0:
                print(number, written, flush=True)
    print(written, "releases")


if __name__ == "__main__":
    main(*sys.argv[1:3])
