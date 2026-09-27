"""Freeze real-style questions into test examples: each question goes through `ask`'s own
search on a saved catalog, and the prompt the model would get is kept, so every model is graded
on exactly the same sources. Answers are then labelled by hand in gold.json.

    research/.venv/bin/python research/ask/real/freeze.py \
        research/data research/ask/real/questions.txt OUT.jsonl
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from unlimitedpipe.sources.ask import PROMPT, days_asked, needed, rank, source_lines, terms


def main(catalog: str, questions: str, out: str) -> None:
    document = json.loads((Path(catalog) / "feeds.json").read_text(encoding="utf-8"))
    dates = sorted(str(i.get("date") or "") for i in document["items"])
    now = datetime.fromisoformat(dates[-1].replace("Z", "+00:00")).astimezone(UTC)
    kept = skipped = 0
    with open(out, "w", encoding="utf-8") as lines:
        for question in Path(questions).read_text(encoding="utf-8").splitlines():
            question = question.strip()
            if not question or question.startswith("#"):
                continue
            words = terms(question)
            days = days_asked(question)
            since = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ") if days else None
            items, covered = rank(document, words, 10, since=since)
            if not items or len(covered) < needed(words):
                print(f"ask answers without a model: {question}")
                skipped += 1
                continue
            prompt = PROMPT.format(
                today=now.strftime("%A %d %B %Y"),
                sources=source_lines(items),
                question=question,
                sentences=2,
            )
            lang = "th" if any("฀" <= c <= "๿" for c in question) else "en"
            lines.write(
                json.dumps(
                    {
                        "question": question,
                        "lang": lang,
                        "sources": len(items),
                        "messages": [{"role": "user", "content": prompt}],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            kept += 1
    print(f"{kept} questions reach a model, {skipped} are answered by ask alone")


if __name__ == "__main__":
    main(*sys.argv[1:4])
