"""The model decides, the code writes: a decision model picks which numbered sources answer a
question (or none), and the answer is written from those sources' own titles, dates and links.

A decision is a few tokens (`USE 1 3 4` or `NONE`), so it is fast on a small computer, and the
answer holds no word or number the sources do not have. Ollama reports how likely the first
token was, which is the decision's confidence.
"""

from __future__ import annotations

import re
from typing import Any

PROMPT = """Decide which numbered sources answer the question. Today is {today}.
Reply with USE and the numbers of the sources that answer it, the most useful first and at \
most {most}, like "USE 2 5". If no source answers it, reply NONE.

Sources:
{sources}

Question: {question}"""
MOST = 5
OLD_DAYS = 45  # a "latest" item older than this is not news
_DECISION = re.compile(r"^\s*(USE((?:\s+\d+)+)|NONE)\b", re.IGNORECASE)
_THAI = re.compile(r"[฀-๿]")
_YES_NO = re.compile(r"(any|anything|is|are|was|were|did|do|does|got|has|have)\b", re.IGNORECASE)


def parse(reply: str, count: int) -> list[int] | None:
    """The sources a decision picked, in order, each once and each a real source; [] for NONE;
    None when the reply is not a decision."""
    match = _DECISION.match(reply)
    if match is None:
        return None
    if match.group(2) is None:
        return []
    picked: list[int] = []
    for number in map(int, match.group(2).split()):
        if 1 <= number <= count and number not in picked:
            picked.append(number)
    return picked[:MOST]


def headline(title: Any) -> str:
    return " ".join(str(title or "").split()).rstrip(".")


def short(title: Any, words: int = 10) -> str:
    cut = headline(title).split()
    return " ".join(cut[:words]).rstrip(".,;:") + ("…" if len(cut) > words else "")


# Not the end of a sentence: "St. Louis", "U.S. rules", "Inc. said", "No. 2".
_ABBREVIATION = re.compile(r"(?:\b(?:St|Mr|Mrs|Ms|Dr|Inc|Corp|Co|Ltd|No|vs|Jr|Sr)|\b[A-Z])\.$")


def first_sentence(text: str, words: int = 30) -> str:
    flat = " ".join(str(text or "").split())
    sentence = flat
    for match in re.finditer(r"(?<=[.!?])\s", flat):
        if not _ABBREVIATION.search(flat[: match.start()]):
            sentence = flat[: match.start()]
            break
    cut = sentence.split()
    return " ".join(cut[:words]).rstrip(".,;:") + ("…" if len(cut) > words else "")


def write(question: str, sources: list[dict[str, Any]], picked: list[int]) -> str:
    """The answer, written from the picked sources only (numbered from 1 as given)."""
    thai = bool(_THAI.search(question))
    if not picked:
        if not sources:
            return "ไม่พบข้อมูลในแหล่งข่าว" if thai else "Nothing in the sources answers this."
        closest = headline(sources[0].get("title"))
        if thai:
            return f"แหล่งข่าวไม่ได้ตอบคำถามนี้ ข่าวที่ใกล้เคียงที่สุดคือ: {closest} [1]"
        return f"The sources do not answer this. The closest is: {closest} [1]."
    if len(picked) == 1:
        n = picked[0]
        item = sources[n - 1]
        title, date = headline(item.get("title")), str(item.get("date") or "")[:10]
        if thai:
            return f"ข่าวล่าสุดจากแหล่งข่าว [{n}] ({date}): {title}"
        dated = date and date not in title and date[:7] not in title
        answer = f"{title} ({date}) [{n}]." if dated else f"{title} [{n}]."
        summary = first_sentence(item.get("summary") or "")
        if summary and summary not in title:
            answer += f" {summary} [{n}]."
        return answer
    parts = "; ".join(f"{short(sources[n - 1].get('title'))} [{n}]" for n in picked)
    if thai:
        return f"มีดังนี้: {parts}."
    if _YES_NO.match(question):
        return f"Yes: {parts}."
    from datetime import UTC, datetime, timedelta

    from unlimitedpipe.archive import EVER, named_period

    today = datetime.now(UTC).isoformat()
    named = named_period(question, today)
    if named and named[0] == EVER:
        return f"Of all time: {parts}."
    if named:  # "which citrix flaws were exploited in 2023?" is not about the latest
        return f"From {named[0] if named[0] == named[1] else named[0][:4]}: {parts}."
    # Updates of one feed newest first ("new ollama version"); from several feeds, the most
    # useful first, as picked. Dated when even the newest is old, so 2023 does not read as now.
    if len({sources[n - 1].get("feed") for n in picked}) == 1:
        picked = sorted(picked, key=lambda n: str(sources[n - 1].get("date") or ""), reverse=True)
    newest = max(str(sources[n - 1].get("date") or "")[:10] for n in picked)
    recent = (datetime.fromisoformat(today[:10]) - timedelta(days=OLD_DAYS)).date().isoformat()
    if newest and newest < recent:
        dated = "; ".join(
            f"{short(sources[n - 1].get('title'))} ({str(sources[n - 1].get('date'))[:10]}) [{n}]"
            for n in picked
        )
        return f"Nothing recent; the latest found: {dated}."
    parts = "; ".join(f"{short(sources[n - 1].get('title'))} [{n}]" for n in picked)
    return f"Latest: {parts}."
