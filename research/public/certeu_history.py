"""CERT-EU's security advisories since 2011, from its yearly publication lists, as items of the
security-advisories feed, written as the feed writes them ("CERT-EU: 2024-099: Critical
Vulnerabilities in Openshift").

    research/.venv/bin/python research/public/certeu_history.py OUT.jsonl 2011 2026
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime, timedelta

import httpx
from bs4 import BeautifulSoup

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
SITE = "https://cert.europa.eu"
LIST = SITE + "/publications/security-advisories/{year}"
ZONES = {"CEST": 2, "CET": 1}


def when(text: str) -> str | None:
    parts = text.split()
    zone = ZONES.get(parts[-1]) if parts else None
    try:
        local = datetime.strptime(" ".join(parts[:-1]), "%A, %B %d, %Y %I:%M:%S %p")
    except ValueError:
        return None
    moment = local - timedelta(hours=zone or 0)
    return moment.replace(tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(out: str, first: str, last: str) -> None:
    written = 0
    with (
        httpx.Client(headers=AGENT, timeout=60, follow_redirects=False) as http,
        open(out, "w", encoding="utf-8") as lines,
    ):
        for year in range(int(first), int(last) + 1):
            response = http.get(LIST.format(year=year))
            time.sleep(2)
            if response.status_code != 200:
                print(year, response.status_code, flush=True)
                continue
            soup = BeautifulSoup(response.text, "lxml")
            count = 0
            for link in soup.select("a.publications--list--item--link"):
                title = link.select_one(".publications--list--item--link--title")
                date = link.select_one(".publications--list--item--link--date")
                about = link.select_one(".publications--list--item--link--description")
                moment = when(date.get_text(" ", strip=True)) if date else None
                if not (title and moment):
                    continue
                entry = {
                    "feed": "security-advisories",
                    "title": "CERT-EU: " + " ".join(title.get_text().split()),
                    "summary": " ".join(about.get_text().split())[:500] if about else "",
                    "link": SITE + str(link["href"]),
                    "date": moment,
                }
                lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
                count += 1
            written += count
            print(year, count, flush=True)
    print(written, "advisories")


if __name__ == "__main__":
    main(*sys.argv[1:4])
