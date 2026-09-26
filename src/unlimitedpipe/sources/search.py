"""The ``search`` source: search a published feed catalog (its feeds.json) in one request."""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from unlimitedpipe.component import Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError
from unlimitedpipe.event import Event

# The public catalog built with UnlimitedPipe; any site made by `unlimited publish` works.
DEFAULT_CATALOG = "https://feeds.daemonfill.dev/"


def catalog_url(base: str | None) -> str:
    """Where a catalog's feeds.json is: a site, a feeds.json URL, or a local folder or file
    (a downloaded or cloned catalog works offline)."""
    base = base or os.environ.get("UNLIMITEDPIPE_CATALOG") or DEFAULT_CATALOG
    if not _is_web(base):
        path = Path(base).expanduser()
        return str(path / "feeds.json" if path.is_dir() else path)
    return base if base.endswith(".json") else base.rstrip("/") + "/feeds.json"


def _is_web(location: str) -> bool:
    return bool(re.match(r"^https?://", location, re.IGNORECASE))


def join(base: str, relative: str) -> str:
    """A path inside a catalog, next to its feeds.json."""
    return urljoin(base, relative) if _is_web(base) else str(Path(base).parent / relative)


async def read(ctx: Context, location: str) -> bytes:
    if _is_web(location):
        return (await ctx.http.get(location)).content
    try:
        return Path(location).read_bytes()
    except OSError as exc:
        raise FetchError(f"cannot read {location}: {exc.strerror or exc}", url=location) from None


@lru_cache(maxsize=256)
def word_pattern(word: str) -> re.Pattern[str]:
    # A word matches at the start of a word ("hack" finds "hacks", not "Thackeray"). Scripts
    # written without spaces, such as Thai or Chinese, match anywhere.
    if word.isascii():
        return re.compile(r"(?<!\w)" + re.escape(word), re.IGNORECASE)
    return re.compile(re.escape(word), re.IGNORECASE)


def matches(item: dict[str, Any], words: list[str], about: str = "") -> bool:
    """Every word appears in the title or summary, or in the name of the item's feed
    ("insider" finds every item of insider-trades), ignoring case."""
    text = f"{item.get('title') or ''} {item.get('summary') or ''} {about}"
    return all(word_pattern(word).search(text) for word in words)


async def load_catalog(ctx: Context, url: str) -> dict[str, Any]:
    try:
        document = json.loads(await read(ctx, url))
    except ValueError:
        raise FetchError(f"{url} is not a feed catalog", url=url) from None
    if not isinstance(document, dict) or not str(document.get("schema", "")).startswith(
        "unlimitedpipe.catalog/"
    ):
        raise FetchError(
            f"{url} is not a feed catalog",
            url=url,
            hint="point --catalog at a site made by `unlimited publish` (it serves feeds.json)",
        )
    return document


async def items_since(
    ctx: Context, url: str, document: dict[str, Any], since: str
) -> list[dict[str, Any]]:
    """The catalog's latest items plus its archive from ``since`` (a month or a day) on,
    each once, newest first."""
    from unlimitedpipe.archive import item_key

    merged = {item_key(i): i for i in document.get("items", [])}
    index_url = join(url, document.get("archive") or "archive/index.json")
    try:
        index = json.loads(await read(ctx, index_url))
    except (FetchError, ValueError):
        ctx.warn(f"{url} has no archive; searching its latest items only")
        index = {"months": []}
    for month in index.get("months", []):
        if str(month.get("month", "")) < since[:7]:
            continue
        content = await read(ctx, join(index_url, str(month.get("file"))))
        for line in content.decode("utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                merged.setdefault(item.get("key") or item_key(item), item)
    items = [
        i
        for i in merged.values()
        if str(i.get("date") or i.get("seen") or "")[: len(since)] >= since
    ]
    items.sort(key=lambda i: str(i.get("date") or ""), reverse=True)
    return items


class Search(Source):
    """Search every feed of a published catalog at once, or list its feeds.

    A catalog is a site made by `unlimited publish`: its feeds.json holds the latest items of
    all its feeds, refreshed after every run, so a search is one request and answers
    instantly. Every result links to its original source. The default catalog is
    https://feeds.daemonfill.dev/ (50+ feeds on money, government, security, crypto,
    disasters and world news); use `--catalog` or `$UNLIMITEDPIPE_CATALOG` for another.
    """

    name = "search"
    examples = (
        "unlimited search bankruptcy",
        'unlimited search "cyber" --feed sec-company-events --feed security-news',
        "unlimited search --list-feeds              # the feeds and what they follow",
        "unlimited search sanctions --since 2026-08   # the archive too, from August on",
    )

    words: list[str] = arg("Words that must all appear", metavar="WORDS...", default_factory=list)
    feed: list[str] = opt(
        "Only search this feed (repeatable)", metavar="NAME", default_factory=list
    )
    catalog: str | None = opt(
        "Catalog: a site, a feeds.json URL, or a downloaded catalog folder", default=None
    )
    since: str | None = opt(
        "Also search the archive back to this month or day (2026-08, 2026-08-15)",
        default=None,
        metavar="DATE",
    )
    limit: int = opt("Most results to return", default=20)
    list_feeds: bool = opt("List the catalog's feeds instead of searching", default=False)

    def __post_init__(self) -> None:
        from unlimitedpipe.archive import parse_since

        if not self.words and not self.list_feeds:
            raise ValueError("search needs words to look for, or --list-feeds")
        if self.limit < 1:
            raise ValueError("--limit must be at least 1")
        if self.since:
            self.since = parse_since(self.since)

    async def collect(self, ctx: Context):
        url = catalog_url(self.catalog)
        try:
            document = await load_catalog(ctx, url)
        except FetchError as exc:
            if (error := ctx.fail(exc, source=self.name, url=url)) is not None:
                yield error
            return
        wanted = set(self.feed)
        if self.list_feeds:
            for feed in document.get("feeds", []):
                if wanted and feed.get("name") not in wanted:
                    continue
                files = [join(url, f) for f in feed.get("files", [])]
                yield Event(
                    source=self.name,
                    type="feed",
                    key=files[0] if files else feed.get("name"),
                    source_url=url,
                    data={
                        "title": feed.get("name"),
                        "summary": feed.get("description"),
                        "files": files,
                    },
                )
            return
        # A feed's name counts ("insider" finds insider-trades); its description would match
        # too much ("hack" in "Hacker News").
        about = {
            f.get("name"): str(f.get("name", "")).replace("-", " ")
            for f in document.get("feeds", [])
        }
        items = document.get("items", [])
        if self.since:
            try:
                items = await items_since(ctx, url, document, self.since)
            except FetchError as exc:
                if (error := ctx.fail(exc, source=self.name, url=url)) is not None:
                    yield error
                return
        found = 0
        for item in items:
            if wanted and item.get("feed") not in wanted:
                continue
            if not matches(item, self.words, about.get(item.get("feed"), "")):
                continue
            yield Event(
                source=self.name,
                type="entry",
                key=item.get("link"),
                source_url=item.get("link") or url,
                timestamp=item.get("date"),
                data={
                    "title": item.get("title"),
                    "summary": item.get("summary"),
                    "link": item.get("link"),
                    "published_at": item.get("date"),
                    "feed": item.get("feed"),
                },
                metadata={"catalog": url},
            )
            found += 1
            if found >= self.limit:
                return
