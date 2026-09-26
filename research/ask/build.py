"""Training and test examples for `unlimited ask`, built from the catalog.

Every example is the exact prompt `ask` sends (same wording, same source ranking) and an
answer written from the sources by a template, so it is correct by construction:

- lookup: a question about one item, answered from it with its citation;
- listing: "any insider trades this week?", answered with up to three cited items;
- refusal: sources that miss the question's key word, answered by saying so;
- each also asked in Thai.

Items are split once: those in `test.jsonl` never appear as the answer in `train.jsonl`.
The files hold publishers' headlines: keep them private.

    research/.venv/bin/python research/ask/build.py research/data research/ask/data
"""

from __future__ import annotations

import collections
import json
import math
import random
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import corpus  # noqa: E402

from unlimitedpipe.operators.extract import STOPWORDS  # noqa: E402
from unlimitedpipe.sources.ask import (  # noqa: E402
    PROMPT,
    QUESTION_WORDS,
    rank,
    source_lines,
    terms,
)
from unlimitedpipe.sources.search import word_pattern  # noqa: E402

SOURCES = 5
SENTENCES = 2  # what `ask` asks of models under 3B parameters
EN_LOOKUP = (
    "What is the latest on {a} {b}?",
    "Any news about {a} and {b}?",
    "What happened with {a} {b}?",
    "Tell me about {a} {b}.",
    "Is there anything new about {a} {b}?",
)
TH_LOOKUP = (
    "มีข่าวอะไรเกี่ยวกับ {a} {b} บ้าง",
    "{a} {b} ล่าสุดเป็นอย่างไร",
    "ช่วยสรุปข่าว {a} {b} หน่อย",
)
EN_LISTING = ("Any {topic} this week?", "What are the latest {topic}?", "Show me recent {topic}.")
TH_LISTING = ("มี {topic} อะไรบ้างสัปดาห์นี้", "{topic} ล่าสุดมีอะไรบ้าง")
OUTLET = re.compile(r"^[^:]{2,40}: (?=\S)")


def headline(title: str) -> str:
    """The headline without an outlet prefix ("BBC Africa: ..."), which is metadata."""
    return OUTLET.sub("", title).strip().rstrip(".")


def first_sentence(text: str, words: int = 30) -> str:
    sentence = re.split(r"(?<=[.!?])\s", " ".join(text.split()), maxsplit=1)[0]
    cut = sentence.split()
    return " ".join(cut[:words]).rstrip(".,;:") + ("…" if len(cut) > words else "")


def day(item: dict) -> str:
    return (item.get("date") or "")[:10]


