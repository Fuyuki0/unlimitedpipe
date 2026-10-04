"""The ``search`` source: search a published feed catalog (its feeds.json) in one request."""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from unlimitedpipe import thai
from unlimitedpipe.archive import item_key, named_period
from unlimitedpipe.component import Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError, UsageError
from unlimitedpipe.event import Event, utcnow

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


# A catalog is static files made to be read by machines: its files are fetched without the
# pause between requests that scraping a site gets, a few at a time.
CATALOG_INTERVAL = 0.0
AT_ONCE = 4


async def read(ctx: Context, location: str) -> bytes:
    if _is_web(location):
        return (await ctx.http.get(location, interval=CATALOG_INTERVAL)).content
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

# What people ask for in words the sources do not use: "fed" for the Federal Reserve,
# "jobless" for unemployment. Each is matched as well as the word itself.
SAME = {
    "fed": ("federal reserve", "fomc"),
    "gdp": ("gross domestic product",),
    "jobless": ("unemployment",),
    "job": ("employment",),
    "inflation": ("consumer price",),
    "cpi": ("consumer price",),
    "ipo": ("go public", "initial public offering"),
    "purchase": ("bought", "buy"),
    "purchas": ("bought", "buy"),  # "purchases", as stem() cuts it
    "sale": ("sold", "sell"),
    "warning": ("alert", "advisory", "bulletin"),  # "tsunami warning?", "flood warning"
    "outage": ("issues with", "elevated error", "degraded", "disruption", "unavailable"),
    "quake": ("earthquake",),
    "sec": ("securities and exchange commission",),
    "fda": ("food and drug administration",),
    "doj": ("justice department", "department of justice"),
    "us": ("u.s.", "united states"),
    "uk": ("britain", "british", "united kingdom"),
    "eu": ("european union",),
    "un": ("united nations",),
    "ai": ("artificial intelligence",),
    "stock": ("share",),
    "flaw": ("vulnerabilit",),  # "cisco critical flaws": the sources say vulnerability
    "flaws": ("vulnerabilit",),  # stem() keeps words ending in -ws whole, as "news"
    "bug": ("vulnerabilit",),
    "sign": ("became public law",),  # "laws signed this month"
    "congress": ("public law",),  # "laws congress passed"
    "sanction": ("designation",),  # OFAC's "Counter Terrorism Designations"
    "xai": ("x.ai",),
    # currency codes, as the rate feeds name the currencies ("US dollar: 33.595 baht")
    "usd": ("us dollar", "dollar"),
    "thb": ("baht",),
    "jpy": ("yen",),
    "cny": ("yuan",),
    "inr": ("rupee",),
    "eur": ("euro",),
    # four-letter words match only their own endings, so their long forms are named here
    "tech": ("technolog",),
    "spac": ("blank check", "acquisition corp"),
}
# US agencies by the names the Federal Register gives them ("Environmental Protection Agency:
# ..."). Acronyms that are also common words (doe, dot, va) are left out; the rest match whole
# words only ("fema" is not "female", "nasa" not "nasal").
AGENCIES = {
    "epa": ("environmental protection agency",),
    "hhs": ("health and human services",),
    "usda": ("agriculture department", "department of agriculture"),
    "dod": ("defense department", "department of defense", "pentagon"),
    "pentagon": ("defense department", "department of defense"),
    "dhs": ("homeland security",),
    "hud": ("housing and urban development",),
    "dol": ("labor department", "department of labor"),
    "opm": ("personnel management",),
    "sba": ("small business administration",),
    "ssa": ("social security administration",),
    "cftc": ("commodity futures trading commission",),
    "nrc": ("nuclear regulatory commission",),
    "gsa": ("general services administration",),
    "fhfa": ("federal housing finance agency",),
    "cfpb": ("consumer financial protection bureau",),
    "nasa": ("national aeronautics and space administration",),
    "nlrb": ("national labor relations board",),
    "eeoc": ("equal employment opportunity commission",),
    "usaid": ("agency for international development",),
    "ftc": ("federal trade commission",),
    "fdic": ("federal deposit insurance corporation",),
    "ncua": ("national credit union administration",),
    "faa": ("federal aviation administration",),
    "irs": ("internal revenue service",),
    "osha": ("occupational safety and health administration",),
    "fcc": ("federal communications commission",),
    "fema": ("federal emergency management agency",),
    "nhtsa": ("national highway traffic safety administration",),
    "cdc": ("centers for disease control",),
    "nih": ("national institutes of health",),
}
SAME.update(AGENCIES)
WHOLE_WORDS = frozenset(AGENCIES)


