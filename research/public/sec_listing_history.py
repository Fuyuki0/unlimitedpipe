"""The SEC's press releases and litigation releases from its newsroom listings, as items of the
sec-press-releases and sec-enforcement feeds, with their titles (works of the US government).
The SEC asks automated readers for a contact email: give it in $SEC_CONTACT.

    SEC_CONTACT=you@example.com \\
        research/.venv/bin/python research/public/sec_listing_history.py OUT.jsonl
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time

import httpx

SITE = "https://www.sec.gov"
LISTINGS = {
    "sec-press-releases": "/newsroom/press-releases",
    "sec-enforcement": "/enforcement-litigation/litigation-releases",
}
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)


def text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def rows(page: str) -> list[tuple[str, str, str, str]]:
    """(date, title, link, release number) of each row of a listing page."""
    found = []
    for row in ROW.findall(page):
        when = re.search(r'datetime="([^"]+)"', row)
        link = re.search(r"""href=["'](/[^"']+)["'][^>]*>(.*?)</a>""", row, re.S)
        number = re.findall(r'subfield_value">\s*([^<]+?)\s*<', row) or re.findall(
            r">\s*(\d{4}-\d+)\s*<", row
        )
        if when and link:
            found.append((when[1], text(link[2]), SITE + link[1], number[0] if number else ""))
    return found


def item(feed: str, when: str, title: str, link: str, number: str) -> dict:
    if feed == "sec-enforcement":
        return {
            "feed": feed,
            "title": f"SEC lawsuit: {title}",
            "summary": f"The SEC filed a civil action in federal court against {title} "
            f"(litigation release {number}).",
            "link": link,
            "date": when,
        }
    return {
        "feed": feed,
        "title": title,
        "summary": f"SEC press release {number}." if number else "",
        "link": link,
        "date": when,
    }


def main(out: str) -> None:
    contact = os.environ["SEC_CONTACT"]
    agent = {"User-Agent": f"UnlimitedPipe {contact}"}  # the SEC turns away agents with a URL
    with (
        open(out, "w", encoding="utf-8") as lines,
        httpx.Client(headers=agent, timeout=120) as http,
    ):
        for feed, path in LISTINGS.items():
            count, page = 0, 0
            while True:
                response = http.get(SITE + path, params={"page": page})
                if "Request Rate Threshold Exceeded" in response.text:
                    print("the SEC refused; waiting ten minutes", flush=True)
                    time.sleep(600)  # the SEC's ten-minute pause
                    continue
                response.raise_for_status()
                found = rows(response.text)
                if not found:
                    break
                for row in found:
                    lines.write(json.dumps(item(feed, *row), ensure_ascii=False) + "\n")
                count += len(found)
                page += 1
                time.sleep(1)
            print(feed, count, "releases,", page, "pages", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
