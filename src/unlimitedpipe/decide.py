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


def first_sentence(text: str, words: int = 30) -> str:
    sentence = re.split(r"(?<=[.!?])\s", " ".join(str(text or "").split()), maxsplit=1)[0]
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
        answer = f"{title} ({date}) [{n}]." if date else f"{title} [{n}]."
        summary = first_sentence(item.get("summary") or "")
        if summary and summary not in title:
            answer += f" {summary} [{n}]."
        return answer
    parts = "; ".join(f"{short(sources[n - 1].get('title'))} [{n}]" for n in picked)
    if thai:
        return f"มีดังนี้: {parts}."
    if _YES_NO.match(question):
        return f"Yes: {parts}."
    from datetime import UTC, datetime

    from unlimitedpipe.archive import named_period

    named = named_period(question, datetime.now(UTC).isoformat())
    if named:  # "which citrix flaws were exploited in 2023?" is not about the latest
        return f"From {named[0] if named[0] == named[1] else named[0][:4]}: {parts}."
    return f"Latest: {parts}."
