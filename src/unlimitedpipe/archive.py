"""A catalog's archive: every item it ever listed, in one file per month.

`feeds.json` holds only the latest items of each feed. After every run, new items are also
appended to ``archive/YYYY-MM.jsonl`` (by the item's date, or when it was first seen), each
once, so `search --since` and `ask --since` can look back months. The files only grow at the
end, which keeps them cheap to store in Git and to serve.
"""

from __future__ import annotations

import collections
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ARCHIVE_DIR = "archive"
INDEX = "index.json"
SCHEMA = "unlimitedpipe.archive/1"
# Which months each title word appears in, so a question without a date ("ronin hack") reads
# only the months that can answer it. Also split by the first two letters of the words
# (words/ja.json), so a question reads a few small files rather than the whole index; the
# index lists those files as "shards".
WORDS = "words.json"
WORD_FILES = "words"
WORDS_SCHEMA = "unlimitedpipe.archive-words/1"
# Each month also split by feed (archive/2024-02/sec-ipo-filings.jsonl), with the feeds each word
# appears in (words-by-feed/ja.json), so a question reads the feeds that can answer it rather
# than every item of the month. The month files stay, for readers that do not know the split.
BY_FEED = "words-by-feed"
BY_FEED_SCHEMA = "unlimitedpipe.archive-words-by-feed/1"
_FEED = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_WORD = re.compile(r"[^\W_][\w'-]*")
_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_DATE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])(-\d{2})?")


def item_key(item: dict[str, Any]) -> str:
    """The identity of an item across runs: its feed, link and title. Both, because some feeds
    link every item to the same page (a list of hacks, a weekly volcano report), and the same
    story can arrive twice from two sources with a title that differs only in case."""
    title = " ".join(str(item.get("title") or "").split()).casefold()
    basis = f"{item.get('feed')}\n{item.get('link') or ''}\n{title}"
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def month_of(item: dict[str, Any], now: str) -> str:
    date = str(item.get("date") or "")
    return date[:7] if _DATE.match(date) else now[:7]


def _known(path: Path) -> set[str]:
    keys = set()
    try:
        with path.open(encoding="utf-8") as lines:
            for line in lines:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict):
                    keys.add(item_key(entry))  # not the stored key: older ones were link-only
    except OSError:
        pass
    return keys


def append(site: Path, items: list[dict[str, Any]], now: str) -> dict[str, int]:
    """Add the items the archive does not have yet; returns how many were added per month."""
    folder = site / ARCHIVE_DIR
    fresh: list[tuple[str, dict[str, Any]]] = []
    by_month: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_month.setdefault(month_of(item, now), []).append(item)
    added: dict[str, int] = {}
    for month, entries in sorted(by_month.items()):
        path = folder / f"{month}.jsonl"
        known = _known(path)
        new = []
        for item in entries:
            key = item_key(item)
            if key not in known:
                known.add(key)
                new.append({**item, "key": key, "seen": now})
        if new:
            folder.mkdir(parents=True, exist_ok=True)
            lines = [json.dumps(e, ensure_ascii=False, separators=(",", ":")) for e in new]
            with path.open("a", encoding="utf-8") as out:
                out.writelines(line + "\n" for line in lines)
            for entry, line in zip(new, lines, strict=True):
                if feed_file := _feed_path(folder, month, entry.get("feed")):
                    feed_file.parent.mkdir(exist_ok=True)
                    with feed_file.open("a", encoding="utf-8") as out:
                        out.write(line + "\n")
            added[month] = len(new)
            fresh.extend((month, entry) for entry in new)
            _heal(folder, month)
    if added:
        write_words(folder, fresh)
        write_index(folder)
    return added


def _feed_path(folder: Path, month: str, feed: Any) -> Path | None:
    return folder / month / f"{feed}.jsonl" if isinstance(feed, str) and _FEED.match(feed) else None


def _lines(path: Path) -> int:
    with path.open(encoding="utf-8") as lines:
        return sum(1 for line in lines if line.strip())