@lru_cache(maxsize=256)
def word_pattern(word: str) -> re.Pattern[str]:
    # A word matches at the start of a word, in any of its forms ("hacks" finds "hack" and
    # "hacked", not "Thackeray"; "buys" finds "bought"). Scripts written without spaces, such
    # as Thai or Chinese, match anywhere.
    if word.isascii():
        base = stem(word)
        same = SAME.get(base) or SAME.get(word.casefold()) or ()
        forms = (base, *IRREGULAR.get(base, ()), *same)
        return re.compile("|".join(map(_start, forms)), re.IGNORECASE)
    # A Thai word also matches its other spellings and its English equivalents.
    parts = [_start(stem(form)) if form.isascii() else re.escape(form) for form in thai.forms(word)]
    return re.compile("|".join(parts), re.IGNORECASE)


@lru_cache(maxsize=256)
def word_forms(word: str) -> tuple[str, ...]:
    """Text a match of ``word_pattern(word)`` always contains, lowercased: a quick check that
    spares the pattern most texts."""
    if word.isascii():
        base = stem(word)
        same = SAME.get(base) or SAME.get(word.casefold()) or ()
        return tuple(f.lower() for f in (base, *IRREGULAR.get(base, ()), *same))
    return tuple((stem(form) if form.isascii() else form).lower() for form in thai.forms(word))


def lowered(text: str) -> str:
    """``text`` as ``word_forms`` are compared with it ("İstanbul" as "istanbul")."""
    return text.lower().replace("i\u0307", "i")


def matches_in(texts: list[str], low: list[str], word: str) -> set[int]:
    """The positions of the texts that ``word`` matches."""
    forms, pattern = word_forms(word), word_pattern(word)
    return {
        n
        for n, (text, quick) in enumerate(zip(texts, low, strict=True))
        if any(form in quick for form in forms) and pattern.search(text)
    }


def _start(form: str) -> str:
    """A word's start: words of five letters or more match any ending ("vulnerabilit" finds
    "vulnerability"), four-letter words only the endings of their own forms ("hack" finds
    "hacker" and "hacked"; "noto" is not "notorious", "gold" not "goldman"), and words of three
    letters or fewer and acronyms only their plural and verb endings ("sec" is not "security",
    "ai" not "aid", "us" not "user")."""
    if len(form) <= 3 or form in WHOLE_WORDS:
        return r"(?<!\w)" + re.escape(form) + r"(?:s|es|'s|ed|ing)?(?!\w)"
    if form == "hack":  # "hacker", not "Hacker News"
        return r"(?<!\w)hack(?:s|'s|ed|ing|ers?)?(?!\w)(?<!hacker(?= ?news\b))"
    if len(form) == 4:
        return r"(?<!\w)" + re.escape(form) + r"(?:s|es|'s|e?d|ing|ers?|i?ans?|ese|ish)?(?!\w)"
    return r"(?<!\w)" + re.escape(form)


STORY_UPDATES = 2  # updates of one story that search and ask show, newest first


