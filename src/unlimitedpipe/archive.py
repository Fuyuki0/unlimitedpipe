"""A catalog's archive: every item it ever listed, in one file per month.

`feeds.json` holds only the latest items of each feed. After every run, new items are also
appended to ``archive/YYYY-MM.jsonl`` (by the item's date, or when it was first seen), each
once, so `search --since` and `ask --since` can look back months. The files only grow at the
end, which keeps them cheap to store in Git and to serve. Months older than the last two are
kept compressed (``YYYY-MM.jsonl.gz``, about a third of the size), as the index names them;
a late item for such a month opens it again, and the next run closes it.
"""

from __future__ import annotations

import collections
import functools
import gzip
import hashlib
import html
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
DAYS = "days.json"  # items by day and feed in the months not yet compressed, for charts
DAYS_SCHEMA = "unlimitedpipe.archive-days/1"
_DAY = re.compile(r'"date":\s*"(\d{4}-\d\d-\d\d)')
_FEED_FIELD = re.compile(r'"feed":\s*"([^"]+)"')
WORDS_GZ = "words.json.gz"  # the whole word index in one file, for copies (mirror)
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
PACKED = ".jsonl.gz"
OPEN_MONTHS = 2  # the current month and the one before stay plain: items still arrive there


# Characters str.splitlines() ends a line at although JSON leaves them raw inside strings: a
# title with one would be cut in two by a reader that splits on them.
_LINE_BREAKS = {"\u2028": "\\u2028", "\u2029": "\\u2029", "\x85": "\\u0085"}


def json_line(item: dict[str, Any]) -> str:
    """An archive record as one line of JSON, safe for any line splitter."""
    text = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
    for raw, escaped in _LINE_BREAKS.items():
        text = text.replace(raw, escaped)
    return text


def lines_of(text: str) -> list[str]:
    """The lines of a month file: split at newlines only, never inside a record."""
    return text.split("\n")


_ENTITY = re.compile(r"&(?:#\d+|#x[0-9a-f]+|[a-z]+);", re.IGNORECASE)
# UTF-8 read as Windows-1252: a lead byte (Ã for é's C3) and one or two continuation bytes
_CONTINUATION = (
    "\u0080-\u00bf\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192\u02c6\u02dc"
    "\u2013\u2014\u2018-\u201e\u2020-\u2022\u2026\u2030\u2039\u203a\u20ac\u2122"
)
_MOJIBAKE = re.compile(f"[\u00c2-\u00df][{_CONTINUATION}]|[\u00e0-\u00ef][{_CONTINUATION}]{{2}}")
# quote marks some sources mangle past repair
_MANGLED = {"Â€œ": "“", "Â€\x9d": "”", "Â€™": "’", "Â€˜": "‘", "Â€Ï¿½": "’", "Ï¿½": "’"}


def _byte(char: str) -> bytes:
    try:
        return char.encode("cp1252")
    except UnicodeEncodeError:
        return char.encode("latin-1")


def _repaired(match: re.Match[str]) -> str:
    try:
        return b"".join(_byte(c) for c in match[0]).decode("utf-8")
    except UnicodeError:
        return match[0]


def clean_title(title: str) -> str:
    """A title as people read it: HTML entities a source left in ("Ha&#039;apai") decoded, and
    UTF-8 that a source decoded twice ("CROMATOGRAFÃ\x8dA") repaired, each sequence only when it
    decodes cleanly ("SÃO PAULO" stays)."""
    for _ in range(2):  # "&amp;amp;"
        if not _ENTITY.search(title):
            break
        title = html.unescape(title)
    for mangled, mark in _MANGLED.items():
        title = title.replace(mangled, mark)
    return _MOJIBAKE.sub(_repaired, title)


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


def _text(path: Path) -> str:
    """A month or feed file's text, compressed or not."""
    data = path.read_bytes()
    return (gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data).decode("utf-8")


def _month_name(path: Path) -> str:
    return path.name.split(".", 1)[0]


def _month_files(folder: Path) -> list[Path]:
    """Every month file, plain or compressed, oldest first."""
    found = [
        p
        for p in [*folder.glob("*.jsonl"), *folder.glob(f"*{PACKED}")]
        if _MONTH.match(_month_name(p))
    ]
    return sorted(found, key=_month_name)


def _pack_file(path: Path) -> None:
    packed = path.with_name(path.name + ".gz")
    packed.write_bytes(gzip.compress(path.read_bytes(), mtime=0))  # the same bytes every time
    path.unlink()


def _unpack_file(packed: Path) -> None:
    plain = packed.with_name(packed.name.removesuffix(".gz"))
    plain.write_bytes(gzip.decompress(packed.read_bytes()))
    packed.unlink()