def _heal(folder: Path, month: str) -> None:
    """Split a month again when its feed files do not add up to it (a version that did not
    split appended to it, or a run stopped half-way)."""
    split = folder / month
    if split.is_dir() and sum(_lines(f) for f in split.glob("*.jsonl")) != _lines(
        folder / f"{month}.jsonl"
    ):
        _split_month(folder, folder / f"{month}.jsonl")


def _split_month(folder: Path, path: Path) -> int:
    groups: dict[Path, list[str]] = collections.defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        feed_file = (
            _feed_path(folder, path.stem, entry.get("feed")) if isinstance(entry, dict) else None
        )
        if feed_file:
            groups[feed_file].append(line)
    month_folder = folder / path.stem
    if month_folder.is_dir():
        for old in month_folder.glob("*.jsonl"):
            if old not in groups:
                old.unlink()
    for feed_file, lines in groups.items():
        feed_file.parent.mkdir(exist_ok=True)
        feed_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(groups)


def split_by_feed(folder: Path) -> int:
    """Write every month's per-feed files anew from the month files; returns how many."""
    written = sum(
        _split_month(folder, path)
        for path in sorted(folder.glob("*.jsonl"))
        if _MONTH.match(path.stem)
    )
    write_index(folder)
    return written


def title_words(title: Any) -> set[str]:
    """The searchable words of a title, as `search` stems them (no numbers, no short words)."""
    from unlimitedpipe.sources.search import stem

    words = _WORD.findall(str(title or "").casefold())
    return {stem(w) for w in words if len(w) > 2 and not w.isdigit()}


# Words in more months than this also get keys by feed ("reddit@sec-ipo-filings"), up to
# FEED_WORDS months: "reddit ipo" then reads the month of Reddit's IPO filing, not the many
# months of its insiders' trades.
RARE = 12
FEED_WORDS = 120


def write_words(folder: Path, fresh: list[tuple[str, dict[str, Any]]] | None = None) -> None:
    """Write the word index from every month (``fresh``, the items just added, is in them):
    the months each title word appears in, and for words that are not rare, the months it
    appears in each feed."""
    del fresh  # a whole rebuild takes a few seconds and keeps the keys by feed exact
    words: dict[str, set[str]] = collections.defaultdict(set)
    by_feed: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    for month in sorted(folder.glob("*.jsonl")):
        if not _MONTH.match(month.stem):
            continue
        for line in month.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            feed = str(entry.get("feed") or "")
            for word in title_words(entry.get("title")):
                words[word].add(month.stem)
                by_feed[(word, feed)].add(month.stem)
    table = {w: sorted(m) for w, m in words.items()}
    for (word, feed), months in by_feed.items():
        if RARE < len(words[word]) <= FEED_WORDS and len(months) < len(words[word]):
            table[f"{word}@{feed}"] = sorted(months)
    table = dict(sorted(table.items()))
    _write_json(folder / WORDS, {"schema": WORDS_SCHEMA, "words": table})
    from unlimitedpipe.operators.extract import STOPWORDS

    stop = {w.casefold() for w in STOPWORDS}  # a search never asks for them
    feeds: dict[str, dict[str, list[str]]] = collections.defaultdict(dict)
    for (word, feed), months in sorted(by_feed.items()):
        if word not in stop:
            feeds[word][feed] = sorted(months)
    names = {shard_of(word) for word in table}
    _write_shards(folder / WORD_FILES, WORDS_SCHEMA, table, names)
    _write_shards(folder / BY_FEED, BY_FEED_SCHEMA, feeds, names)
    (folder / f"{BY_FEED}.json").unlink(missing_ok=True)  # the one file of version 0.10.18


def shard_of(word: str) -> str:
    """The file of a split word index that holds a word: its first two letters or digits, any
    other character as "_" ("ja" for "japan", "x_" for "x-ray")."""
    return re.sub(r"[^a-z0-9]", "_", word.lower()[:2]).ljust(2, "_")


def _write_json(path: Path, content: dict[str, Any]) -> None:
    text = json.dumps(content, ensure_ascii=False, separators=(",", ":")) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")