def corrected(
    words: list[str], document: dict[str, Any], known: set[str] | frozenset[str] = frozenset()
) -> tuple[list[str], dict[str, str]]:
    """The words with typos fixed ("bitcion" -> "bitcoin"): a word of five letters or more
    that no item has, and that is not in ``known`` (the archive's words, stemmed), is replaced
    by the most common word of the catalog one letter away (two for long words). Returns the
    words and what was replaced."""
    names = " ".join(str(f.get("name", "")).replace("-", " ") for f in document.get("feeds", []))
    text = "\n".join(
        f"{i.get('title') or ''} {i.get('summary') or ''}" for i in document.get("items", [])
    )
    text += "\n" + names
    vocabulary: Counter[str] | None = None
    fixed: dict[str, str] = {}
    out = []
    for word in words:
        if (
            not (word.isascii() and word.isalpha() and len(word) >= 5)
            or stem(word) in known
            or word_pattern(word).search(text)
        ):
            out.append(word)
            continue
        if vocabulary is None:
            vocabulary = Counter(re.findall(r"[a-z]{4,}", text.casefold()))
        allowed = 1 if len(word) < 9 else 2
        near = [
            (count, known)
            for known, count in vocabulary.items()
            if abs(len(known) - len(word)) <= allowed and _distance(word, known, allowed)
        ]
        if near:
            fixed[word] = max(near)[1]
            out.append(fixed[word])
        else:
            out.append(word)
    return out, fixed


def _distance(a: str, b: str, limit: int) -> bool:
    """Whether a and b are at most `limit` edits apart (insert, delete, replace, swap)."""
    if a == b:
        return False  # the same word is not a correction
    previous2: list[int] | None = None
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            cost = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            if previous2 is not None and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cost = min(cost, previous2[j - 2] + 1)
            current.append(cost)
        if min(current) > limit:
            return False
        previous2, previous = previous, current
    return previous[-1] <= limit


def story(item: dict[str, Any]) -> str:
    """What makes items updates of one story: their feed, and the title without its numbers
    ("Hurricane Polo, advisory 26/2357Z", "USDT supply +$199.8M in a day, now $183.9B")."""
    title = re.sub(r"[\d.,:/%$#+-]+", " ", str(item.get("title") or "")).casefold()
    return f"{item.get('feed')}|{' '.join(title.split())}"


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
    return await with_live(ctx, document)


LIVE_TIMEOUT = 3.0  # a live copy that is slow to answer is skipped, not waited for


async def with_live(ctx: Context, document: dict[str, Any]) -> dict[str, Any]:
    """The catalog with the newer items of its live copy merged in (a server polling its
    time-sensitive feeds every minute), when it names one that answers quickly; as it is
    otherwise."""
    live = document.get("live")
    if not (isinstance(live, str) and _is_web(live)):
        return document
    try:
        response = await ctx.http.get(
            live, timeout=LIVE_TIMEOUT, retries=0, interval=CATALOG_INTERVAL, cache=False
        )
        items = json.loads(response.content).get("items") or []
    except (FetchError, ValueError, AttributeError):
        return document
    merged = {item_key(i): i for i in document.get("items", []) if isinstance(i, dict)}
    for item in items:
        if isinstance(item, dict):
            merged.setdefault(item_key(item), item)
    ordered = sorted(merged.values(), key=lambda i: str(i.get("date") or ""), reverse=True)
    return {**document, "items": ordered}


async def items_since(
    ctx: Context,
    url: str,
    document: dict[str, Any],
    since: str,
    until: str | None = None,
    words: list[str] | None = None,
) -> list[dict[str, Any]]:
    """The catalog's latest items plus its archive from ``since`` (a month or a day) on, and
    up to the month ``until`` when given, each once, newest first. With ``words``, only the
    feeds that can hold them are read, where the archive is split by feed."""

    merged = {item_key(i): i for i in document.get("items", [])}
    index_url = join(url, document.get("archive") or "archive/index.json")
    try:
        index = json.loads(await read(ctx, index_url))
    except (FetchError, ValueError):
        ctx.warn(f"{url} has no archive; searching its latest items only")
        index = {"months": []}
    months = [
        month
        for month in index.get("months", [])
        if not (
            str(month.get("month", "")) < since[:7]
            or (until and str(month.get("month", "")) > until)
        )
    ]
    wanted = await _wanted_feeds(ctx, index_url, index, document, words or [], months)
    for item in await _read_months(ctx, index_url, months, wanted):
        merged.setdefault(item_key(item), item)
    items = [
        i
        for i in merged.values()
        if (when := str(i.get("date") or i.get("seen") or ""))[: len(since)] >= since
        and not (until and when[:7] > until)
    ]
    items.sort(key=lambda i: str(i.get("date") or ""), reverse=True)
    return items


