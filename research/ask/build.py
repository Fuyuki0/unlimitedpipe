"""Training and test examples for `unlimited ask`, built from the catalog.

Every example is the exact prompt `ask` sends (same wording, same search, same number of
sources, same time window) and an answer written from the sources by a template, so it is
correct by construction:

- lookup: a question about one item, answered from it with its citation;
- listing: "any insider trades this week?" or "what's new with Bitget?", answered with every
  matching source up to five, each cited;
- refusal: sources that miss the question's key word, answered by saying so;
- each asked in English and Thai, formally and the way people type ("bitget hack?").

Build 3 (2026-09-27) adds listings over many days and topics (build 2 had 56), casual
questions, and 10 sources as `ask` gives by default (build 2 always had 5). Build 4 is English
first (Thai 15%), and answers a broad question ("openai news": three or more sources match as
well as the item asked about) with a list, where build 3 picked one item. A search that
works like `ask`'s own (`World.rank`, checked against it on every run) makes it fast.

Items are split once: those in `test.jsonl` never appear as the answer in `train.jsonl`.
Built from news feeds, the files hold publishers' headlines: keep them private. With
`--public`, only public-data feeds and Federal Register documents are used.

    research/.venv/bin/python research/ask/build.py research/data research/ask/data
    research/.venv/bin/python research/ask/build.py research/data research/ask/data-public \\
        --public research/data-fr/federal_register
"""

from __future__ import annotations

import bisect
import collections
import hashlib
import json
import math
import random
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import corpus

from unlimitedpipe import decide
from unlimitedpipe.operators.extract import STOPWORDS
from unlimitedpipe.sources.ask import (
    PROMPT,
    QUESTION_WORDS,
    days_asked,
    needed,
    rank,
    source_lines,
    terms,
)
from unlimitedpipe.sources.search import IRREGULAR, SAME, STORY_UPDATES, stem, story, word_pattern

SOURCE_COUNTS = (10,) * 7 + (5,) * 2 + (3,)  # `ask` gives 10 unless --sources says otherwise
LISTED = 5  # a listing names at most this many sources
SENTENCES = 2  # what `ask` asks of models under 3B parameters
THAI_SHARE = 0.15  # English first (build 4); build 3 was half Thai
YES_NO = re.compile(r"(any|anything|is|are|was|were|did|do|does|got|has|have)\b", re.IGNORECASE)
FORMAL = {
    ("lookup", "en"): (
        "What is the latest on {a} {b}?",
        "Any news about {a} and {b}?",
        "What happened with {a} {b}?",
        "Tell me about {a} {b}.",
        "Is there anything new about {a} {b}?",
    ),
    ("lookup", "th"): (
        "มีข่าวอะไรเกี่ยวกับ {a} {b} บ้าง",
        "{a} {b} ล่าสุดเป็นอย่างไร",
        "ช่วยสรุปข่าว {a} {b} หน่อย",
    ),
    ("listing", "en"): (
        "Any {topic} this week?",
        "What are the latest {topic}?",
        "Show me recent {topic}.",
        "Were there any {topic} today?",
        "What {topic} were there this month?",
        "What is the latest {topic} news?",
        "Tell me the latest news on {topic}.",
    ),
    ("listing", "th"): (
        "มี {topic} อะไรบ้างสัปดาห์นี้",
        "{topic} ล่าสุดมีอะไรบ้าง",
        "วันนี้มี {topic} อะไรบ้าง",
    ),
    ("refusal", "en"): ("What is the latest on {a} {b} {c}?", "Any news about {a} {b} {c}?"),
    ("refusal", "th"): ("มีข่าวอะไรเกี่ยวกับ {a} {b} {c} บ้าง",),
}
# The way people type: short, lower case, no question word.
CASUAL = {
    ("lookup", "en"): (
        "{a} {b}?",
        "whats new with {a} {b}",
        "any news on {a} {b}",
        "{a} {b} news",
        "what happened to {a} {b}",
        "latest {a} {b}",
        "update on {a} {b}?",
        "so what's going on with {a} {b}",
        "got anything about {a} {b}?",
        "{a} {b} - what do we know",
    ),
    ("lookup", "th"): (
        "{a} {b} เป็นไงบ้าง",
        "ขอข่าว {a} {b} หน่อย",
        "{a} {b} มีอะไรใหม่",
        "มีอะไรเกี่ยวกับ {a} {b} ไหม",
        "{a} {b} ล่าสุด",
        "{a} {b} ว่าไงบ้าง",
    ),
    ("listing", "en"): (
        "{topic}?",
        "recent {topic}",
        "{topic} lately?",
        "any {topic} today?",
        "{topic} this week",
        "any {topic} in the past month?",
        "latest {topic} please",
        "whats new with {topic}",
        "anything about {topic}?",
        "{topic} news",
        "news about {topic}",
        "{topic} updates",
        "what's going on with {topic}",
        "latest on {topic}",
        "{topic} today",
    ),
    ("listing", "th"): (
        "{topic} วันนี้มีอะไรบ้าง",
        "ขอ {topic} ล่าสุดหน่อย",
        "{topic} เดือนนี้มีอะไรบ้าง",
        "มี {topic} ใหม่ไหม",
        "{topic} เป็นไงบ้าง",
        "ข่าว {topic} สัปดาห์นี้",
    ),
    ("refusal", "en"): ("{a} {b} {c}?", "whats new with {a} {b} {c}", "{a} {b} {c} news"),
    ("refusal", "th"): ("{a} {b} {c} เป็นไงบ้าง", "ขอข่าว {a} {b} {c} หน่อย"),
}


