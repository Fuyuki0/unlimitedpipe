"""Kaggle job: grade the original, the news-trained and the public-data-trained ask models
the same way, on both test sets (news and public data).

Every model answers the same test examples (up to PER_KIND per kind and language from each
set), greedily, with at most 150 new tokens, as `ask` asks small models; answers are checked
like research/ask/score.py. Writes scores.json and answers.jsonl."""

import collections
import glob
import json
import random
import re
import subprocess
import sys

subprocess.run(
    [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-q",
        "git+https://github.com/Fuyuki0/unlimitedpipe@v0.9.1",
    ],
    check=True,
)

import torch  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

from unlimitedpipe.sources.ask import unsupported_numbers  # noqa: E402

REFUSAL = re.compile(
    r"\b(not|no|none|nothing|don't|doesn't|does not|do not|cannot|can't)\b|ไม่", re.IGNORECASE
)
THAI = re.compile(r"[฀-๿]")


def find(name):
    return glob.glob(f"/kaggle/input/**/{name}", recursive=True)[0]


def check(example, answer):
    prompt = example["messages"][0]["content"]
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
    checks = {"answered": bool(answer.strip())}
    if example["kind"] == "refusal":
        checks["says not covered"] = bool(REFUSAL.search(answer))
    else:
        need = 1 if example["kind"] == "lookup" else 2
        checks["cites the right source"] = len(cited & set(example["gold"])) >= need
        checks["cites only real sources"] = all(1 <= n <= example["sources"] for n in cited)
        checks["invents no number"] = not unsupported_numbers(answer, prompt)
    if example["lang"] == "th":
        checks["answers in Thai"] = bool(THAI.search(answer))
    return checks


PER_KIND = 20


def dir_named(part):
    """A mounted input folder whose path contains `part` (Kaggle's mount layout varies)."""
    return next(p for p in glob.glob("/kaggle/input/**/", recursive=True) if part in p)


def sample(path):
    rows = [json.loads(line) for line in open(path, encoding="utf-8")]
    groups = collections.defaultdict(list)
    for example in rows:
        groups[(example["kind"], example["lang"])].append(example)
    rng = random.Random(0)
    return [
        e
        for key in sorted(groups)
        for e in rng.sample(groups[key], min(PER_KIND, len(groups[key])))
    ]


sets = {
    "news (the catalog as people use it)": sample(
        glob.glob(dir_named("ask-sft/") + "**/test.jsonl", recursive=True)[0]
    ),
    "public data": sample(
        glob.glob(dir_named("ask-sft-public") + "**/test.jsonl", recursive=True)[0]
    ),
}
models = {
    "original qwen2.5 0.5B": "Qwen/Qwen2.5-0.5B-Instruct",
    "trained on news (private)": glob.glob(
        dir_named("ask-train/") + "**/ask-merged", recursive=True
    )[0],
    "trained on public data": glob.glob(
        dir_named("ask-public-train") + "**/ask-merged", recursive=True
    )[0],
}
scores, answers = {}, []
for name, path in models.items():
    tok = AutoTokenizer.from_pretrained(path)
    model = AutoModelForCausalLM.from_pretrained(path, torch_dtype=torch.float16).to("cuda").eval()
    for set_name, examples in sets.items():
        passed, fails = 0, collections.Counter()
        for example in examples:
            text = tok.apply_chat_template(
                example["messages"][:1], tokenize=False, add_generation_prompt=True
            )
            ids = tok(text, return_tensors="pt").input_ids.to("cuda")
            with torch.no_grad():
                out = model.generate(ids, max_new_tokens=150, do_sample=False)
            answer = tok.decode(out[0][ids.shape[1] :], skip_special_tokens=True).strip()
            checks = check(example, answer)
            passed += all(checks.values())
            fails.update(k for k, ok in checks.items() if not ok)
            answers.append(
                {
                    "model": name,
                    "set": set_name,
                    "question": example["question"],
                    "answer": answer,
                    "checks": checks,
                }
            )
        scores[f"{name} | {set_name}"] = {
            "passed": passed,
            "of": len(examples),
            "failed_checks": dict(fails),
        }
        print(name, "|", set_name, f"{passed}/{len(examples)}", dict(fails), flush=True)
    del model
    torch.cuda.empty_cache()

json.dump(scores, open("/kaggle/working/scores.json", "w"), ensure_ascii=False, indent=1)
with open("/kaggle/working/answers.jsonl", "w", encoding="utf-8") as out:
    for a in answers:
        out.write(json.dumps(a, ensure_ascii=False) + "\n")
print("done", flush=True)