def _forms(word: str) -> set[str]:
    """The index words a question word stands for: its stem and those of its synonyms."""
    return {stem(word)} | {
        stem(part)
        for phrase in SAME.get(stem(word), SAME.get(word.casefold(), ()))
        for part in phrase.split()
        if len(part) > 2
    }


def _named_feeds(document: dict[str, Any], words: list[str]) -> set[str]:
    """Feeds a question names by a word of their name or description ("earthquakes", "ipo",
    "hack", "close" for daily closes): their items may have the word only in a summary."""
    return {
        str(f.get("name"))
        for f in document.get("feeds", [])
        if any(
            word_pattern(w).search(
                f"{str(f.get('name', '')).replace('-', ' ')} {f.get('description') or ''}"
            )
            for w in words
        )
    }


async def word_table(
    ctx: Context, index_url: str, index: Any, name: str, forms: set[str]
) -> dict[str, Any] | None:
    """The entries of one of the archive's word indexes (``name``: words, words-by-feed) that
    can start with ``forms``: from its small files by first letters where the archive index
    lists them, else from its one whole file; None when there is neither."""
    from unlimitedpipe.archive import shard_of

    shards = index.get("shards") if isinstance(index, dict) else None
    if not isinstance(shards, list):
        try:
            content = await read(ctx, join(index_url, f"{name}.json"))
            return json.loads(content).get("words") or {}
        except (FetchError, ValueError, AttributeError):
            return None
    wanted = sorted({shard_of(form) for form in forms if form} & set(map(str, shards)))
    try:
        contents = await asyncio.gather(
            *(read(ctx, join(index_url, f"{name}/{shard}.json")) for shard in wanted)
        )
        table: dict[str, Any] = {}
        for content in contents:
            table.update(json.loads(content).get("words") or {})
    except (FetchError, ValueError, AttributeError, TypeError):
        return None
    return table


async def _wanted_feeds(
    ctx: Context,
    index_url: str,
    index: Any,
    document: dict[str, Any],
    words: list[str],
    months: list[dict[str, Any]],
) -> dict[str, set[str]] | None:
    """For each month, the feeds that can hold the words (from the archive's words-by-feed
    index), and the feeds the words name; None to read whole months (no split, no index, or
    no word that narrows anything down)."""
    from unlimitedpipe.archive import BY_FEED

    if not words or not any("feeds" in m for m in months):
        return None
    forms = {form for word in words for form in _forms(word) if len(form) >= 2}
    table = await word_table(ctx, index_url, index, BY_FEED, forms)
    if table is None:
        return None
    wanted: dict[str, set[str]] = {}
    narrowed = False
    for key, word_feeds in table.items():
        if not any(key.startswith(form) for form in forms):
            continue
        narrowed = True
        for feed, feed_months in word_feeds.items():
            for month in feed_months:
                wanted.setdefault(month, set()).add(feed)
    if not narrowed:
        return None
    named = _named_feeds(document, words)
    return {
        str(m["month"]): (wanted.get(str(m["month"]), set()) | named) & set(m.get("feeds") or {})
        for m in months
    }


async def _read_months(
    ctx: Context,
    index_url: str,
    months: list[dict[str, Any]],
    wanted: dict[str, set[str]] | None,
) -> list[dict[str, Any]]:
    """The items of some archive months: of the wanted feeds only where the archive is split
    by feed, else (or when a feed file cannot be read) the whole month."""
    items: list[dict[str, Any]] = []
    missing: list[str] = []
    for month in months:
        name = str(month.get("month"))
        split = month.get("feeds")
        # a split that does not add up to the month (being written, or half done) is not used
        whole = not isinstance(split, dict) or sum(split.values()) != month.get("items")
        feeds = None if wanted is None or whole else wanted.get(name, set())
        if feeds is not None:
            try:
                ext = ".jsonl.gz" if month.get("packed") else ".jsonl"
                files = [join(index_url, f"{name}/{feed}{ext}") for feed in sorted(feeds)]
                items += await _read_items(ctx, files)
                continue
            except FetchError:
                pass  # read the whole month instead
        try:
            items += await _read_items(ctx, [join(index_url, str(month.get("file")))])
        except FetchError:
            missing.append(name)  # a copy made with fewer months, or one not reachable now
    if missing:
        span = missing[0] if len(missing) == 1 else f"{min(missing)} to {max(missing)}"
        ctx.warn(
            f"{len(missing)} archive month(s) could not be read ({span}) and are left out; "
            "for an offline copy: unlimited mirror --since " + min(missing)
        )
    return items