def headline(title: str) -> str:
    """The title as the source wrote it. (Cutting what comes before a colon, meant for outlet
    names such as "BBC Africa:", also cut subjects such as "Bitcoin (BTC) price:" in build 1,
    and the model learned to drop them.)"""
    return " ".join(title.split()).rstrip(".")


def short(title: str, words: int = 10) -> str:
    """A long title's opening, for lists: the subject comes first in a headline."""
    cut = headline(title).split()
    return " ".join(cut[:words]).rstrip(".,;:") + ("…" if len(cut) > words else "")


def first_sentence(text: str, words: int = 30) -> str:
    sentence = re.split(r"(?<=[.!?])\s", " ".join(text.split()), maxsplit=1)[0]
    cut = sentence.split()
    return " ".join(cut[:words]).rstrip(".,;:") + ("…" if len(cut) > words else "")


def day(item: dict) -> str:
    return (item.get("date") or "")[:10]


def held(key: str) -> bool:
    """One in ten topics and items only ever tested, the same on every run."""
    return hashlib.sha256(key.encode()).digest()[0] % 10 == 0


class Tokens:
    """Where each word of some texts starts, to find what `word_pattern` finds without scanning
    every text: a word matches at the start of a word ("hack" in "hackers"), a word of three
    letters or fewer only as itself or with a plural or verb ending."""

    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        where: dict[str, set[int]] = collections.defaultdict(set)
        for n, text in enumerate(texts):
            for token in re.findall(r"\w+", text.casefold()):
                where[token].add(n)
        self.where = dict(where)
        self.tokens = sorted(where)

    def find(self, word: str) -> set[int]:
        forms = None
        if word.isascii() and not (SAME.get(stem(word)) or SAME.get(word.casefold())):
            base = stem(word)
            forms = [f.casefold() for f in (base, *IRREGULAR.get(base, ()))]
            if not all(re.fullmatch(r"\w+", f) for f in forms):
                forms = None
        if forms is None:  # Thai, or a form with punctuation in it: read every text
            pattern = word_pattern(word)
            return {n for n, t in enumerate(self.texts) if pattern.search(t)}
        found: set[int] = set()
        for form in forms:
            if len(form) <= 3:
                for ending in ("", "s", "es", "ed", "ing"):
                    found |= self.where.get(form + ending, set())
                continue
            i = bisect.bisect_left(self.tokens, form)
            while i < len(self.tokens) and self.tokens[i].startswith(form):
                found |= self.where[self.tokens[i]]
                i += 1
        return found


