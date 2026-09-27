"""The real-question test sets in the decision format (the model picks, the code writes), and
the answer the code writes from a decision, for grading decisions like written answers.

    research/.venv/bin/python research/ask/decide_sets.py research/ask/real
        # writes test-decide.jsonl, extra-decide.jsonl and blind-decide.jsonl beside the sets
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from unlimitedpipe import decide

LINE = re.compile(r"\[(\d+)\] \(([^,]*), ([^)]*)\) (.*)")


def parts(prompt: str) -> tuple[str, list[dict], str, str]:
    """Today, the sources and the question of an `ask` or decision prompt."""
    today = re.search(r"Today is ([^.]+)\.", prompt).group(1)
    block = prompt.split("Sources:\n", 1)[1].split("\n\nQuestion:", 1)[0]
    sources = []
    for line in block.splitlines():
        match = LINE.match(line)
        if match:
            text = match.group(4)
            title, _, summary = text.partition(" - ")
            sources.append(
                {"feed": match.group(2), "date": match.group(3), "title": title, "summary": summary}
            )
    question = prompt.rsplit("Question:", 1)[1].strip()
    return today, sources, question, block


def to_decide(example: dict) -> dict:
    today, _, question, block = parts(example["messages"][0]["content"])
    prompt = decide.PROMPT.format(today=today, most=decide.MOST, sources=block, question=question)
    return {**example, "messages": [{"role": "user", "content": prompt}]}


def written(example: dict, reply: str) -> str:
    """What `ask` would show for a decision: the code's answer, or the reply as it came when it
    is not a decision."""
    _, sources, question, _ = parts(example["messages"][0]["content"])
    picked = decide.parse(reply, len(sources))
    return reply if picked is None else decide.write(question, sources, picked)


if __name__ == "__main__":
    root = Path(sys.argv[1])
    for name in ("test", "extra", "blind"):
        path = root / f"{name}.jsonl"
        if not path.exists():
            continue
        rows = [json.loads(line) for line in path.open(encoding="utf-8")]
        with (root / f"{name}-decide.jsonl").open("w", encoding="utf-8") as out:
            for row in rows:
                out.write(json.dumps(to_decide(row), ensure_ascii=False) + "\n")
        print(name, len(rows))