def _write_shards(folder: Path, schema: str, table: dict[str, Any], names: set[str]) -> None:
    """A word index split into one file per shard name (a name without words gets an empty
    file, so every listed shard can be read); files of older names are removed."""
    shards: dict[str, dict[str, Any]] = {name: {} for name in names}
    for word, value in table.items():
        shards.setdefault(shard_of(word), {})[word] = value
    folder.mkdir(exist_ok=True)
    for old in folder.glob("*.json"):
        if old.stem not in shards:
            old.unlink()
    for name, words in shards.items():
        _write_json(folder / f"{name}.json", {"schema": schema, "words": words})


def write_index(folder: Path) -> None:
    months = []
    for path in sorted(folder.glob("*.jsonl"), reverse=True):
        if _MONTH.match(path.stem):
            with path.open(encoding="utf-8") as lines:
                count = sum(1 for line in lines if line.strip())
            entry: dict[str, Any] = {"month": path.stem, "file": path.name, "items": count}
            split = folder / path.stem
            if split.is_dir():
                entry["feeds"] = {
                    f.stem: sum(1 for line in f.open(encoding="utf-8") if line.strip())
                    for f in sorted(split.glob("*.jsonl"))
                }
            months.append(entry)
    index: dict[str, Any] = {"schema": SCHEMA, "months": months}
    if (folder / WORD_FILES).is_dir():
        index["shards"] = sorted(f.stem for f in (folder / WORD_FILES).glob("*.json"))
    (folder / INDEX).write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")


MONTH_NAMES = {
    name: number
    for number, names in enumerate(
        (
            "january jan",
            "february feb",
            "march mar",
            "april apr",
            "may",
            "june jun",
            "july jul",
            "august aug",
            "september sep sept",
            "october oct",
            "november nov",
            "december dec",
        ),
        1,
    )
    for name in names.split()
}
_PERIOD = re.compile(
    r"\b(?:(?P<month>" + "|".join(sorted(MONTH_NAMES, key=len, reverse=True)) + r")\.?\s+)?"
    r"(?P<year>(?:19|20)\d\d)(?:-(?P<iso>0[1-9]|1[0-2]))?\b"
    r"|\b(?P<relative>last|this)\s+year\b"
    r"|\b(?P<ever>ever|of all time|all[- ]time)\b",
    re.IGNORECASE,
)
EVER = "1800-01"  # the first month of "biggest earthquake ever": all of the archive


def named_period(text: str, today: str) -> tuple[str, str, list[str]] | None:
    """The months a question names, as the first and last (YYYY-MM), and the words that named
    them: "earthquakes in 2023", "rules in march 2025", "2025-03", "last year", and all of it
    for "ever" (from EVER). None when it names no period, or one after ``today`` (an ISO
    date)."""
    match = _PERIOD.search(text)
    if match is None:
        return None
    this_year = int(today[:4])
    if match["ever"]:
        return EVER, today[:7], [w.casefold() for w in match[0].split()]
    if match["relative"]:
        year = this_year - (match["relative"].casefold() == "last")
        return f"{year}-01", f"{year}-12", [w.casefold() for w in match[0].split()]
    year = int(match["year"])
    if year > this_year:
        return None  # "python 2027 roadmap" is not in the past
    said = [match["year"] if not match["iso"] else f"{year}-{match['iso']}"]
    if match["iso"]:
        month = f"{year}-{match['iso']}"
        return month, month, said
    if match["month"]:
        month = f"{year}-{MONTH_NAMES[match['month'].casefold()]:02d}"
        return month, month, [match["month"].casefold(), *said]
    return f"{year}-01", f"{year}-12", said


def parse_since(value: str) -> str:
    """``2010`` -> ``2010-01``; ``2026-08`` or ``2026-08-15`` -> the same, checked."""
    value = value.strip()
    if re.fullmatch(r"(1[89]|20)\d\d", value):
        return f"{value}-01"
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?", value):
        raise ValueError(
            f"--since takes a year, a month or a day, like 2010, 2026-08 or 2026-08-15, "
            f"not {value!r}"
        )
    return value
