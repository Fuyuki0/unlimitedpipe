"""The ``search`` source: search a published feed catalog (its feeds.json) in one request."""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from unlimitedpipe import thai
from unlimitedpipe.archive import item_key
from unlimitedpipe.component import Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError, UsageError
from unlimitedpipe.event import Event

# The public catalog built with UnlimitedPipe; any site made by `unlimited publish` works.
DEFAULT_CATALOG = "https://feeds.daemonfill.dev/"


def offline_copy() -> Path:
    """Where `unlimited setup` and `unlimited mirror` keep a copy of the catalog, used when the
    internet is not there: the user's data folder, or $UNLIMITEDPIPE_DATA_DIR."""
    override = os.environ.get("UNLIMITEDPIPE_DATA_DIR")
    if override:
        return Path(override).expanduser() / "catalog"
    import platformdirs

    return platformdirs.user_data_path("unlimitedpipe") / "catalog"


def catalog_url(base: str | None) -> str:
    """Where a catalog's feeds.json is: a site, a feeds.json URL, a local folder or file (a
    downloaded or cloned catalog works offline), or `offline` for the copy `mirror` keeps."""
    base = base or os.environ.get("UNLIMITEDPIPE_CATALOG") or DEFAULT_CATALOG
    if base == "offline" and not Path(base).exists():
        return str(offline_copy() / "feeds.json")
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


def stem(word: str) -> str:
    """An English word cut to the part its other forms share, so that "hacks" also finds
    "hack" and "hacked", and "companies" finds "company". Short words stay whole."""
    lower = word.casefold()
    if lower.endswith(("ss", "us", "is", "ws")):  # class, status, crisis, news
        return lower
    if lower.endswith("y") and len(lower) >= 5:
        return lower[:-1]  # company, companies
    for suffix, keep in (("ies", ""), ("ing", ""), ("ed", ""), ("es", "e"), ("s", "")):
        if lower.endswith(suffix):
            base = lower[: -len(suffix)]
            if suffix == "es" and base.endswith(("s", "x", "z", "ch", "sh")):
                keep = ""  # crashes -> crash
            if len(base) >= 4 or (suffix in ("s", "es") and len(base) >= 3):
                return base + keep
    return lower


# Past forms that do not start like the word, for verbs common in news and filings.
IRREGULAR = {
    "buy": ("bought",),
    "sell": ("sold",),
    "rise": ("rose", "risen"),
    "fall": ("fell", "fallen"),
    "win": ("won",),
    "lose": ("lost",),
    "pay": ("paid",),
    "steal": ("stole",),
    "say": ("said",),
    "hold": ("held",),
    "spend": ("spent",),
    "strike": ("struck",),
    "shake": ("shook",),
}


@lru_cache(maxsize=256)
def word_pattern(word: str) -> re.Pattern[str]:
    # A word matches at the start of a word, in any of its forms ("hacks" finds "hack" and
    # "hacked", not "Thackeray"; "buys" finds "bought"). Scripts written without spaces, such
    # as Thai or Chinese, match anywhere.
    if word.isascii():
        forms = (stem(word), *IRREGULAR.get(stem(word), ()))
        return re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, forms)) + ")", re.IGNORECASE)
    # A Thai word also matches its other spellings and its English equivalents.
    parts = [
        r"(?<!\w)" + re.escape(stem(form)) if form.isascii() else re.escape(form)
        for form in thai.forms(word)
    ]
    return re.compile("|".join(parts), re.IGNORECASE)


def split_words(words: list[str]) -> list[str]:
    """Search words, with runs of Thai (written without spaces) split into words."""
    split = [
        term
        for word in words
        for term in (thai.words_in(word) if thai.THAI_RUN.search(word) else [word])
    ]
    return split or words


def matches(item: dict[str, Any], words: list[str], about: str = "") -> bool:
    """Every word appears in the title or summary, or in the name of the item's feed
    ("insider" finds every item of insider-trades), ignoring case."""
    text = f"{item.get('title') or ''} {item.get('summary') or ''} {about}"
    return all(word_pattern(word).search(text) for word in words)


async def open_catalog(ctx: Context, catalog: str | None) -> tuple[str, dict[str, Any]]:
    """The catalog to read and where it is. When the default one cannot be reached, the
    offline copy `unlimited setup` saved is used instead, with a warning saying how old it is."""
    url = catalog_url(catalog)
    try:
        return url, await load_catalog(ctx, url)
    except FetchError as exc:
        copy = offline_copy() / "feeds.json"
        chosen = catalog or os.environ.get("UNLIMITEDPIPE_CATALOG")
        if chosen or not copy.is_file():
            raise
        from datetime import UTC, datetime

        saved = datetime.fromtimestamp(copy.stat().st_mtime, UTC).strftime("%Y-%m-%d %H:%M UTC")
        ctx.warn(f"{exc.message}; using the offline copy in {copy.parent} (saved {saved})")
        return str(copy), await load_catalog(ctx, str(copy))


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
                merged.setdefault(item_key(item), item)
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
    https://feeds.daemonfill.dev/ (75+ feeds on money, government, law, security,
    crypto, disasters, health, science and world news); use `--catalog` or
    `$UNLIMITEDPIPE_CATALOG` for another.
    """

    name = "search"
    examples = (
        "unlimited search bankruptcy",
        'unlimited search "cyber" --feed sec-company-events --feed security-news',
        "unlimited search --list-feeds              # the feeds and what they follow",
        "unlimited search --feed insider-trades     # a feed's latest items",
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

        if not self.words and not self.list_feeds and not self.feed:
            raise ValueError("search needs words to look for, a --feed, or --list-feeds")
        if self.limit < 1:
            raise ValueError("--limit must be at least 1")
        self.words = split_words(self.words)
        if self.since:
            self.since = parse_since(self.since)

    async def collect(self, ctx: Context):
        try:
            url, document = await open_catalog(ctx, self.catalog)
        except FetchError as exc:
            if (error := ctx.fail(exc, source=self.name, url=exc.url)) is not None:
                yield error
            return
        wanted = set(self.feed)
        names = [str(f.get("name")) for f in document.get("feeds", [])]
        if unknown := sorted(wanted - set(names)):
            from unlimitedpipe.component import suggest

            close = suggest(unknown[0], names)
            raise UsageError(
                f"the catalog has no feed named {unknown[0]!r}",
                hint=f"did you mean {close!r}?"
                if close
                else "list them: unlimited search --list-feeds",
            )
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
                        **({"health": feed["health"]} if feed.get("health") else {}),
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
                key=item_key(item),
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
        if not found:
            ctx.notice(self._nothing_found())

    def _nothing_found(self) -> str:
        feeds = ", ".join(self.feed)
        if not self.words:
            return (
                f"{feeds}: no items yet. Some feeds list only changes (a new listing, a new "
                "filing), and none has happened since the feed started; its health says when "
                f"it last ran: unlimited search --list-feeds --feed {self.feed[0]}"
            )
        where = f" in {feeds}" if feeds else ""
        return (
            f"Nothing{where} matches {' '.join(self.words)!r}. Every word must appear: try fewer "
            "or other words, add --since 2026-01 to search the archive too, or see what the "
            "feeds cover: unlimited search --list-feeds"
        )