async def _read_items(ctx: Context, files: list[str]) -> list[dict[str, Any]]:
    """The items of some archive files, fetched a few at a time."""
    gate = asyncio.Semaphore(AT_ONCE)

    async def fetch(location: str) -> bytes:
        async with gate:
            return await read(ctx, location)

    items = []
    for content in await asyncio.gather(*(fetch(f) for f in files)):
        if content[:2] == b"\x1f\x8b":  # a compressed month (a server may have opened it)
            content = gzip.decompress(content)
        for line in content.decode("utf-8", errors="replace").split("\n"):
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                items.append(item)
    return items


async def archive_words(
    ctx: Context, url: str, document: dict[str, Any], words: list[str]
) -> set[str]:
    """Which of the words (stemmed) the archive's titles have, from its word index; empty
    without one."""
    from unlimitedpipe.archive import WORD_FILES

    index_url = join(url, document.get("archive") or "archive/index.json")
    try:
        index = json.loads(await read(ctx, index_url))
    except (FetchError, ValueError):
        index = None
    forms = {stem(word) for word in words}
    return forms & set(await word_table(ctx, index_url, index, WORD_FILES, forms) or {})


RARE_MONTHS = 12  # a word in more months than this narrows nothing down
MOST_MONTHS = 12


async def items_by_words(
    ctx: Context, url: str, document: dict[str, Any], words: list[str]
) -> list[dict[str, Any]]:
    """Archive items for a question that names no date ("ronin hack", "reddit ipo filing"),
    from the archive's word index: the months its rarest word appears in, those where more of
    its other words appear too first ("reddit" with "public", as "ipo" is said), then the
    newest; at most twelve. Empty when the catalog has no index or no word is rare enough."""
    from unlimitedpipe.archive import WORD_FILES

    index_url = join(url, document.get("archive") or "archive/index.json")
    try:
        index = json.loads(await read(ctx, index_url))
    except (FetchError, ValueError):
        index = None
    all_forms = {form for word in words for form in _forms(word)}
    table = await word_table(ctx, index_url, index, WORD_FILES, all_forms)
    if table is None:
        return []
    per_word = []
    for word in words:
        forms = _forms(word)
        months = {m for form in forms if isinstance(table.get(form), list) for m in table[form]}
        if months:
            per_word.append(months)
    # A word naming a feed ("ipo" for sec-ipo-filings, "hack" for crypto-hacks) narrows the
    # others to the months they appear in that feed ("reddit@sec-ipo-filings").
    named = [
        str(f.get("name"))
        for f in document.get("feeds", [])
        if any(word_pattern(w).search(str(f.get("name", "")).replace("-", " ")) for w in words)
    ]
    in_feed = [
        set(table[key])
        for word in words
        for feed in named
        if isinstance(table.get(key := f"{stem(word)}@{feed}"), list)
    ]
    anchors = in_feed + [months for months in per_word if len(months) <= RARE_MONTHS * 5]
    if not anchors and len(per_word) >= 2 and len(per_word) == len(words):
        # no rare word ("affordable care act", "berkshire hathaway 13f"): the months where
        # every word appears, the newest first
        together = set.intersection(*per_word)
        if together:
            anchors = [together]
    if not anchors:
        return []
    anchor = min(anchors, key=len)
    ranked = sorted(
        anchor, key=lambda m: (sum(m in months for months in per_word), m), reverse=True
    )
    chosen = set(ranked[:MOST_MONTHS])
    if not isinstance(index, dict):
        whole = [{"month": m, "file": f"{m}.jsonl"} for m in sorted(chosen)]
        return await _read_months(ctx, index_url, whole, None)
    months = [m for m in index.get("months", []) if str(m.get("month")) in chosen]
    wanted = await _wanted_feeds(ctx, index_url, index, document, words, months)
    return await _read_months(ctx, index_url, months, wanted)


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
    every_update: bool = opt(
        "Show every update of a story (default: the newest two, as of a storm or a price)",
        default=False,
    )
    list_feeds: bool = opt("List the catalog's feeds instead of searching", default=False)
    exact: bool = opt(
        "Only items with every word: no items found by meaning, no hint when none matches "
        "(as `follow` searches)",
        default=False,
    )

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
        # "nvidia earnings" quoted is two words, each of which must appear, as unquoted
        asked = [term for word in self.words for term in word.split()]
        named = None if self.since else named_period(" ".join(asked), utcnow())
        if self.since or named:
            # "earthquake 2023": that period's items from the archive, not the latest ones
            first, last = (named[0], named[1]) if named else (str(self.since), None)
            if named:
                asked = [w for w in asked if w.casefold().rstrip(".") not in named[2]]
            try:
                items = await items_since(
                    ctx, url, document, first, last, words=asked if named else None
                )
            except FetchError as exc:
                if (error := ctx.fail(exc, source=self.name, url=url)) is not None:
                    yield error
                return
        words, fixed = corrected(asked, {**document, "items": items})
        if fixed and not (self.since or named):
            # "haiyan" is not a typo when the archive has it
            try:
                known = await archive_words(ctx, url, document, list(fixed))
            except FetchError:
                known = set()
            if known:
                words, fixed = corrected(asked, {**document, "items": items}, known)
        for typo, word in fixed.items():
            ctx.notice(f"search: no item has {typo!r}; searched for {word!r}")
        found = 0
        for event in self._matching(url, items, words, wanted, about):
            yield event
            found += 1
            if found >= self.limit:
                return
        if not found and words and not (self.since or named):
            # "hurricane katrina": no latest item has the words, so the months of the archive
            # its word index has them in: items with every word in the title first, those of a
            # feed a word names next (the storm itself before the news about it), then the newest
            try:
                past = await items_by_words(ctx, url, document, split_words(words))
            except FetchError:
                past = []
            past.sort(
                key=lambda item: (
                    matches({"title": item.get("title")}, words),
                    any(word_pattern(w).search(about.get(item.get("feed"), "")) for w in words),
                    str(item.get("date") or ""),
                ),
                reverse=True,
            )
            for event in self._matching(url, past, words, wanted, about):
                if not found:
                    ctx.notice("search: no latest item has these words; these are from the archive")
                yield event
                found += 1
                if found >= self.limit:
                    return
        if not found and words and not wanted and not self.exact:
            async for event in self._by_meaning(ctx, url, items):
                found += 1
                yield event
        if not found and not self.exact:
            ctx.notice(self._nothing_found())

    def _matching(
        self,
        url: str,
        items: list[dict[str, Any]],
        words: list[str],
        wanted: set[str],
        about: dict[Any, str],
    ):
        """The items with every word, as events: a story's first few updates only."""
        updates: Counter[str] = Counter()
        for item in items:
            if wanted and item.get("feed") not in wanted:
                continue
            if not matches(item, words, about.get(item.get("feed"), "")):
                continue
            if not self.every_update:
                updates[story(item)] += 1
                if updates[story(item)] > STORY_UPDATES:
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

    async def _by_meaning(self, ctx: Context, url: str, items: list[dict[str, Any]]):
        """Items alike the words in meaning, with a local embedding model, when none has them."""
        import httpx

        from unlimitedpipe import meaning
        from unlimitedpipe.sources.ask import OLLAMA, _ollama_models

        host = os.environ.get("OLLAMA_HOST", OLLAMA)
        host = host if host.startswith("http") else f"http://{host}"
        async with httpx.AsyncClient(timeout=30, transport=ctx.transport) as client:
            model = meaning.pick(await _ollama_models(client, host) or [])
            if model is None or not items:
                return
            try:
                found = await meaning.nearest(
                    ctx, client, host, model, " ".join(self.words), items, self.limit
                )
            except (httpx.HTTPError, ValueError, KeyError):
                return
        if found:
            ctx.notice(f"search: no item has these words; {len(found)} match their meaning")
        for _, item in found:
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
                    "found_by": "meaning",
                },
                metadata={"catalog": url},
            )

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
