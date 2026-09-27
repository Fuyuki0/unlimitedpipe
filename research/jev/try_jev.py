"""Can Jev (TypeSafe AI's decision model) make the two decisions `ask`'s model gets wrong?

1. Do the sources answer the question at all? (If not, `ask` should say so.)
2. Which sources answer it? (A list should name those, not the newest five.)

Each question of research/ask/real (the 70, the 45 and the blind 40) goes to Jev once, with
the sources as state and one yes/no question for the whole set plus one per source. The
answers are compared with the hand labels, and with what the ask model (build 4) did.

    export TYPESAFE_API_KEY=...        # from https://console.typesafe.ai/keys
    research/.venv/bin/python research/jev/try_jev.py research/ask/real OUT.jsonl
    research/.venv/bin/python research/jev/try_jev.py --report OUT.jsonl ASK_ANSWERS.jsonl...
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

API = "https://api.typesafe.ai/v1/systemone"
SETS = {"real": "test.jsonl", "real extra": "extra.jsonl", "real blind": "blind.jsonl"}


def sources_of(example: dict) -> dict[str, str]:
    """The numbered sources in the prompt `ask` sent, by number."""
    block = example["messages"][0]["content"].split("Sources:\n", 1)[1].split("\n\nQuestion", 1)[0]
    found = {}
    for line in block.splitlines():
        match = re.match(r"\[(\d+)\] (.*)", line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def request(example: dict) -> dict:
    sources = sources_of(example)
    questions = {
        "answered": {
            "type": "noul",
            "instructions": "Do the `sources` answer the `question`, fully or in part?",
            "criteria": {
                "true": "At least one source gives the information the question asks for",
                "false": "No source gives it; they are only about related things",
            },
        }
    }
    for n in sources:
        questions[f"source_{n}"] = {
            "type": "noul",
            "instructions": f"Does source {n} in `sources` help answer the `question`?",
        }
    return {
        "model": "jev-latest",
        "state": {"question": example["question"], "sources": sources},
        "questions": questions,
    }


def ask_jev(root: Path, out: Path) -> None:
    key = os.environ.get("TYPESAFE_API_KEY") or Path("~/.typesafe_key").expanduser().read_text()
    headers = {"Authorization": f"Bearer {key.strip()}"}
    done = set()
    if out.exists():
        done = {(r["set"], r["question"]) for r in map(json.loads, out.open())}
    with httpx.Client(timeout=60, headers=headers) as client, out.open("a") as lines:
        for name, file in SETS.items():
            for example in map(json.loads, (root / file).open(encoding="utf-8")):
                if (name, example["question"]) in done:
                    continue
                start = time.time()
                response = client.post(API, json=request(example))
                if response.status_code != 200:
                    raise SystemExit(f"{response.status_code}: {response.text[:300]}")
                body = response.json()
                lines.write(
                    json.dumps(
                        {
                            "set": name,
                            "question": example["question"],
                            "kind": example["kind"],
                            "gold": example["gold"],
                            "sources": example["sources"],
                            "seconds": round(time.time() - start, 2),
                            "response": body,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                lines.flush()
                print(name, "|", example["question"], "|", round(time.time() - start, 2), "s")


def yes(answer: dict) -> float:
    """The probability of yes in a Noul answer, whatever its exact field name."""
    for field in ("noul", "value", "probability", "p"):
        if isinstance(answer.get(field), (int, float)):
            return float(answer[field])
    raise KeyError(f"no probability in {answer}")


def report(jev_file: Path, ask_files: list[Path]) -> None:
    declined = re.compile(r"\b(do(es)? not|don't|no (information|mention)|not (mention|say))\b")
    ask = {}
    for path in ask_files:
        for row in map(json.loads, path.open()):
            if row.get("model", "").startswith("ours build 4"):
                ask[(row["set"], row["question"])] = row["answer"]
    decide = {"jev": [0, 0], "ask": [0, 0]}
    pick = {"jev": [0, 0, 0], "ask": [0, 0, 0]}  # true positives, predicted, gold
    seconds = []
    for row in map(json.loads, jev_file.open()):
        answers = row["response"].get("answers", row["response"])
        answerable = row["kind"] != "refusal"
        p = yes(answers["answered"])
        decide["jev"][0] += (p >= 0.5) == answerable
        decide["jev"][1] += 1
        seconds.append(row["seconds"])
        chosen = {
            int(k.split("_")[1])
            for k, v in answers.items()
            if k.startswith("source_") and yes(v) >= 0.5
        }
        gold = set(row["gold"])
        if answerable:
            pick["jev"][0] += len(chosen & gold)
            pick["jev"][1] += len(chosen)
            pick["jev"][2] += len(gold)
        text = ask.get((row["set"], row["question"]))
        if text is not None:
            decide["ask"][0] += (not declined.search(text)) == answerable
            decide["ask"][1] += 1
            if answerable:
                cited = {int(n) for n in re.findall(r"\[(\d+)\]", text)}
                pick["ask"][0] += len(cited & gold)
                pick["ask"][1] += len(cited)
                pick["ask"][2] += len(gold)
    for who in ("jev", "ask"):
        right, total = decide[who]
        tp, predicted, gold = pick[who]
        print(
            f"{who}: says whether the sources answer: {right}/{total}; "
            f"picks sources: precision {tp / max(predicted, 1):.2f}, recall {tp / max(gold, 1):.2f}"
        )
    seconds.sort()
    print(f"jev: median {seconds[len(seconds) // 2]} s a question")


if __name__ == "__main__":
    if sys.argv[1] == "--report":
        report(Path(sys.argv[2]), [Path(p) for p in sys.argv[3:]])
    else:
        ask_jev(Path(sys.argv[1]), Path(sys.argv[2]))
