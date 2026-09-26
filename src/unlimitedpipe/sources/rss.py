"""The ``rss`` source: RSS, Atom and JSON Feed, one event per item."""

from __future__ import annotations

import html as htmllib
import json
import re
import warnings
from datetime import UTC, datetime
from typing import Any

from unlimitedpipe.component import Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError
from unlimitedpipe.event import Event, is_envelope
from unlimitedpipe.sources import input_urls

# Map data in feeds, dropped when feedparser cannot read it.
_GEO = re.compile(rb"<(georss:where|gml:[A-Za-z]+)\b.*?</\1>", re.S)
# Links and spans are glued to their text (`#<span>tag</span>` is "#tag"); bold and the like
# often act as headings with no space after them ("<b>Background</b>Post-acute").
_INLINE_TAG = re.compile(r"</?(a|span)(\s[^>]*)?>", re.I)


def strip_html(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>", "\n", text, flags=re.I)
    text = _INLINE_TAG.sub("", text)  # `#<span>tag</span>` is "#tag", not "# tag"
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", text))
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _iso(parsed: Any) -> str | None:
    """feedparser's UTC ``time.struct_time`` -> ISO 8601."""
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None


def _web_link(entry: Any) -> str | None:
    """The entry's page. feedparser can report an Atom ``urn:`` id as the link when an entry
    lists its id before its links; prefer a web link, the alternate one first."""
    link = entry.get("link")
    if isinstance(link, str) and link.startswith(("http://", "https://")):
        return link
    links = [item for item in entry.get("links") or [] if isinstance(item, dict)]
    web = [item for item in links if str(item.get("href", "")).startswith(("http://", "https://"))]
    for item in sorted(web, key=lambda item: item.get("rel", "alternate") != "alternate"):
        if item.get("rel", "alternate") != "enclosure":
            return item["href"]
    return link


def _is_json_feed(content: bytes, content_type: str) -> dict[str, Any] | None:
    if "json" not in content_type and not content.lstrip().startswith(b"{"):
        return None
    try:
        document = json.loads(content)
    except ValueError:
        return None
    version = document.get("version") if isinstance(document, dict) else None
    if isinstance(version, str) and version.startswith("https://jsonfeed.org/version/"):
        return document
    return None


class Rss(Source):
    """Read RSS, Atom or JSON Feed and emit one ``entry`` event per item.

    Items keep their id as the event key, so ``| unlimited diff --only added`` emits only new
    posts. Given a web page instead of a feed, the feed it advertises is used. JSON Feeds
    written by UnlimitedPipe return their original events, provenance included.
    """

    name = "rss"
    url: list[str] = arg(
        "Feed URLs, or pages that link to a feed (or piped in)", default_factory=list
    )
    content: bool = opt("Include full item content, not just the summary", default=False)
    timeout: float = opt("Seconds to wait for each response", default=20.0)
    user_agent: str | None = opt(
        "User-Agent header (default identifies UnlimitedPipe)", default=None
    )
    cache: bool = opt("Revalidate unchanged feeds with ETag/Last-Modified", default=True)

    async def collect(self, ctx: Context):
        async for url in input_urls(self.url, ctx, command="rss"):
            try:
                events = await self.fetch(url, ctx)
            except FetchError as exc:
                error = ctx.fail(exc, source=self.name, url=url)
                if error is not None:
                    yield error
                continue
            for event in events:
                yield event

    async def fetch(self, url: str, ctx: Context, *, discovered: bool = False) -> list[Event]:
        from unlimitedpipe.http import normalize_url

        url = normalize_url(url)
        response = await ctx.http.get(
            url, timeout=self.timeout, user_agent=self.user_agent, cache=self.cache
        )
        meta = {
            "status": response.status,
            "final_url": response.final_url,
            "elapsed_ms": response.elapsed_ms,
            "not_modified": response.from_cache,
        }
        document = _is_json_feed(response.content, response.content_type)
        if document is not None:
            return self._json_feed(url, document, meta)

        import feedparser

        headers = {
            "content-type": response.headers.get("content-type", ""),
            "content-location": response.final_url,
        }
        try:
            parsed = feedparser.parse(response.content, response_headers=headers)
        except Exception:  # feedparser can fail on map data it misreads (a GML srsName URL)
            content = _GEO.sub(b"", response.content)
            try:
                parsed = feedparser.parse(content, response_headers=headers)
            except Exception as exc:
                raise FetchError(f"{url} could not be read as a feed ({exc})", url=url) from None
        if not parsed.entries and not parsed.get("version"):
            reason = parsed.get("bozo_exception") or "no items found"
            if not discovered and "html" in response.content_type:
                from unlimitedpipe import html

                soup = html.parse(response.content, response.encoding)
                feeds = html.feeds(soup, response.final_url)
                if feeds:
                    ctx.notice(f"rss: {url} is a page; reading its feed {feeds[0]}")
                    return await self.fetch(feeds[0], ctx, discovered=True)
                reason = "it is a web page and advertises no feed"
            raise FetchError(
                f"{url} is not a readable feed ({reason})",
                url=url,
                hint=f"find the site's feeds with: unlimited inspect {url}",
            )
        feed = parsed.feed
        feed_info = {"title": feed.get("title"), "url": feed.get("link"), "feed_url": url}
        meta["method"] = parsed.get("version") or "feed"
        with warnings.catch_warnings():
            # feedparser warns when `updated_parsed` falls back to `published_parsed`.
            warnings.simplefilter("ignore", DeprecationWarning)
            return [self._entry_event(url, entry, feed_info, meta) for entry in parsed.entries]

    def _entry_event(
        self, url: str, entry: Any, feed_info: dict[str, Any], meta: dict[str, Any]
    ) -> Event:
        link = _web_link(entry)
        published = _iso(entry.get("published_parsed")) or _iso(entry.get("updated_parsed"))
        data: dict[str, Any] = {
            "title": " ".join((entry.get("title") or "").split()) or None,
            "link": link,
            "id": entry.get("id") or link,
            "author": entry.get("author"),
            "published_at": published,
            "updated_at": _iso(entry.get("updated_parsed")),
            "summary": strip_html(entry.get("summary"))[:2000] or None,
            "categories": [t.get("term") for t in entry.get("tags") or [] if t.get("term")],
            "feed": feed_info,
        }
        enclosures = [e.get("href") for e in entry.get("enclosures") or [] if e.get("href")]
        if enclosures:
            data["enclosures"] = enclosures
        if self.content and entry.get("content"):
            data["content"] = strip_html(entry["content"][0].get("value"))
        return Event(
            source=self.name,
            type="entry",
            source_url=url,
            key=data["id"],
            timestamp=published,
            data=data,
            metadata=meta,
        )

    def _json_feed(self, url: str, document: dict[str, Any], meta: dict[str, Any]) -> list[Event]:
        feed_info = {
            "title": document.get("title"),
            "url": document.get("home_page_url"),
            "feed_url": url,
        }
        meta = {**meta, "method": "json-feed"}
        events = []
        for item in document.get("items") or []:
            if not isinstance(item, dict):
                continue
            extension = item.get("_unlimitedpipe")
            original = extension.get("event") if isinstance(extension, dict) else None
            if is_envelope(original):
                event = Event.from_dict(original)
                event.metadata = {**event.metadata, "via_feed": url}
                events.append(event)
                continue
            authors = item.get("authors") or ([item["author"]] if item.get("author") else [])
            summary = (
                item.get("summary")
                or item.get("content_text")
                or strip_html(item.get("content_html"))
            )
            data = {
                "title": item.get("title"),
                "link": item.get("url") or item.get("external_url"),
                "id": item.get("id"),
                "author": authors[0].get("name")
                if authors and isinstance(authors[0], dict)
                else None,
                "published_at": item.get("date_published"),
                "updated_at": item.get("date_modified"),
                "summary": (summary or "")[:2000] or None,
                "categories": [t for t in item.get("tags") or [] if isinstance(t, str)],
                "feed": feed_info,
            }
            if self.content:
                data["content"] = item.get("content_text") or strip_html(item.get("content_html"))
            events.append(
                Event(
                    source=self.name,
                    type="entry",
                    source_url=url,
                    key=str(data["id"] or data["link"]),
                    timestamp=data["published_at"],
                    data=data,
                    metadata=meta,
                )
            )
        return events