class Builder:
    def __init__(self, items: list[dict], feeds: list[dict], seed: int = 0) -> None:
        self.items = items
        self.feeds = feeds
        self.rng = random.Random(seed)
        documents = collections.Counter()
        for item in items:
            documents.update(set(self.words(item["title"])))
        self.rarity = {w: math.log(len(items) / n) for w, n in documents.items()}
        names = {f["name"]: f["name"].replace("-", " ") for f in feeds}
        self.texts = [f"{i['title']} {i['summary']} {names.get(i['feed'], '')}" for i in items]
        self.hit_cache: dict[str, set[int]] = {}

    def hits(self, term: str) -> set[int]:
        """Items that mention a term, cached: search scans every item once per word."""
        if term not in self.hit_cache:
            pattern = word_pattern(term)
            self.hit_cache[term] = {n for n, t in enumerate(self.texts) if pattern.search(t)}
        return self.hit_cache[term]

    def search(self, question: str, pool: dict, leave_out: dict | None = None):
        """`ask`'s ranking over the items that mention any of the question's words (the
        others would score nothing): nearly the same ranking, much faster."""
        words = terms(question)
        found = set().union(*(self.hits(w) for w in words)) if words else set()
        candidates = [self.items[n] for n in sorted(found) if self.items[n] is not leave_out]
        return rank({**pool, "items": candidates}, words, SOURCES)

    @staticmethod
    def words(text: str) -> list[str]:
        found = re.findall(r"[A-Za-z][A-Za-z0-9'-]{3,}", headline(text))
        return [
            w for w in found if w.casefold() not in STOPWORDS and w.casefold() not in QUESTION_WORDS
        ]

    def keywords(self, item: dict, count: int) -> list[str] | None:
        """The item's rarest words: what a person would ask about."""
        words = list(dict.fromkeys(self.words(item["title"])))
        if len(words) < count:
            return None
        words.sort(key=lambda w: -self.rarity.get(w, 0))
        return words[:count]

    def prompt(self, sources: list[dict], question: str, today: str) -> str:
        return PROMPT.format(
            today=datetime.fromisoformat(today).strftime("%A %d %B %Y"),
            sources=source_lines(sources),
            question=question,
            sentences=SENTENCES,
        )

    def example(self, kind, question, sources, answer, gold, lang, today) -> dict:
        return {
            "messages": [
                {"role": "user", "content": self.prompt(sources, question, today)},
                {"role": "assistant", "content": answer},
            ],
            "kind": kind,
            "lang": lang,
            "question": question,
            "gold": gold,
            "sources": len(sources),
        }

    def today_after(self, item: dict) -> str:
        when = day(item) or "2026-09-26"
        return (
            (datetime.fromisoformat(when) + timedelta(days=self.rng.choice((0, 1))))
            .date()
            .isoformat()
        )

    def lookup(self, item: dict, pool: dict) -> list[dict]:
        found = []
        words = self.keywords(item, 2)
        if not words:
            return found
        a, b = words
        for lang, templates in (("en", EN_LOOKUP), ("th", TH_LOOKUP)):
            question = self.rng.choice(templates).format(a=a, b=b)
            sources, _ = self.search(question, pool)
            if item not in sources:
                continue  # search would not find it: nothing for the model to learn here
            n = sources.index(item) + 1
            text = headline(item["title"])
            date = day(item)
            if lang == "en":
                answer = f"{text} ({date}) [{n}]."
                if item["summary"] and first_sentence(item["summary"]) not in text:
                    answer += f" {first_sentence(item['summary'])} [{n}]."
            else:
                answer = f"ข่าวล่าสุดจากแหล่งข่าว [{n}] ({date}): {text}"
            found.append(
                self.example("lookup", question, sources, answer, [n], lang, self.today_after(item))
            )
        return found

    def listing(self, feed: dict, pool: dict) -> list[dict]:
        found = []
        topic = feed["name"].replace("-", " ")
        for lang, templates in (("en", EN_LISTING), ("th", TH_LISTING)):
            question = self.rng.choice(templates).format(topic=topic)
            sources, _ = self.search(question, pool)
            mine = [i for i, s in enumerate(sources, 1) if s["feed"] == feed["name"]][:3]
            if len(mine) < 2:
                continue
            parts = [f"{headline(sources[i - 1]['title'])} [{i}]" for i in mine]
            answer = ("Yes: " if lang == "en" else "มีดังนี้: ") + "; ".join(parts) + "."
            latest = max(day(sources[i - 1]) for i in mine)
            found.append(
                self.example(
                    "listing", question, sources, answer, mine, lang, latest or "2026-09-26"
                )
            )
        return found

    def refusal(self, item: dict, pool: dict) -> list[dict]:
        """A three-word question whose rarest word no source has: `ask` still passes it to
        the model (two of three words match), which must say what is missing."""
        words = self.keywords(item, 3)
        if not words:
            return []
        missing, *kept = words
        lang = self.rng.choice(("en", "th"))
        question = (
            f"What is the latest on {kept[0]} {kept[1]} {missing}?"
            if lang == "en"
            else f"มีข่าวอะไรเกี่ยวกับ {kept[0]} {kept[1]} {missing} บ้าง"
        )
        sources, covered = self.search(question, pool, leave_out=item)
        text = " ".join(f"{s['title']} {s['summary']}" for s in sources).casefold()
        if not sources or missing.casefold() in text or len(covered) < 2:
            return []
        closest = headline(sources[0]["title"])
        answer = (
            f"The sources do not say anything about {missing}. The closest is: {closest} [1]."
            if lang == "en"
            else f"แหล่งข่าวไม่ได้กล่าวถึง {missing} ข่าวที่ใกล้เคียงที่สุดคือ: {closest} [1]"
        )
        return [
            self.example("refusal", question, sources, answer, [], lang, self.today_after(item))
        ]


def main(catalog: str, out: str) -> None:
    items = corpus.load(catalog)
    feeds = json.loads((Path(catalog) / "feeds.json").read_text(encoding="utf-8"))["feeds"]
    rng = random.Random(0)
    order = items[:]
    rng.shuffle(order)
    held = {id(i) for i in order[: len(order) // 10]}  # 10% of items only ever tested
    held_feeds = {f["name"] for f in rng.sample(feeds, max(1, len(feeds) // 10))}
    pool = {"feeds": feeds, "items": items}
    builder = Builder(items, feeds)
    split: dict[str, list[dict]] = {"train": [], "test": []}
    for item in items:
        name = "test" if id(item) in held else "train"
        split[name] += builder.lookup(item, pool)
        split[name] += builder.refusal(item, pool)
    for feed in feeds:
        split["test" if feed["name"] in held_feeds else "train"] += builder.listing(feed, pool)
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    for name, examples in split.items():
        rng.shuffle(examples)
        with (folder / f"{name}.jsonl").open("w", encoding="utf-8") as lines:
            for example in examples:
                lines.write(json.dumps(example, ensure_ascii=False) + "\n")
        kinds = collections.Counter((e["kind"], e["lang"]) for e in examples)
        print(
            f"{name}: {len(examples)} examples "
            + ", ".join(f"{k} {lang} {n}" for (k, lang), n in sorted(kinds.items()))
        )


if __name__ == "__main__":
    main(
        sys.argv[1] if len(sys.argv) > 1 else "research/data",
        sys.argv[2] if len(sys.argv) > 2 else "research/ask/data",
    )
