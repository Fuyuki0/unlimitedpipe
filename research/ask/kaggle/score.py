"""Kaggle job: grade the original and the trained ask model the same way, on the GPU.

Both answer the same test examples (up to PER_KIND per kind and language) and the real
questions, greedily, with at most 150 new tokens, as `ask` asks small models; answers are
checked like research/ask/score.py. Writes scores.json and answers.jsonl."""

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

PER_KIND = 30
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


tests = [json.loads(line) for line in open(find("test.jsonl"), encoding="utf-8")]
groups = collections.defaultdict(list)
for example in tests:
    groups[(example["kind"], example["lang"])].append(example)
rng = random.Random(0)
chosen = [
    e for key in sorted(groups) for e in rng.sample(groups[key], min(PER_KIND, len(groups[key])))
]
real = [json.loads(line) for line in open(find("real-questions.jsonl"), encoding="utf-8")]
real = [r for r in real if r.get("prompt")]
merged = glob.glob("/kaggle/input/**/ask-merged", recursive=True)[0]

scores, answers = {}, []
for name, path in (("original qwen2.5 0.5B", "Qwen/Qwen2.5-0.5B-Instruct"), ("trained", merged)):
    tok = AutoTokenizer.from_pretrained(path)
    model = AutoModelForCausalLM.from_pretrained(path, torch_dtype=torch.float16).to("cuda").eval()

    def generate(prompt, model=model, tok=tok):
        text = tok.apply_chat_template(
            [{"role": "user", "content": prompt}], tokenize=False, add_generation_prompt=True
        )
        ids = tok(text, return_tensors="pt").input_ids.to("cuda")
        with torch.no_grad():
            out = model.generate(ids, max_new_tokens=150, do_sample=False)
        return tok.decode(out[0][ids.shape[1] :], skip_special_tokens=True).strip()

    results = collections.defaultdict(list)
    fails = collections.Counter()
    for example in chosen:
        answer = generate(example["messages"][0]["content"])
        checks = check(example, answer)
        results[f"{example['kind']} {example['lang']}"].append(all(checks.values()))
        fails.update(k for k, ok in checks.items() if not ok)
        answers.append(
            {
                "model": name,
                "question": example["question"],
                "kind": example["kind"],
                "answer": answer,
                "checks": checks,
            }
        )
    for r in real:
        answers.append(
            {
                "model": name,
                "question": r["question"],
                "kind": "real",
                "answer": generate(r["prompt"]),
            }
        )
    total = [ok for oks in results.values() for ok in oks]
    scores[name] = {
        "passed": sum(total),
        "of": len(total),
        "by_kind": {k: f"{sum(v)}/{len(v)}" for k, v in sorted(results.items())},
        "failed_checks": dict(fails),
    }
    print(name, json.dumps(scores[name], ensure_ascii=False), flush=True)
    del model
    torch.cuda.empty_cache()

json.dump(scores, open("/kaggle/working/scores.json", "w"), ensure_ascii=False, indent=1)
with open("/kaggle/working/answers.jsonl", "w", encoding="utf-8") as out:
    for a in answers:
        out.write(json.dumps(a, ensure_ascii=False) + "\n")
print("done", flush=True)