class World:
    """A catalog as `ask` would see it on a given day: the same ranking as `ask.rank`, over the
    items dated up to that day, fast enough for tens of thousands of questions."""

    def __init__(self, items: list[dict], feeds: list[dict]) -> None:
        self.items = sorted(items, key=lambda i: str(i.get("date") or ""))
        self.dates = [str(i.get("date") or "") for i in self.items]
        self.feeds = feeds
        self.names = {
            f["name"]: (f["name"].replace("-", " "), f.get("description") or "") for f in feeds
        }
        self.heads = [f"{i['title']} {self.names.get(i['feed'], ('', ''))[0]}" for i in self.items]
        self.bodies = [i.get("summary") or "" for i in self.items]
        self.index = {id(item): n for n, item in enumerate(self.items)}
        self._heads, self._bodies = Tokens(self.heads), Tokens(self.bodies)
        self._hits: dict[str, tuple[set[int], set[int], list[int]]] = {}
        self._about: dict[str, set[str]] = {}

    def hits(self, word: str) -> tuple[set[int], set[int], list[int]]:
        """Items whose title or feed name has the word, whose summary has it, and all of them
        in date order."""
        if word not in self._hits:
            head = self._heads.find(word)
            body = self._bodies.find(word) - head
            self._hits[word] = (head, body, sorted(head | body))
        return self._hits[word]

    def about(self, word: str) -> set[str]:
        if word not in self._about:
            pattern = word_pattern(word)
            self._about[word] = {n for n, (_, d) in self.names.items() if pattern.search(d)}
        return self._about[word]

    def window(self, since: str | None, until: str) -> tuple[int, int]:
        return (bisect.bisect_left(self.dates, since) if since else 0), bisect.bisect_right(
            self.dates, until
        )

    def rank(self, words, limit: int, since: str | None, until: str, without: dict | None = None):
        """`ask.rank` on the items dated from `since` to `until`, as if `without` were not in
        the catalog."""
        lo, hi = self.window(since, until)
        skip = self.index[id(without)] if without is not None else -1
        seen = hi - lo - (lo <= skip < hi)
        found: set[int] = set()
        rarity = {}
        for word in words:
            every = self.hits(word)[2]
            inside = every[bisect.bisect_left(every, lo) : bisect.bisect_left(every, hi)]
            inside = [n for n in inside if n != skip]
            rarity[word] = 1 + math.log((seen + 1) / (1 + len(inside)))
            found.update(inside)
        scored = []
        for n in sorted(found):
            covered, score = set(), 0.0
            for word in words:
                head, body, _ = self.hits(word)
                weight = 2 if n in head else 1 if n in body else 0
                if weight:
                    covered.add(word)
                    score += weight * rarity[word]
            if covered and any(self.items[n]["feed"] in self.about(w) for w in words):
                score += 0.5
            if covered:
                scored.append((len(covered), score, self.dates[n], n, covered))
        if not scored:
            return [], set()
        scored.sort(key=lambda s: (s[0], s[1], s[2]), reverse=True)
        best_coverage, best_score = scored[0][0], scored[0][1]
        kept = [s for s in scored if s[0] == best_coverage and s[1] >= best_score / 2]
        updates: collections.Counter[str] = collections.Counter()
        chosen = []
        for s in kept:
            updates[story(self.items[s[3]])] += 1
            if updates[story(self.items[s[3]])] <= STORY_UPDATES:
                chosen.append(self.items[s[3]])
        return chosen[:limit], scored[0][4]

    def check(self, questions: list[str], until: str) -> None:
        """Stop if this ranking and `ask.rank` ever disagree."""
        lo, hi = self.window(None, until)
        document = {"feeds": self.feeds, "items": self.items[lo:hi]}
        for question in questions:
            words = terms(question)
            mine = self.rank(words, 10, None, until)[0]
            theirs = rank(document, words, 10)[0]
            if [id(i) for i in mine] != [id(i) for i in theirs]:
                raise SystemExit(f"World.rank differs from ask.rank on {question!r}")


