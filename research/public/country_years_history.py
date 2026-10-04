"""Each country's events, year by year, from Wikipedia's "<year> in <country>" articles (CC BY-SA
4.0, credited in each summary), as items of the country and regional news feeds: what happened
in Japan in 2011 is in japan-news, Nigeria's years are in africa-news. Only the articles' Events
lists are read (not births or deaths), from the rendered pages.

    research/.venv/bin/python research/public/country_years_history.py OUT.jsonl 2001 2026
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import date

import httpx
from bs4 import BeautifulSoup, Tag

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
WIKI = "https://en.wikipedia.org/wiki/"
FEEDS = {
    "japan-news": ["Japan"],
    "korea-news": ["South Korea", "North Korea"],
    "india-news": ["India"],
    "china-news": ["China"],
    "taiwan-news": ["Taiwan"],
    "russia-news": ["Russia", "Ukraine"],
    "thailand-news": ["Thailand"],
    "singapore-news": ["Singapore"],
    "southeast-asia-news": [
        "Indonesia",
        "the Philippines",
        "Vietnam",
        "Malaysia",
        "Myanmar",
        "Cambodia",
    ],
    "australia-news": ["Australia", "New Zealand"],
    "us-news": ["the United States"],
    "europe-news": [
        "the United Kingdom",
        "France",
        "Germany",
        "Italy",
        "Spain",
        "Poland",
        "the Netherlands",
    ],
    "middle-east-news": ["Israel", "Iran", "Iraq", "Saudi Arabia", "Turkey", "Syria", "Lebanon"],
    "africa-news": ["Nigeria", "South Africa", "Kenya", "Ethiopia", "Egypt", "Ghana"],
    "latin-america-news": [
        "Brazil",
        "Mexico",
        "Argentina",
        "Colombia",
        "Chile",
        "Venezuela",
        "Peru",
    ],
}
MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
_MONTH = "|".join(MONTHS)
_DATE = re.compile(rf"^\s*(?:({_MONTH})\s+(\d{{1,2}})|(\d{{1,2}})\s+({_MONTH}))\b")
_LEAD = re.compile(rf"^\s*(?:(?:{_MONTH})\s+\d{{1,2}}|\d{{1,2}}\s+(?:{_MONTH}))[^–—:-]*[–—:-]\s*")


def _text(node: Tag) -> str:
    for mark in node.select("sup"):
        mark.decompose()
    return " ".join(node.get_text().split())


def _own_text(item: Tag) -> str:
    parts = [
        c.get_text() if isinstance(c, Tag) else str(c)
        for c in item.children
        if not (isinstance(c, Tag) and c.name in ("ul", "ol"))
    ]
    return " ".join(" ".join(parts).split())


def _day(year: int, text: str, month: int | None) -> date | None:
    if match := _DATE.match(text):
        name = match[1] or match[4]
        number = int(match[2] or match[3])
        try:
            return date(year, MONTHS.index(name) + 1, number)
        except ValueError:
            return None
    return date(year, month, 1) if month else None


def events(page: str, year: int) -> list[tuple[date, str]]:
    soup = BeautifulSoup(page, "lxml")
    heading = soup.find(id="Events")
    section = heading.find_parent("section") if heading else None
    if section is None:
        return []
    found = []
    month: int | None = None
    for node in section.find_all(["h3", "h4", "li"]):
        if node.name in ("h3", "h4"):
            name = node.get_text().strip()
            month = MONTHS.index(name) + 1 if name in MONTHS else month
            continue
        if node.find(["ul", "ol"]):
            continue  # a date with its events listed under it
        parent = node.find_parent("li")
        label = _own_text(parent) if parent and section in parent.parents else ""
        own = _text(node)
        when = _day(year, own, month) or _day(year, label, month)
        text = _LEAD.sub("", own).strip()
        if when is None or len(text) < 25:
            continue
        found.append((when, text))
    return found


def main(out: str, first: str, last: str) -> None:
    written = 0
    with (
        httpx.Client(headers=AGENT, timeout=60, follow_redirects=True) as http,
        open(out, "w", encoding="utf-8") as lines,
    ):
        for feed, countries in FEEDS.items():
            for country in countries:
                for year in range(int(first), int(last) + 1):
                    article = f"{year} in {country}"
                    url = WIKI + article.replace(" ", "_")
                    for attempt in range(4):
                        try:
                            response = http.get(url)
                            if response.status_code < 500 and response.status_code != 429:
                                break
                        except httpx.TransportError:
                            pass
                        time.sleep(15 * (attempt + 1))
                    time.sleep(1)
                    if response.status_code != 200:
                        continue
                    found = events(response.text, year)
                    name = country.removeprefix("the ")
                    for when, text in found:
                        title = f"{name}: {text}"
                        if len(title) > 300:
                            cut = title.rfind(". ", 0, 300)
                            title = title[: cut + 1] if cut > 80 else title[:299].rstrip() + "…"
                        entry = {
                            "feed": feed,
                            "title": title,
                            "summary": f'{text} From Wikipedia\'s article "{article}" (CC BY-SA '
                            "4.0).",
                            "link": url,
                            "date": f"{when.isoformat()}T00:00:00Z",
                        }
                        lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    written += len(found)
                    print(feed, article, len(found), flush=True)
    print(written, "events")


if __name__ == "__main__":
    main(*sys.argv[1:4])