def unpack_month(folder: Path, month: str) -> bool:
    """Open a compressed month (and its files by feed) to add to it; False when it is plain."""
    packed = folder / f"{month}{PACKED}"
    if not packed.exists():
        return False
    _unpack_file(packed)
    if (folder / month).is_dir():
        for part in (folder / month).glob(f"*{PACKED}"):
            _unpack_file(part)
    return True


def pack_old(folder: Path, now: str, keep: int = OPEN_MONTHS) -> int:
    """Compress the plain months before the last ``keep`` (and their files by feed); returns
    how many."""
    if not _DATE.match(now or ""):
        return 0
    year, month = int(now[:4]), int(now[5:7]) - (keep - 1)
    while month < 1:
        year, month = year - 1, month + 12
    first_open = f"{year:04d}-{month:02d}"
    packed = 0
    for path in sorted(folder.glob("*.jsonl")):
        name = path.stem
        if not _MONTH.match(name) or name >= first_open:
            continue
        _pack_file(path)
        if (folder / name).is_dir():
            for part in (folder / name).glob("*.jsonl"):
                _pack_file(part)
        packed += 1
    return packed


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
        unpack_month(folder, month)  # a late item for a closed month
        known = _known(path)
        new = []
        for item in entries:
            if isinstance(item.get("title"), str) and item["title"] != (
                title := clean_title(item["title"])
            ):
                item = {**item, "title": title}
            key = item_key(item)
            if key not in known:
                known.add(key)
                new.append({**item, "key": key, "seen": now})
        if new:
            folder.mkdir(parents=True, exist_ok=True)
            lines = [json_line(e) for e in new]
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
    packed = pack_old(folder, now) if folder.is_dir() else 0
    if added or packed:
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
    for line in lines_of(path.read_text(encoding="utf-8")):
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
    words = _WORD.findall(str(title or "").casefold())
    return {_stem(w) for w in words if len(w) > 2 and not w.isdigit()}


@functools.lru_cache(maxsize=1 << 18)
def _stem(word: str) -> str:
    """`search`'s stem, remembered: an archive's titles repeat the same words millions of
    times."""
    from unlimitedpipe.sources.search import stem

    return stem(word)


# Words in more months than this also get keys by feed ("reddit@sec-ipo-filings"), up to
# FEED_WORDS months: "reddit ipo" then reads the month of Reddit's IPO filing, not the many
# months of its insiders' trades.
RARE = 12
FEED_WORDS = 120


def write_words(folder: Path, fresh: list[tuple[str, dict[str, Any]]] | None = None) -> None:
    """Write the word index: the months each title word appears in, and for words that are not
    rare, the months it appears in each feed. With ``fresh`` (the items an append just added),
    the existing index by feed is updated with them; without it, or when that index is missing
    or from an older version, every month is read again."""
    by_feed = _load_by_feed(folder) if fresh is not None else None
    if by_feed is not None:
        for month, entry in fresh or []:
            feed = str(entry.get("feed") or "")
            for word in title_words(entry.get("title")):
                by_feed.setdefault(word, {}).setdefault(feed, set()).add(month)
    else:
        by_feed = {}
        for path in _month_files(folder):
            name = _month_name(path)
            pairs: set[tuple[str, str]] = set()  # each word and feed once a month
            for line in lines_of(_text(path)):
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(entry, dict):
                    continue
                feed = str(entry.get("feed") or "")
                pairs.update((word, feed) for word in title_words(entry.get("title")))
            for word, feed in pairs:
                by_feed.setdefault(word, {}).setdefault(feed, set()).add(name)
    table: dict[str, list[str]] = {}
    for word, feeds_of in by_feed.items():
        months = set().union(*feeds_of.values())
        table[word] = sorted(months)
        if RARE < len(months) <= FEED_WORDS:
            for feed, in_feed in feeds_of.items():
                if len(in_feed) < len(months):
                    table[f"{word}@{feed}"] = sorted(in_feed)
    table = dict(sorted(table.items()))
    # Readers fetch the small files; the one whole file is kept gzipped for copies (53 MB of
    # JSON is about 8 MB), and the plain one, past GitHub's 50 MB warning, is gone.
    _write_gzip_json(folder / WORDS_GZ, {"schema": WORDS_SCHEMA, "words": table})
    (folder / WORDS).unlink(missing_ok=True)
    feeds = {
        word: {feed: sorted(months) for feed, months in sorted(feeds_of.items())}
        for word, feeds_of in sorted(by_feed.items())
    }
    names = {shard_of(word) for word in table}
    _write_shards(folder / WORD_FILES, WORDS_SCHEMA, table, names)
    _write_shards(folder / BY_FEED, BY_FEED_SCHEMA, feeds, names, complete=True)
    (folder / f"{BY_FEED}.json").unlink(missing_ok=True)  # the one file of version 0.10.18


