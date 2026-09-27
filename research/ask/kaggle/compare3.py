"""Kaggle job: grade `ask` models and other small open models the same way.

Every model gets the exact prompts `ask` sends, answers greedily (up to 200 new tokens, thinking
switched off where a model has it), and is graded on four sets:

- real: questions written the way people type them, through `ask`'s own search on a saved
  catalog, labelled by hand (research/ask/real);
- build 3: template questions from public data (lookup, listing, refusal; English and Thai);
- build 2 public and build 2 news: the sets the earlier models were graded on.

A model that cannot be loaded is reported and skipped. Writes scores.json and answers.jsonl.
`MODELS` is filled in by run.sh when the job is pushed."""

import collections
import glob
import json
import os
import random
import re
import subprocess
import sys
import time
import traceback

subprocess.run(
    [sys.executable, "-m", "pip", "install", "-q", "-U", "transformers", "accelerate"], check=True
)
subprocess.run(
    [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-q",
        "git+https://github.com/Fuyuki0/unlimitedpipe@v0.10.2",
    ],
    check=True,
)

import torch  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

from unlimitedpipe.sources.ask import unsupported_numbers  # noqa: E402

# label -> Hugging Face id, or "kernel:SLUG" for a model an earlier job trained; "|batch=N"
# after it answers N questions at a time instead of BATCH.
MODELS = {}
BATCH, NEW_TOKENS, PER_KIND = 16, 200, 20

DECLINED = re.compile(
    r"\b(do(es)? not|don't|doesn't|did not|didn't|cannot|can't|unable|isn't|aren't|none of|"
    r"no (information|mention|data|details|news|sources?|reports?)|there (is|are) no|"
    r"not (mention|say|cover|include|provide|contain|specify|state|list|report|give|have)|"
    r"nothing (about|on|regarding))\b|ไม่ได้|ไม่มี|ไม่พบ|ไม่ระบุ",
    re.IGNORECASE,
)
THAI = re.compile(r"[฀-๿]")


def folder(slug):
    """The mounted input folder of a dataset or job, whatever layout Kaggle uses."""
    for path in glob.glob("/kaggle/input/**/", recursive=True):
        if path.rstrip("/").rsplit("/", 1)[-1] == slug:
            return path
    raise FileNotFoundError(slug)


def rows(path):
    with open(path, encoding="utf-8") as lines:
        return [json.loads(line) for line in lines]


def sample(examples):
    groups = collections.defaultdict(list)
    for example in examples:
        groups[(example["kind"], example["lang"])].append(example)
    rng = random.Random(0)
    picked = []
    for key in sorted(groups):
        picked += rng.sample(groups[key], min(PER_KIND, len(groups[key])))
    return picked


def check(example, answer):
    """Pass or fail on each thing a good `ask` answer does."""
    prompt = example["messages"][0]["content"]
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
    checks = {"answered": bool(answer.strip())}
    gold = set(example["gold"])
    if example["kind"] == "refusal":
        checks["says not covered"] = bool(DECLINED.search(answer))
    else:
        need = 1 if example["kind"] == "lookup" else min(3, len(gold))
        checks["cites the right source"] = len(cited & gold) >= need
    checks["invents no number"] = not unsupported_numbers(answer, prompt)
    checks["cites only real sources"] = all(1 <= n <= example["sources"] for n in cited)
    if example["lang"] == "th":
        checks["answers in Thai"] = bool(THAI.search(answer))
    return checks


def listing_recall(example, answer):
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
    gold = set(example["gold"])
    return len(cited & gold) / min(5, len(gold))


def load_sets():
    real = glob.glob(folder("unlimitedpipe-ask-real") + "**/test.jsonl", recursive=True)[0]
    sets = {"real": rows(real)}
    for name, slug in (
        ("build 3", "unlimitedpipe-ask-sft-public-v3"),
        ("build 2 public", "unlimitedpipe-ask-sft-public"),
        ("build 2 news", "unlimitedpipe-ask-sft"),
    ):
        path = glob.glob(folder(slug) + "**/test.jsonl", recursive=True)[0]
        sets[name] = sample(rows(path))
    return sets


