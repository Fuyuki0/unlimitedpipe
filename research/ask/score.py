"""Score a model on the `ask` test examples: does it answer like the tool needs?

For each example the model gets the exact prompt `ask` sends, through Ollama, with the same
settings as `ask` for small models, and passes when:

- lookup: it cites the right source, cites no source that does not exist, invents no
  number, and answers in the question's language (Thai questions need some Thai);
- listing: it cites at least two of the right sources;
- refusal: it says the sources do not cover the question.

    research/.venv/bin/python research/ask/score.py qwen2.5:0.5b --per-kind 10
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import re
import sys
import time
from pathlib import Path

import httpx

from unlimitedpipe.sources.ask import unsupported_numbers

REFUSAL = re.compile(
    r"\b(not|no|none|nothing|don't|doesn't|does not|do not|cannot|can't)\b|ไม่", re.IGNORECASE
)
THAI = re.compile(r"[฀-๿]")


def check(example: dict, answer: str) -> dict[str, bool]:
    prompt = example["messages"][0]["content"]
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
    checks = {"answered": bool(answer.strip())}
    if example["kind"] == "refusal":
        checks["says not covered"] = bool(REFUSAL.search(answer))
    else:
        gold = set(example["gold"])
        need = 1 if example["kind"] == "lookup" else 2
        checks["cites the right source"] = len(cited & gold) >= need
        checks["cites only real sources"] = all(1 <= n <= example["sources"] for n in cited)
        checks["invents no number"] = not unsupported_numbers(answer, prompt)
    if example["lang"] == "th":
        checks["answers in Thai"] = bool(THAI.search(answer))
    return checks


def ask(model: str, prompt: str, host: str) -> str:
    response = httpx.post(
        f"{host}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 150},
        },
        timeout=300,
    )
    response.raise_for_status()
    return response.json().get("response", "").strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    parser.add_argument("--test", default="research/ask/data/test.jsonl")
    parser.add_argument("--per-kind", type=int, default=10, help="examples per kind and language")
    parser.add_argument("--host", default="http://127.0.0.1:11434")
    parser.add_argument("--out", default=None, help="write every answer here (JSONL)")
    args = parser.parse_args()

    examples = [
        json.loads(line) for line in Path(args.test).read_text(encoding="utf-8").splitlines()
    ]
    groups = collections.defaultdict(list)
    for example in examples:
        groups[(example["kind"], example["lang"])].append(example)
    rng = random.Random(0)
    chosen = [
        e
        for key in sorted(groups)
        for e in rng.sample(groups[key], min(args.per_kind, len(groups[key])))
    ]

    results = collections.defaultdict(list)
    records = []
    start = time.time()
    for n, example in enumerate(chosen, 1):
        answer = ask(args.model, example["messages"][0]["content"], args.host)
        checks = check(example, answer)
        results[(example["kind"], example["lang"])].append(all(checks.values()))
        records.append(
            {
                "question": example["question"],
                "kind": example["kind"],
                "lang": example["lang"],
                "answer": answer,
                "checks": checks,
            }
        )
        print(f"\r{n}/{len(chosen)}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as out:
            for record in records:
                out.write(json.dumps(record, ensure_ascii=False) + "\n")

    total = [ok for oks in results.values() for ok in oks]
    print(
        f"{args.model}: {sum(total)}/{len(total)} passed ({sum(total) / len(total):.0%}), "
        f"{(time.time() - start) / len(total):.1f} s per answer"
    )
    for (kind, lang), oks in sorted(results.items()):
        print(f"  {kind:8} {lang}  {sum(oks):3}/{len(oks):<3} {sum(oks) / len(oks):.0%}")
    fails = collections.Counter(name for r in records for name, ok in r["checks"].items() if not ok)
    if fails:
        print("  most failed checks: " + ", ".join(f"{k} ({v})" for k, v in fails.most_common()))


if __name__ == "__main__":
    main()
