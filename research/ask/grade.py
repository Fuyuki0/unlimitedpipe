"""Grade the answers of a comparison job (research/ask/kaggle/compare3.py) on this machine, the
same way for every model, from its answers.jsonl and the test sets.

    research/.venv/bin/python research/ask/grade.py ANSWERS.jsonl [ANSWERS.jsonl ...] \\
        --real research/ask/real/test.jsonl --build3 research/ask/data-public/test.jsonl \\
        --build2-public V2_PUBLIC/test.jsonl --build2-news research/ask/data/test.jsonl

A good `ask` answer:

- cites the right source: one that answers a fact question; three of the matching sources
  for a list (all of them when fewer match);
- cites a few, not all: at most two sources that do not answer the question, so citing every
  source ("[1] [2] ... [10]") does not pass;
- says so plainly when the sources do not answer the question;
- invents no number, cites no source that does not exist, and answers Thai in Thai.
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import re

from unlimitedpipe.sources.ask import unsupported_numbers

PER_KIND = 20
DECLINED = re.compile(
    r"\b(do(es)? not|don't|doesn't|did not|didn't|cannot|can't|unable|isn't|aren't|none of|"
    r"no (information|mention|data|details|news|sources?|reports?)|there (is|are) no|"
    r"not (mention|say|cover|include|provide|contain|specify|state|list|report|give|have)|"
    r"nothing (about|on|regarding))\b|ไม่ได้|ไม่มี|ไม่พบ|ไม่ระบุ",
    re.IGNORECASE,
)
THAI = re.compile(r"[฀-๿]")
CITE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")  # [1], and [1, 2] as some models write it


def cited(answer: str) -> set[int]:
    return {int(n) for group in CITE.findall(answer) for n in group.split(",")}


def check(example: dict, answer: str) -> dict[str, bool]:
    prompt = example["messages"][0]["content"]
    found, gold = cited(answer), set(example["gold"])
    checks = {"answered": bool(answer.strip())}
    if example["kind"] == "refusal":
        checks["says not covered"] = bool(DECLINED.search(answer))
    else:
        need = 1 if example["kind"] == "lookup" else min(3, len(gold))
        checks["cites the right source"] = len(found & gold) >= need
    checks["cites a few, not all"] = len(found - gold) <= 2
    checks["invents no number"] = not unsupported_numbers(re.sub(CITE, " ", answer), prompt)
    checks["cites only real sources"] = all(1 <= n <= example["sources"] for n in found)
    if example["lang"] == "th":
        checks["answers in Thai"] = bool(THAI.search(answer))
    return checks


def rows(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as lines:
        return [json.loads(line) for line in lines]


def sample(examples: list[dict]) -> list[dict]:
    """The same sample compare3.py takes."""
    groups = collections.defaultdict(list)
    for example in examples:
        groups[(example["kind"], example["lang"])].append(example)
    rng = random.Random(0)
    picked = []
    for key in sorted(groups):
        picked += rng.sample(groups[key], min(PER_KIND, len(groups[key])))
    return picked


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("answers", nargs="+")
    parser.add_argument("--real", required=True)
    parser.add_argument("--real-extra")
    parser.add_argument("--real-blind")
    parser.add_argument("--build4")
    parser.add_argument("--build3", required=True)
    parser.add_argument("--build2-public", required=True)
    parser.add_argument("--build2-news", required=True)
    parser.add_argument("--json")
    args = parser.parse_args()
    sets = {"real": rows(args.real)}
    if args.real_extra:
        sets["real extra"] = rows(args.real_extra)
    if args.real_blind:
        sets["real blind"] = rows(args.real_blind)
    if args.build4:
        sets["build 4"] = sample(rows(args.build4))
    sets["build 3"] = sample(rows(args.build3))
    sets["build 2 public"] = sample(rows(args.build2_public))
    sets["build 2 news"] = sample(rows(args.build2_news))
    answers: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for path in args.answers:  # a later file's answers replace an earlier one's
        mine: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
        for a in rows(path):
            mine[(a["model"], a["set"])].append(a)
        answers.update(mine)
    report: dict[str, dict] = {}
    for (model, name), given in answers.items():
        if name not in sets:
            continue
        examples = sets[name]
        assert [a["question"] for a in given] == [e["question"] for e in examples], (model, name)
        passed, fails, recall = 0, collections.Counter(), []
        kinds = collections.defaultdict(lambda: [0, 0])
        for example, a in zip(examples, given, strict=True):
            checks = check(example, a["answer"])
            ok = all(checks.values())
            passed += ok
            kinds[example["kind"]][0] += ok
            kinds[example["kind"]][1] += 1
            fails.update(k for k, v in checks.items() if not v)
            if example["kind"] == "listing":
                gold = set(example["gold"])
                recall.append(min(1, len(cited(a["answer"]) & gold) / min(3, len(gold))))
        report.setdefault(model, {})[name] = {
            "passed": passed,
            "of": len(examples),
            "kinds": dict(kinds),
            "failed": dict(fails),
            "listing_recall": round(sum(recall) / len(recall), 2) if recall else None,
        }
    names = list(sets)
    print(f"{'model':24}" + "".join(f"{n:>16}" for n in names) + "   list recall (real)")
    for model, scores in report.items():
        cells = []
        for n in names:
            s = scores.get(n)
            cells.append(f"{s['passed']}/{s['of']} ({100 * s['passed'] // s['of']}%)" if s else "-")
        print(
            f"{model:24}"
            + "".join(f"{c:>16}" for c in cells)
            + f"   {scores.get('real', {}).get('listing_recall')}"
        )
    if args.json:
        with open(args.json, "w", encoding="utf-8") as out:
            json.dump(report, out, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
