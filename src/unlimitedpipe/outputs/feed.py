"""Publish events as a feed: RSS 2.0, Atom or JSON Feed 1.1.

JSON Feed items carry the full event under ``_unlimitedpipe``, so another pipeline reading the
feed with ``unlimited rss`` gets the original events back, provenance included.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from typing import Any, Literal

from unlimitedpipe._version import PROJECT_URL, __version__
from unlimitedpipe.component import Output, arg, opt
from unlimitedpipe.event import SCHEMA, Event, content_hash, utcnow
from unlimitedpipe.outputs import open_target

ATOM_NS = "http://www.w3.org/2005/Atom"
# Feeds carry titles, links and short summaries: enough to decide what to read, without
# republishing other people's full text.
SUMMARY_CHARS = 500
GENERATOR = f"UnlimitedPipe {__version__}"


def _parse_iso(value: str | None) -> datetime:
    if value:
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _previous_link(existing: str | None) -> str | None:
    """The site link of a feed file written earlier, so an empty run keeps it."""
    if not existing:
        return None
    match = re.search(
        r'"home_page_url":\s*"([^"]+)"|<link>([^<]+)</link>|<link href="([^"]+)"', existing
    )
    return next((group for group in match.groups() if group), None) if match else None


def _shorten(text: str | None, limit: int) -> str | None:
    if text is None or len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"


_METADATA_LINE = re.compile(r"^[#\w .-]{1,24}:\s*\S*$")
_PLAIN_FACTS = ("title", "name", "label", "link", "url", "summary", "description", "text", "id")


def _prose(text: str | None) -> str | None:
    """Drop summaries that carry no prose, like Hacker News' "Article URL: … Points: 74"
    lines or a lone "Comments"."""
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if all(_METADATA_LINE.match(line) for line in lines) or len(text.split()) < 2:
        return None
    return text


def _facts(data: dict[str, Any]) -> str | None:
    """``price $99 · stock In stock`` for records that have no text of their own."""
    facts = [
        f"{key} {value}"
        for key, value in data.items()
        if key not in _PLAIN_FACTS
        and isinstance(value, (str, int, float))
        and value not in ("", False)
    ][:4]
    return " · ".join(facts) or None


def _summary(data: dict[str, Any]) -> str | None:
    return (
        _prose(_text(data.get("summary")))
        or _prose(_text(data.get("description")))
        or _prose(_text(data.get("text")))
    )


def feed_item(event: Event) -> dict[str, Any]:
    """The reader-facing fields of an event: title, link, summary, date, id."""
    data = event.data
    if event.type == "change":
        label = _text(data.get("label")) or event.label
        kind = str(data.get("change"))
        details = data.get("after") or data.get("before") or {}
        details = details if isinstance(details, dict) else {}
        link = _text(details.get("link")) or _text(details.get("url")) or event.source_url
        textual = data.get("item_type") in ("entry", "document", "release", "story")
        if kind in ("added", "removed"):  # a new item reads like the item itself
            title = label if kind == "added" else f"Removed: {label}"
            summary = _summary(details) or (None if textual else _facts(details))
        else:
            # The title carries the change; list every field only when it had to cut some.
            title = f"{label}: {data.get('summary', 'changed')}"
            fields = data.get("fields") or []
            summary = (
                "\n".join(f"{f.get('path')}: {f.get('old')} → {f.get('new')}" for f in fields)
                if len(fields) > 4
                else None
            )
    else:
        details = data
        title = event.label
        link = _text(data.get("link")) or _text(data.get("url")) or event.source_url
        summary = _summary(data)
    categories = details.get("categories") if isinstance(details, dict) else None
    return {
        "id": event.id,
        "title": title,
        "link": link,
        "summary": _shorten(summary, SUMMARY_CHARS),
        "date": _parse_iso(
            event.timestamp
            or _text(details.get("published_at") if isinstance(details, dict) else None)
            or _text(details.get("date") if isinstance(details, dict) else None)
            or event.observed_at
        ),
        "categories": [c for c in categories or [] if isinstance(c, str)],
    }


class Feed(Output):
    """Write events as an RSS, Atom or JSON Feed file that any feed reader can subscribe to.

    The format follows the file extension (.xml/.rss: RSS, .atom: Atom, .json: JSON Feed).
    Items from earlier runs are kept (newest first, up to ``--max-items``), so a feed of
    changes keeps its history even when a run finds nothing new.
    """

    name = "feed"
    path: str | None = arg("Feed file to write (default: stdout)", default=None)
    format: Literal["auto", "rss", "atom", "json"] = opt("Feed format", default="auto")
    title: str | None = opt("Feed title", default=None)
    link: str | None = opt("Link to the site the feed is about", default=None)
    description: str | None = opt("Feed description", default=None)
    max_items: int = opt("Keep at most this many items", default=100)
    keep: bool = opt("Keep items from earlier runs", default=True)

    def __post_init__(self) -> None:
        if self.max_items < 1:
            raise ValueError("--max-items must be at least 1")

    @property
    def resolved_format(self) -> str:
        if self.format != "auto":
            return self.format
        suffix = Path(self.path).suffix.lower() if self.path else ""
        return {".json": "json", ".atom": "atom"}.get(suffix, "rss")

    async def open(self, ctx) -> None:
        self._events: list[Event] = []

    async def write(self, event: Event) -> None:
        self._events.append(event)

    def _meta(self, existing: str | None) -> dict[str, str]:
        first = self._events[0] if self._events else None
        link = (
            self.link
            or (first.source_url if first else None)
            or _previous_link(existing)
            or PROJECT_URL
        )
        title = self.title or f"UnlimitedPipe: {link}"
        return {
            "title": title,
            "link": link,
            "description": self.description or f"Events collected by {GENERATOR}",
        }

    def _existing(self) -> str | None:
        if not (self.keep and self.path):
            return None
        target = Path(self.path).expanduser()
        return target.read_text(encoding="utf-8") if target.exists() else None

    async def close(self) -> None:
        builder = {"rss": self._rss, "atom": self._atom, "json": self._json}[self.resolved_format]
        existing = self._existing()
        if existing is not None and not self._events:
            return  # nothing new: leave the file (and its build date) exactly as it was
        text = builder(self._meta(existing), existing)
        stream, is_stdout = open_target(self.path)
        stream.write(text)
        if is_stdout:
            stream.flush()
        else:
            stream.close()

    def _rss(self, meta: dict[str, str], existing: str | None) -> str:
        rss = ET.Element("rss", {"version": "2.0"})
        channel = ET.SubElement(rss, "channel")
        for tag in ("title", "link", "description"):
            ET.SubElement(channel, tag).text = meta[tag]
        ET.SubElement(channel, "generator").text = GENERATOR
        ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(UTC))
        ids: set[str] = set()
        for event in self._events:
            item = feed_item(event)
            if item["id"] in ids:
                continue
            ids.add(item["id"])
            node = ET.SubElement(channel, "item")
            ET.SubElement(node, "title").text = item["title"]
            if item["link"]:
                ET.SubElement(node, "link").text = item["link"]
            ET.SubElement(node, "guid", {"isPermaLink": "false"}).text = item["id"]
            ET.SubElement(node, "pubDate").text = format_datetime(item["date"])
            if item["summary"]:
                ET.SubElement(node, "description").text = item["summary"]
            for category in item["categories"]:
                ET.SubElement(node, "category").text = category
        if existing:
            try:
                old_channel = ET.fromstring(existing).find("channel")
            except ET.ParseError:
                old_channel = None
            for node in old_channel.findall("item") if old_channel is not None else []:
                guid = node.findtext("guid")
                if guid and guid not in ids:
                    ids.add(guid)
                    channel.append(node)
        for extra in channel.findall("item")[self.max_items :]:
            channel.remove(extra)
        ET.indent(rss)
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(rss, encoding="unicode") + "\n"
        )

    def _atom(self, meta: dict[str, str], existing: str | None) -> str:
        ET.register_namespace("", ATOM_NS)

        def q(tag: str) -> str:
            return f"{{{ATOM_NS}}}{tag}"

        feed = ET.Element(q("feed"))
        ET.SubElement(feed, q("title")).text = meta["title"]
        ET.SubElement(feed, q("subtitle")).text = meta["description"]
        ET.SubElement(
            feed, q("id")
        ).text = f"urn:unlimitedpipe:feed:{content_hash(meta['link'], meta['title'])[:20]}"
        ET.SubElement(feed, q("updated")).text = utcnow()
        ET.SubElement(feed, q("link"), {"href": meta["link"]})
        author = ET.SubElement(feed, q("author"))
        ET.SubElement(author, q("name")).text = "UnlimitedPipe"
        ET.SubElement(feed, q("generator")).text = GENERATOR
        ids: set[str] = set()
        for event in self._events:
            item = feed_item(event)
            entry_id = f"urn:unlimitedpipe:{item['id']}"
            if entry_id in ids:
                continue
            ids.add(entry_id)
            entry = ET.SubElement(feed, q("entry"))
            ET.SubElement(entry, q("title")).text = item["title"]
            ET.SubElement(entry, q("id")).text = entry_id
            ET.SubElement(entry, q("updated")).text = item["date"].strftime("%Y-%m-%dT%H:%M:%SZ")
            if item["link"]:
                ET.SubElement(entry, q("link"), {"href": item["link"]})
            if item["summary"]:
                ET.SubElement(entry, q("summary")).text = item["summary"]
            for category in item["categories"]:
                ET.SubElement(entry, q("category"), {"term": category})
        if existing:
            try:
                old_entries = ET.fromstring(existing).findall(q("entry"))
            except ET.ParseError:
                old_entries = []
            for entry in old_entries:
                entry_id = entry.findtext(q("id"))
                if entry_id and entry_id not in ids:
                    ids.add(entry_id)
                    feed.append(entry)
        for extra in feed.findall(q("entry"))[self.max_items :]:
            feed.remove(extra)
        ET.indent(feed)
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            + ET.tostring(feed, encoding="unicode")
            + "\n"
        )

    def _json(self, meta: dict[str, str], existing: str | None) -> str:
        items: list[dict[str, Any]] = []
        ids: set[str] = set()
        for event in self._events:
            item = feed_item(event)
            if item["id"] in ids:
                continue
            ids.add(item["id"])
            entry: dict[str, Any] = {
                "id": item["id"],
                "title": item["title"],
                "content_text": item["summary"] or item["title"],
                "date_published": item["date"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "_unlimitedpipe": {"event": event.to_dict()},
            }
            if item["link"]:
                entry["url"] = item["link"]
            if item["categories"]:
                entry["tags"] = item["categories"]
            items.append(entry)
        if existing:
            try:
                old_items = json.loads(existing).get("items", [])
            except (ValueError, AttributeError):
                old_items = []
            for entry in old_items:
                entry_id = entry.get("id") if isinstance(entry, dict) else None
                if isinstance(entry_id, str) and entry_id not in ids:
                    ids.add(entry_id)
                    items.append(entry)
        document = {
            "version": "https://jsonfeed.org/version/1.1",
            "title": meta["title"],
            "home_page_url": meta["link"],
            "description": meta["description"],
            "_unlimitedpipe": {"schema": SCHEMA, "generator": GENERATOR},
            "items": items[: self.max_items],
        }
        return json.dumps(document, ensure_ascii=False, indent=2, default=str) + "\n"
