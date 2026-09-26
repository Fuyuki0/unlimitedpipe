"""The ``search`` source: search a published feed catalog (its feeds.json) in one request."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any
from urllib.parse import urljoin

from unlimitedpipe.component import Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError
from unlimitedpipe.event import Event

# The public catalog built with UnlimitedPipe; any site made by `unlimited publish` works.
DEFAULT_CATALOG = "https://feeds.daemonfill.dev/"


def catalog_url(base: str | None) -> str:
    base = base or os.environ.get("UNLIMITEDPIPE_CATALOG") or DEFAULT_CATALOG
    return base if base.endswith(".json") else base.rstrip("/") + "/feeds.json"


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
    response = await ctx.http.get(url)
    try:
        document = response.json()
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
    )

    words: list[str] = arg("Words that must all appear", metavar="WORDS...", default_factory=list)
    feed: list[str] = opt(
        "Only search this feed (repeatable)", metavar="NAME", default_factory=list
    )
    catalog: str | None = opt("Catalog site or feeds.json URL", default=None)
    limit: int = opt("Most results to return", default=20)
    list_feeds: bool = opt("List the catalog's feeds instead of searching", default=False)

    def __post_init__(self) -> None:
        if not self.words and not self.list_feeds:
            raise ValueError("search needs words to look for, or --list-feeds")
        if self.limit < 1:
            raise ValueError("--limit must be at least 1")

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
                files = [urljoin(url, f) for f in feed.get("files", [])]
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
        found = 0
        for item in document.get("items", []):
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
