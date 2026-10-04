"""The day's events from Wikipedia's Current events portal, one item per event."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from bs4 import BeautifulSoup, Tag

from unlimitedpipe.component import Source, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError
from unlimitedpipe.event import Event

MONTHS = (
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
)
WIKI = "https://en.wikipedia.org/wiki/"
CREDIT = "From Wikipedia's Current events portal (CC BY-SA 4.0)."
_DAY_ID = re.compile(r"^(\d{4})_([A-Z][a-z]+)_(\d{1,2})$")


def day_page(day: date) -> str:
    """The portal's page for a day, such as Portal:Current_events/2024_January_5."""
    return f"{WIKI}Portal:Current_events/{day.year}_{MONTHS[day.month - 1]}_{day.day}"


def month_page(year: int, month: int) -> str:
    """The portal's page for a month, which shows all its days."""
    return f"{WIKI}Portal:Current_events/{MONTHS[month - 1]}_{year}"


def _day_of(region: Tag) -> date | None:
    match = _DAY_ID.match(str(region.get("id") or ""))
    if not match or match[2] not in MONTHS:
        return None
    try:
        return date(int(match[1]), MONTHS.index(match[2]) + 1, int(match[3]))
    except ValueError:
        return None


def _text(node: Tag) -> str:
    return " ".join(node.get_text().split())


def _label(item: Tag) -> str:
    """A topic's name: the text of a list item without its nested lists."""
    parts = [
        child.get_text(" ") if isinstance(child, Tag) else str(child)
        for child in item.children
        if not (isinstance(child, Tag) and child.name in ("ul", "ol"))
    ]
    return " ".join(" ".join(parts).split())


def _event(item: Tag) -> tuple[str, list[tuple[str, str]]]:
    """An event's sentence, without its reference marks and source links, and its sources as
    (name, url)."""
    sources = []
    for link in item.select("a.external"):
        name = link.get_text(" ").strip().strip("()").strip()
        if name and link.get("href"):
            sources.append((name, str(link["href"])))
        link.decompose()
    for mark in item.select("sup"):
        mark.decompose()
    text = _text(item)
    text = re.sub(r"\(\s*\)|\s+(?=[.,;:])", "", text).strip()
    return text, sources


def _walk(lists: list[Tag], path: list[str], found: list[tuple[list[str], Tag]]) -> None:
    for lst in lists:
        for item in lst.find_all("li", recursive=False):
            nested = item.find_all(["ul", "ol"], recursive=False)
            if nested:
                _walk(nested, [*path, _label(item)], found)
            else:
                found.append((path, item))


def _title(text: str, limit: int = 300) -> str:
    """The event's sentence, cut at a sentence end when it runs long."""
    if len(text) <= limit:
        return text
    cut = text.rfind(". ", 0, limit)
    return text[: cut + 1] if cut > 80 else text[: limit - 1].rstrip() + "…"


def events(document: str, days: set[date] | None = None) -> list[dict[str, Any]]:
    """Each event on a day or month page of the portal (only those of `days` when given), in
    the page's order, with its date, category, topic path and sources."""
    soup = BeautifulSoup(document, "lxml")
    found = []
    for region in soup.select("div.current-events-main"):
        day = _day_of(region)
        if day is None or (days is not None and day not in days):
            continue
        content = region.select_one(".current-events-content")
        if content is None:
            continue
        category = ""
        for child in content.find_all(recursive=False):
            if child.name in ("ul", "ol"):
                leaves: list[tuple[list[str], Tag]] = []
                _walk([child], [], leaves)
                for path, item in leaves:
                    text, sources = _event(item)
                    if len(text) < 25:
                        continue
                    found.append(
                        {
                            "day": day,
                            "category": category,
                            "topic": path,
                            "text": text,
                            "sources": sources,
                        }
                    )
            elif child.name in ("p", "div") and (heading := _text(child)) and len(heading) < 60:
                category = heading[0].upper() + heading[1:].lower()  # "Disasters and Accidents"
    return found


def event_item(event: dict[str, Any]) -> dict[str, Any]:
    day: date = event["day"]
    summary = [event["text"]]
    if event["topic"]:
        summary.append("Topic: " + ", ".join(event["topic"]) + ".")
    if event["category"]:
        summary.append(f"Section: {event['category']}.")
    if event["sources"]:
        summary.append("Sources: " + ", ".join(name for name, _ in event["sources"]) + ".")
    summary.append(CREDIT)
    return {
        "title": _title(event["text"]),
        "summary": " ".join(summary),
        "link": day_page(day),
        "published_at": f"{day.isoformat()}T00:00:00Z",
        "category": event["category"],
        "topic": event["topic"],
        "sources": [url for _, url in event["sources"]],
    }


class CurrentEvents(Source):
    """Events of the last days from Wikipedia's Current events portal: what editors note as
    happening in the world, each with its topic and the news reports it cites.

    Editors add events through the day, and to yesterday's page too, so --days 2 (the default)
    reads today's page and yesterday's. Text is Wikipedia's, under CC BY-SA 4.0.
    """

    name = "current-events"
    examples = ("unlimited current-events", "unlimited current-events --days 3")

    days: int = opt("Read this many days' pages, today's first", default=2)
    timeout: float = opt("Seconds to wait for Wikipedia", default=20.0)

    async def collect(self, ctx: Context):
        today = datetime.now(UTC).date()
        for back in range(max(1, self.days)):
            day = today - timedelta(days=back)
            url = day_page(day)
            try:
                response = await ctx.http.get(url, timeout=self.timeout, robots=True, cache=False)
            except FetchError as exc:
                if exc.status == 404:  # no page yet for today
                    continue
                if (error := ctx.fail(exc, source=self.name, url=url)) is not None:
                    yield error
                continue
            for event in events(response.text, {day}):
                item = event_item(event)
                yield Event(
                    source=self.name,
                    type="event",
                    source_url=url,
                    key=f"{day.isoformat()}:{' '.join(item['title'].casefold().split())[:120]}",
                    timestamp=item["published_at"],
                    data=item,
                    metadata={"method": "wikipedia-current-events"},
                )
