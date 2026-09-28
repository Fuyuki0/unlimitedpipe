"""Run questions through `ask` itself on a saved catalog (with its archive) and keep what it did:
the answer, the sources, and for questions that reached the decision model the exact prompt it
got, so later models are graded on the same sources. Answers are then labelled by hand.

Unlike freeze.py, which rebuilds the prompts from the latest items, this follows every path
`ask` takes: a year or month the question names, the word index for questions without a date,
answers by size for "strongest" questions, and none at all when nothing matches.

    research/.venv/bin/python research/ask/real/freeze3.py SNAPSHOT_FOLDER \
        research/ask/real/questions-blind3.txt OUT.jsonl
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from unlimitedpipe import decide
from unlimitedpipe.context import Context
from unlimitedpipe.sources.ask import Ask, source_lines


async def run(catalog: str, question: str) -> dict:
    seen: dict = {}
    original = Ask._decide

    async def spy(self, ctx, asked, items):
        seen["prompt"] = decide.PROMPT.format(
            today=datetime.now(UTC).strftime("%A %d %B %Y"),
            most=decide.MOST,
            sources=source_lines(items),
            question=asked,
        )
        seen["result"] = await original(self, ctx, asked, items)
        return seen["result"]

    Ask._decide = spy
    try:
        ctx = Context(quiet=True)
        events = [e async for e in Ask(question=[question], catalog=catalog).collect(ctx)]
        await ctx.aclose()
    finally:
        Ask._decide = original
    data = events[-1].data
    result = seen.get("result")
    return {
        "question": question,
        "path": "model" if result else ("code" if data.get("model") is None else "writer"),
        "answer": data["answer"],
        "confidence": data.get("confidence"),
        "sources": data["sources"],
        **({"messages": [{"role": "user", "content": seen["prompt"]}]} if result else {}),
    }


def main(catalog: str, questions: str, out: str) -> None:
    done = set()
    if Path(out).exists():  # a stopped run goes on where it stopped
        done = {json.loads(line)["question"] for line in Path(out).open(encoding="utf-8")}
    with open(out, "a", encoding="utf-8") as lines:
        for question in Path(questions).read_text(encoding="utf-8").splitlines():
            question = question.strip()
            if not question or question.startswith("#") or question in done:
                continue
            row = asyncio.run(run(catalog, question))
            lines.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"{row['path']:6} {question}: {row['answer'][:110]}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
