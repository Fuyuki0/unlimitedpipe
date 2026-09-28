"""OFAC's recent actions (designations, removals, general licenses) as items of the
sanctions-actions feed, from its listing pages, oldest pages last. Works of the US Treasury.

    research/.venv/bin/python research/public/ofac_history.py OUT.jsonl
"""

from __future__ import annotations

import json
import re
import sys
import time

import httpx
from bs4 import BeautifulSoup

PAGE = "https://ofac.treasury.gov/recent-actions?page={}"
AGENT = "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"


def page_items(html: str) -> list[dict]:
    items = []
    for row in BeautifulSoup(html, "html.parser").select(".views-row"):
        anchor = row.select_one(".text-no-underline a")
        meta = row.select_one(".font-sans-2xs")
        if anchor is None or not anchor.get("href"):
            continue
        href = str(anchor["href"])
        link = href if href.startswith("http") else "https://ofac.treasury.gov" + href
        day = re.search(r"/(\d{4})(\d\d)(\d\d)", href)
        if not day:
            continue
        meta_text = " ".join(meta.get_text(" ").split()) if meta else ""
        items.append(
            {
                "feed": "sanctions-actions",
                "title": " ".join(anchor.get_text(" ").split()),
                "summary": re.sub(r"^.*?\d{4}\s*-\s*", "", meta_text),
                "link": link,
                "date": f"{day[1]}-{day[2]}-{day[3]}T00:00:00Z",
            }
        )
    return items


def main(out: str) -> None:
    count = 0
    with open(out, "w", encoding="utf-8") as lines, httpx.Client(timeout=60) as client:
        for number in range(0, 2000):
            response = client.get(PAGE.format(number), headers={"User-Agent": AGENT})
            response.raise_for_status()
            found = page_items(response.text)
            if not found:
                break
            for item in found:
                lines.write(json.dumps(item, ensure_ascii=False) + "\n")
            count += len(found)
            time.sleep(1)
    print(count, "actions,", number, "pages")


if __name__ == "__main__":
    main(sys.argv[1])