def _load_by_feed(folder: Path) -> dict[str, dict[str, set[str]]] | None:
    """The archive's index by feed, as word -> feed -> months, when it is complete (written by
    a version that keeps every word in it); else None."""
    shards = sorted((folder / BY_FEED).glob("*.json"))
    if not shards:
        return None
    found: dict[str, dict[str, set[str]]] = {}
    for shard in shards:
        try:
            content = json.loads(shard.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not (isinstance(content, dict) and content.get("complete")):
            return None
        for word, feeds_of in content.get("words", {}).items():
            found[word] = {feed: set(months) for feed, months in feeds_of.items()}
    return found


def shard_of(word: str) -> str:
    """The file of a split word index that holds a word: its first two letters or digits, any
    other character as "_" ("ja" for "japan", "x_" for "x-ray")."""
    head = word[:2].lower()
    if len(head) == 2 and head.isascii() and head.isalnum():
        return head  # most words: no pattern needed
    return re.sub(r"[^a-z0-9]", "_", head).ljust(2, "_")


def _write_json(path: Path, content: dict[str, Any]) -> None:
    text = json.dumps(content, ensure_ascii=False, separators=(",", ":")) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")


def _write_gzip_json(path: Path, content: dict[str, Any]) -> None:
    """Gzipped JSON, the same bytes for the same content (no time in the header), written only
    when it changed."""
    text = json.dumps(content, ensure_ascii=False, separators=(",", ":")) + "\n"
    data = gzip.compress(text.encode("utf-8"), compresslevel=9, mtime=0)
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)


def _write_shards(
    folder: Path, schema: str, table: dict[str, Any], names: set[str], complete: bool = False
) -> None:
    """A word index split into one file per shard name (a name without words gets an empty
    file, so every listed shard can be read); files of older names are removed. ``complete``
    marks an index that holds every word, so it can be updated instead of rebuilt."""
    shards: dict[str, dict[str, Any]] = {name: {} for name in names}
    for word, value in table.items():
        shards.setdefault(shard_of(word), {})[word] = value
    folder.mkdir(exist_ok=True)
    for old in folder.glob("*.json"):
        if old.stem not in shards:
            old.unlink()
    for name, words in shards.items():
        content: dict[str, Any] = {"schema": schema, "words": words}
        if complete:
            content["complete"] = True
        _write_json(folder / f"{name}.json", content)


def write_index(folder: Path) -> None:
    # a compressed month is closed: its counts stand while its file keeps its size
    try:
        before = {
            m["file"]: m
            for m in json.loads((folder / INDEX).read_text(encoding="utf-8")).get("months", [])
            if m.get("packed") and m.get("bytes")
        }
    except (OSError, ValueError, AttributeError, TypeError):
        before = {}
    months = []
    days: dict[str, dict[str, int]] = {}  # the open months' items by day and feed, for charts
    for path in reversed(_month_files(folder)):
        name = _month_name(path)
        size = path.stat().st_size
        if (known := before.get(path.name)) and known["bytes"] == size and known.get("feeds"):
            months.append(known)
            continue
        lines = [line for line in lines_of(_text(path)) if line.strip()]
        count = len(lines)
        if not path.name.endswith(PACKED):
            for line in lines:
                day, feed = _DAY.search(line), _FEED_FIELD.search(line)
                if day and feed:
                    by_feed = days.setdefault(day[1], {})
                    by_feed[feed[1]] = by_feed.get(feed[1], 0) + 1
        entry: dict[str, Any] = {"month": name, "file": path.name, "items": count}
        if path.name.endswith(PACKED):
            entry["packed"] = True  # its files by feed are compressed too
            entry["bytes"] = size
        split = folder / name
        if split.is_dir():
            entry["feeds"] = {
                _month_name(f): sum(1 for line in lines_of(_text(f)) if line.strip())
                for f in sorted([*split.glob("*.jsonl"), *split.glob(f"*{PACKED}")])
            }
        months.append(entry)
    index: dict[str, Any] = {"schema": SCHEMA, "months": months}
    if (folder / WORD_FILES).is_dir():
        index["shards"] = sorted(f.stem for f in (folder / WORD_FILES).glob("*.json"))
    (folder / INDEX).write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")
    _write_json(
        folder / DAYS,
        {
            "schema": DAYS_SCHEMA,
            "days": {d: dict(sorted(f.items())) for d, f in sorted(days.items())},
        },
    )


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