def model_path(source):
    source = source.split("|")[0]
    if source.startswith("kernel:"):
        return glob.glob(folder(source[7:]) + "**/ask-merged", recursive=True)[0]
    return source


def generate(tok, model, prompts, size=BATCH):
    tok.padding_side = "left"
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    texts = []
    for prompt in prompts:
        messages = [{"role": "user", "content": prompt}]
        try:
            text = tok.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
            )
        except TypeError:
            text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        texts.append(text)
    answers = []
    for i in range(0, len(texts), size):
        answers += run(tok, model, texts[i : i + size])
    return answers


def run(tok, model, texts):
    """Answers for one batch; a batch too big for the GPU is split in two."""
    try:
        batch = tok(texts, return_tensors="pt", padding=True, add_special_tokens=False)
        batch = {k: v.to("cuda") for k, v in batch.items()}
        with torch.no_grad():
            out = model.generate(
                **batch, max_new_tokens=NEW_TOKENS, do_sample=False, pad_token_id=tok.pad_token_id
            )
    except torch.cuda.OutOfMemoryError:
        torch.cuda.empty_cache()
        if len(texts) == 1:
            raise
        half = len(texts) // 2
        return run(tok, model, texts[:half]) + run(tok, model, texts[half:])
    answers = []
    for row in out[:, batch["input_ids"].shape[1] :]:
        answer = tok.decode(row, skip_special_tokens=True)
        answers.append(re.sub(r"<think>.*?</think>", "", answer, flags=re.S).strip())
    return answers


sets = load_sets()
print({k: len(v) for k, v in sets.items()}, flush=True)
scores, answers_out = {}, []
for label, source in MODELS.items():
    start = time.time()
    try:
        path = model_path(source)
        tok = AutoTokenizer.from_pretrained(path)
        model = AutoModelForCausalLM.from_pretrained(path, torch_dtype=torch.float16)
        model = model.to("cuda").eval()
    except Exception as exc:
        print(f"{label}: could not load ({exc})", flush=True)
        traceback.print_exc()
        scores[label] = {"error": str(exc)[:300]}
        continue
    params = sum(p.numel() for p in model.parameters())
    scores[label] = {"parameters": params, "source": source}
    for set_name, examples in sets.items():
        try:
            size = int(source.split("|batch=")[1]) if "|batch=" in source else BATCH
            answers = generate(tok, model, [e["messages"][0]["content"] for e in examples], size)
        except Exception as exc:
            print(f"{label} | {set_name}: failed ({exc})", flush=True)
            scores[label][set_name] = {"error": str(exc)[:300]}
            continue
        passed, fails, recall = 0, collections.Counter(), []
        by_kind = collections.defaultdict(lambda: [0, 0])
        for example, answer in zip(examples, answers, strict=True):
            checks = check(example, answer)
            ok = all(checks.values())
            passed += ok
            fails.update(k for k, v in checks.items() if not v)
            by_kind[example["kind"]][0] += ok
            by_kind[example["kind"]][1] += 1
            if example["kind"] == "listing":
                recall.append(listing_recall(example, answer))
            answers_out.append(
                {
                    "model": label,
                    "set": set_name,
                    "kind": example["kind"],
                    "lang": example["lang"],
                    "question": example["question"],
                    "answer": answer,
                    "checks": checks,
                }
            )
        scores[label][set_name] = {
            "passed": passed,
            "of": len(examples),
            "by_kind": {k: v for k, v in by_kind.items()},
            "failed_checks": dict(fails),
            "listing_recall": round(sum(recall) / len(recall), 3) if recall else None,
        }
        print(f"{label} | {set_name}: {passed}/{len(examples)} {dict(fails)}", flush=True)
    scores[label]["minutes"] = round((time.time() - start) / 60, 1)
    del model
    torch.cuda.empty_cache()
    with open("/kaggle/working/scores.json", "w") as out:
        json.dump(scores, out, ensure_ascii=False, indent=1)

with open("/kaggle/working/scores.json", "w") as out:
    json.dump(scores, out, ensure_ascii=False, indent=1)
with open("/kaggle/working/answers.jsonl", "w", encoding="utf-8") as out:
    for a in answers_out:
        out.write(json.dumps(a, ensure_ascii=False) + "\n")
print("done", os.listdir("/kaggle/working"), flush=True)