class Builder:
    def __init__(self, world: World, seed: int = 0, decide: bool = False) -> None:
        self.world = world
        self.rng = random.Random(seed)
        self.decide = decide  # decisions (USE 2 5 / NONE) instead of written answers
        documents = collections.Counter()
        for item in world.items:
            documents.update(set(self.words(item["title"])))
        self.rarity = {w: math.log(len(world.items) / n) for w, n in documents.items()}
        self.documents = documents

    @staticmethod
    def words(text: str) -> list[str]:
        found = [w.rstrip("'-") for w in re.findall(r"[A-Za-z][A-Za-z0-9'-]{3,}", headline(text))]
        return [
            w
            for w in found
            if len(w) > 3 and w.casefold() not in STOPWORDS and w.casefold() not in QUESTION_WORDS
        ]

    def keywords(self, item: dict, count: int) -> list[str] | None:
        """The item's rarest words: what a person would ask about."""
        words = list(dict.fromkeys(self.words(item["title"])))
        if len(words) < count:
            return None
        words.sort(key=lambda w: -self.rarity.get(w, 0))
        return words[:count]

    def lang(self) -> str:
        """English first: most people ask in English; a little Thai keeps Thai working."""
        return "th" if self.rng.random() < THAI_SHARE else "en"

    def question(self, kind: str, lang: str, **parts: str) -> tuple[str, str]:
        style = "casual" if self.rng.random() < 0.45 else "formal"
        template = self.rng.choice((CASUAL if style == "casual" else FORMAL)[(kind, lang)])
        if style == "casual" and self.rng.random() < 0.6:
            parts = {k: v.casefold() for k, v in parts.items()}
        return template.format(**parts), style

    def ask(self, question: str, today: datetime, leave_out: dict | None = None):
        """What `ask` would give the model on `today`: the sources, or None when it would not
        ask a model at all (nothing found, or a weak match)."""
        words = terms(question)
        if not words:
            return None
        days = days_asked(question)
        since = (today - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ") if days else None
        until = today.strftime("%Y-%m-%dT%H:%M:%SZ")
        limit = self.rng.choice(SOURCE_COUNTS)
        sources, covered = self.world.rank(words, limit, since, until, without=leave_out)
        if not sources or len(covered) < needed(words):
            return None
        return sources

    def after(self, item: dict) -> datetime:
        """A moment up to a day after the item came out: when someone asks about it."""
        when = datetime.fromisoformat((item.get("date") or "2026-09-26")[:19].replace("Z", ""))
        return when + timedelta(minutes=self.rng.randint(30, 36 * 60))

    def example(self, kind, lang, style, question, sources, answer, gold, today) -> dict:
        prompt = PROMPT.format(
            today=today.strftime("%A %d %B %Y"),
            sources=source_lines(sources),
            question=question,
            sentences=SENTENCES,
        )
        if self.decide:
            prompt = decide.PROMPT.format(
                today=today.strftime("%A %d %B %Y"),
                most=decide.MOST,
                sources=source_lines(sources),
                question=question,
            )
            answer = "USE " + " ".join(map(str, gold[: decide.MOST])) if gold else "NONE"
        return {
            "messages": [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": answer},
            ],
            "kind": kind,
            "lang": lang,
            "style": style,
            "question": question,
            "gold": gold,
            "sources": len(sources),
        }

    def lookup(self, item: dict, lang: str) -> dict | None:
        words = self.keywords(item, 2)
        if not words:
            return None
        question, style = self.question("lookup", lang, a=words[0], b=words[1])
        today = self.after(item)
        sources = self.ask(question, today)
        if not sources or item not in sources:
            return None  # search would not find it: nothing for the model to learn here
        if len(sources) >= 3:
            # Three or more sources match the question as well as this item does: the question
            # is broader than one item ("openai news"), so the answer lists them.
            return self.listed(lang, style, question, sources, today)
        n = sources.index(item) + 1
        text, date = headline(item["title"]), day(item)
        if lang == "en":
            answer = f"{text} ({date}) [{n}]."
            if item.get("summary") and first_sentence(item["summary"]) not in text:
                answer += f" {first_sentence(item['summary'])} [{n}]."
        else:
            answer = f"ข่าวล่าสุดจากแหล่งข่าว [{n}] ({date}): {text}"
        return self.example("lookup", lang, style, question, sources, answer, [n], today)

    def listing(self, topic: str, lang: str, today: datetime) -> dict | None:
        """Every source `ask` keeps covers the whole topic, so all are answers: name the first
        five, in the order given."""
        question, style = self.question("listing", lang, topic=topic)
        sources = self.ask(question, today)
        if not sources or len(sources) < 2:
            return None
        return self.listed(lang, style, question, sources, today)

    def listed(self, lang, style, question, sources, today) -> dict:
        gold = list(range(1, min(LISTED, len(sources)) + 1))
        parts = [f"{short(sources[n - 1]['title'])} [{n}]" for n in gold]
        if lang == "th":
            opening = "มีดังนี้: "
        elif YES_NO.match(question):
            opening = "Yes: "  # "any insider buys this week?"
        else:
            opening = "Latest: "  # "openai news", "what are the latest earthquakes?"
        answer = opening + "; ".join(parts) + "."
        return self.example("listing", lang, style, question, sources, answer, gold, today)

    def subset(self, feed: str, lang: str, today: datetime) -> list[dict]:
        """Decisions over a feed that mixes two kinds of item under one name ("food drug
        recalls"): asked for one kind ("drug recalls"), every item matches by the feed's name,
        and only the items of that kind answer."""
        made = []
        for topic, kind in MIXED_FEEDS.get(feed, {}).items():
            question, style = self.question("listing", lang, topic=topic)
            sources = self.ask(question, today)
            if not sources:
                continue
            gold = [
                n
                for n, s in enumerate(sources, 1)
                if kind(f"{s['title']} {s.get('summary') or ''}")
            ]
            if 1 <= len(gold) < len(sources):
                made.append(
                    self.example("listing", lang, style, question, sources, "", gold, today)
                )
        return made

    def refusal(self, item: dict, lang: str) -> dict | None:
        """A three-word question whose rarest word no source has: `ask` still passes it to
        the model (two of three words match), which must say what is missing."""
        words = self.keywords(item, 3)
        if not words:
            return None
        made = self._refusal(item, lang, words[0], words[1:])
        if made is None and self.decide and len(self.keywords(item, 4) or []) == 4:
            # Decisions need more "not covered": try the next rarest word as the missing one.
            four = self.keywords(item, 4) or []
            made = self._refusal(item, lang, four[1], [four[0], four[2]])
        return made

    def _refusal(self, item: dict, lang: str, missing: str, kept: list[str]) -> dict | None:
        question, style = self.question("refusal", lang, a=kept[0], b=kept[1], c=missing)
        today = self.after(item)
        sources = self.ask(question, today, leave_out=item)
        if not sources:
            return None
        text = " ".join(f"{s['title']} {s.get('summary') or ''}" for s in sources)
        if word_pattern(missing.casefold()).search(text):
            return None
        closest = headline(sources[0]["title"])
        answer = (
            f"The sources do not say anything about {missing}. The closest is: {closest} [1]."
            if lang == "en"
            else f"แหล่งข่าวไม่ได้กล่าวถึง {missing} ข่าวที่ใกล้เคียงที่สุดคือ: {closest} [1]"
        )
        return self.example("refusal", lang, style, question, sources, answer, [], today)

    def topics(self, today: datetime, count: int) -> list[str]:
        """Words people would ask "what's new with" about: in two to fifteen items of the last
        week, in no more than a few percent of all titles."""
        until = today.strftime("%Y-%m-%dT%H:%M:%SZ")
        week = (today - timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
        lo, hi = self.world.window(week, until)
        counts = collections.Counter()
        for item in self.world.items[lo:hi]:
            counts.update(set(self.words(item["title"])))
        limit = max(15, len(self.world.items) // 50)
        good = [w for w, n in counts.items() if 2 <= n <= 15 and self.documents[w] <= limit]
        self.rng.shuffle(good)
        return good[:count]


_DRUG = re.compile(
    r"\b(drug|tablets?|capsules?|injection|pharma\w*|dose|dosage|mg|vials?|syringes?|"
    r"prescription|medication|ointment|inhaler)\b",
    re.IGNORECASE,
)
# Feeds that mix kinds of item under one name, and how to tell each kind by its own words.
MIXED_FEEDS = {
    "food-drug-recalls": {
        "drug recalls": lambda text: bool(_DRUG.search(text)),
        "food recalls": lambda text: not _DRUG.search(text),
    },
}


# Feeds whose items may be republished, for a model that can be public: works of the US
# federal government (public domain), and sentences UnlimitedPipe writes itself from open data
# (prices, moves, weather, breaches). News outlets, the WHO (non-commercial), GDACS and
# non-US central banks are left out.
PUBLIC_FEEDS = {
    "insider-trades",
    "sec-company-events",
    "sec-ipo-filings",
    "sec-cyber-incidents",
    "sec-press-releases",
    "sec-enforcement",
    "activist-stakes",
    "us-new-rules",
    "sanctions-actions",
    "lobbying-big-spenders",
    "earthquakes",
    "tsunami-alerts",
    "hurricanes",
    "typhoons",
    "space-weather",
    "natural-events",
    "exploited-vulnerabilities",
    "food-drug-recalls",
    "fda-news",
    "us-justice",
    "nasa-image",
    "crypto-prices",
    "crypto-big-moves",
    "stablecoin-supply",
    "crypto-hacks",
    "exchange-listings",
    "thailand-weather",
    "data-breaches",
}
# Mixed feeds: only their US-government items.
PUBLIC_LINKS = {
    "central-banks": "federalreserve.gov",
    "world-leaders": "whitehouse.gov",
    "travel-advisories": "travel.state.gov",
}
# Federal Register documents by type, as the feeds a catalog of them would have.
FR_FEEDS = {
    "rule": ("us-final-rules", "Final rules published in the US Federal Register"),
    "proposed rule": (
        "us-proposed-rules",
        "Proposed rules open for comment in the Federal Register",
    ),
    "notice": ("us-agency-notices", "Notices of US federal agencies in the Federal Register"),
    "presidential document": (
        "presidential-documents",
        "Executive orders, proclamations and memoranda of the US President",
    ),
}
_SMALL = {"of", "and", "the", "for", "on", "in", "to", "a", "an", "at", "by"}


def agency_name(agency: str) -> str:
    words = agency.casefold().split()
    return " ".join(w if w in _SMALL and n else w.capitalize() for n, w in enumerate(words))


def public_only(items: list[dict]) -> list[dict]:
    return [
        i
        for i in items
        if i["feed"] in PUBLIC_FEEDS or PUBLIC_LINKS.get(i["feed"], "\0") in (i.get("link") or "")
    ]


def federal_register_items(folder: str) -> list[dict]:
    """Federal Register documents (public domain) with a SUMMARY, as catalog items: title with
    the agency first, the opening of the summary, link and date."""
    import pyarrow.parquet as pq

    items = []
    for path in sorted(Path(folder).glob("*.parquet")):
        parquet = pq.ParquetFile(path)
        for group in range(parquet.metadata.num_row_groups):
            rows = parquet.read_row_group(
                group, columns=["date", "type", "agency", "title", "text", "url"]
            ).to_pylist()
            for d in rows:
                summary = re.search(r"SUMMARY:\n(.+)", d["text"] or "")
                if not (d["title"] and summary and d["type"] in FR_FEEDS):
                    continue
                title = " ".join(d["title"].split())
                items.append(
                    {
                        "feed": FR_FEEDS[d["type"]][0],
                        "title": f"{agency_name(d['agency'])}: {title}" if d["agency"] else title,
                        "summary": " ".join(summary.group(1).split())[:400],
                        "link": d["url"],
                        "date": d["date"] + "T00:00:00Z",
                    }
                )
    return items


def build_world(builder: Builder, items: list[dict], days: list[datetime], per_day: int, name: str):
    """Examples from one world: a lookup (a list when the question is broad) and a refusal per
    item, and on each of `days`, a listing per feed and `per_day` "what's new with" topics."""
    split: dict[str, list[dict]] = {"train": [], "test": []}
    rng = builder.rng
    for item in items:
        part = "test" if held(f"{name}|{item['feed']}|{item['title']}") else "train"
        made_here = (
            builder.lookup(item, builder.lang()),
            builder.refusal(item, "en"),
            builder.refusal(item, "th") if rng.random() < THAI_SHARE else None,
        )
        for made in made_here:
            if made:
                split[part].append(made)
    feeds = {i["feed"] for i in builder.world.items}
    for today in days:
        for feed in sorted(feeds):
            topic = feed.replace("-", " ")
            made = builder.listing(topic, builder.lang(), today)
            if made:
                split["test" if held(f"{name}|feed|{feed}") else "train"].append(made)
        for word in builder.topics(today, per_day):
            made = builder.listing(word, builder.lang(), today)
            if made:
                split["test" if held(f"{name}|topic|{word.casefold()}") else "train"].append(made)
        if builder.decide:
            for feed in sorted(feeds):
                part = "test" if held(f"{name}|subset|{feed}") else "train"
                split[part] += builder.subset(feed, builder.lang(), today)
    return split


def main(
    catalog: str,
    out: str,
    public: bool = False,
    fr_folder: str | None = None,
    decide: bool = False,
) -> None:
    rng = random.Random(0)
    feeds = json.loads((Path(catalog) / "feeds.json").read_text(encoding="utf-8"))["feeds"]
    items = corpus.load(catalog)
    if public:
        items = public_only(items)
    worlds = [("catalog", items, feeds)]
    if fr_folder:
        fr = federal_register_items(fr_folder)
        fr_feeds = [{"name": n, "description": d} for n, d in FR_FEEDS.values()]
        worlds.append(("federal-register", fr, fr_feeds))
    split: dict[str, list[dict]] = {"train": [], "test": []}
    for name, world_items, world_feeds in worlds:
        world = World(world_items, world_feeds)
        builder = Builder(world, seed=len(split["train"]), decide=decide)
        last = datetime.fromisoformat(world.dates[-1][:19].replace("Z", ""))
        sample = [" ".join(builder.keywords(i, 2) or ["x"]) for i in world_items[:60]]
        world.check(
            sample + [f"{f['name'].replace('-', ' ')} latest" for f in world_feeds], world.dates[-1]
        )
        if name == "catalog":
            world.check(
                [f"{f['name'].replace('-', ' ')} latest" for f in world_feeds]
                + [" ".join(builder.keywords(i, 2) or ["x"]) for i in world_items[:200]],
                world.dates[-1],
            )
            chosen = world_items
            # Every day of the last five weeks, at different hours.
            days = [last - timedelta(days=d, hours=rng.randint(0, 20)) for d in range(35)]
            per_day = 60
        else:
            chosen = rng.sample(world_items, min(len(world_items), 9000))
            first = datetime.fromisoformat(world.dates[0][:10])
            span = (last - first).days
            days = [
                first + timedelta(days=rng.randint(40, span), hours=rng.randint(8, 22))
                for _ in range(400)
            ]
            per_day = 15
        made = build_world(builder, chosen, sorted(days), per_day, name)
        for part in split:
            split[part] += made[part]
        print(f"{name}: {len(world_items)} items, {sum(len(v) for v in made.values())} examples")
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    for name, examples in split.items():
        rng.shuffle(examples)
        with (folder / f"{name}.jsonl").open("w", encoding="utf-8") as lines:
            for example in examples:
                lines.write(json.dumps(example, ensure_ascii=False) + "\n")
        kinds = collections.Counter((e["kind"], e["lang"]) for e in examples)
        styles = collections.Counter(e["style"] for e in examples)
        counts = collections.Counter(e["sources"] for e in examples)
        print(
            f"{name}: {len(examples)} examples "
            + ", ".join(f"{k} {lang} {n}" for (k, lang), n in sorted(kinds.items()))
            + f"; {dict(styles)}; sources {dict(sorted(counts.items()))}"
        )


if __name__ == "__main__":
    # build.py CATALOG OUT [--public [FEDERAL_REGISTER_FOLDER]] [--decide]
    args = sys.argv[1:]
    decide_mode = "--decide" in args
    args = [a for a in args if a != "--decide"]
    public = "--public" in args
    fr = (
        args[args.index("--public") + 1]
        if public and len(args) > args.index("--public") + 1
        else None
    )
    rest = [a for a in args if a not in ("--public", fr)]
    main(
        rest[0] if rest else "research/data",
        rest[1] if len(rest) > 1 else "research/ask/data",
        public=public,
        fr_folder=fr,
        decide=decide_mode,
    )
