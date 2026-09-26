"""Kaggle job: fine-tune Qwen2.5 0.5B Instruct with LoRA on the ask examples, merge, and
write an 8-bit GGUF file for Ollama into /kaggle/working. Pushed by `run.sh`; the examples
come from a private Kaggle dataset, so no token is needed here.

A plain training loop on transformers and PEFT (no TRL, whose newest versions broke twice on
Kaggle's image); the loss is on the answer only, not on the sources."""

import glob
import json
import math
import random
import subprocess
import sys
import time

# Kaggle's image carries an old torchao that new PEFT refuses; LoRA here does not need it.
subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "-q", "torchao"], check=False)
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "peft>=0.13"], check=True)

import torch  # noqa: E402
from peft import LoraConfig, get_peft_model  # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: E402

BASE, EPOCHS, BATCH, ACCUMULATE, LR, MAX_TOKENS = "Qwen/Qwen2.5-0.5B-Instruct", 1, 2, 8, 2e-4, 1536
device = "cuda" if torch.cuda.is_available() else "cpu"
print("GPU:", torch.cuda.get_device_name(0) if device == "cuda" else "none", flush=True)
random.seed(0)
torch.manual_seed(0)


def read(name):
    path = glob.glob(f"/kaggle/input/**/{name}.jsonl", recursive=True)[0]
    return [json.loads(line) for line in open(path, encoding="utf-8")]


tok = AutoTokenizer.from_pretrained(BASE)
tok.padding_side = "right"


def encode(example):
    """Prompt tokens are masked out of the loss (-100); the answer and its end are learned."""
    prompt = tok.apply_chat_template(
        example["messages"][:1], tokenize=False, add_generation_prompt=True
    )
    answer = example["messages"][1]["content"] + "<|im_end|>\n"
    p = tok(prompt, add_special_tokens=False)["input_ids"]
    a = tok(answer, add_special_tokens=False)["input_ids"]
    if len(p) + len(a) > MAX_TOKENS:
        return None
    return {"ids": p + a, "labels": [-100] * len(p) + a}


train = [e for e in map(encode, read("train")) if e]
test = [e for e in map(encode, read("test")) if e][:200]
print(f"examples: {len(train)} train, {len(test)} test", flush=True)


def batches(rows, size, shuffle):
    rows = sorted(rows, key=lambda r: len(r["ids"]))  # similar lengths pad less
    groups = [rows[i : i + size] for i in range(0, len(rows), size)]
    if shuffle:
        random.shuffle(groups)
    for group in groups:
        width = max(len(r["ids"]) for r in group)
        ids = torch.full((len(group), width), tok.pad_token_id)
        labels = torch.full((len(group), width), -100)
        mask = torch.zeros((len(group), width), dtype=torch.long)
        for i, r in enumerate(group):
            ids[i, : len(r["ids"])] = torch.tensor(r["ids"])
            labels[i, : len(r["labels"])] = torch.tensor(r["labels"])
            mask[i, : len(r["ids"])] = 1
        yield ids.to(device), labels.to(device), mask.to(device)


model = AutoModelForCausalLM.from_pretrained(BASE, torch_dtype=torch.float32).to(device)
model = get_peft_model(
    model,
    LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        task_type="CAUSAL_LM",
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
    ),
)
model.print_trainable_parameters()
# Recompute activations instead of storing them: a batch of 1,536 tokens fits a T4 with room.
model.gradient_checkpointing_enable()
model.enable_input_require_grads()
optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=LR)
steps = EPOCHS * math.ceil(len(train) / BATCH / ACCUMULATE)
warmup = 20
schedule = torch.optim.lr_scheduler.LambdaLR(
    optimizer,
    lambda s: min(1, (s + 1) / warmup) * 0.5 * (1 + math.cos(math.pi * min(s, steps) / steps)),
)
scaler = torch.amp.GradScaler(enabled=device == "cuda")


def evaluate():
    model.eval()
    total, count = 0.0, 0
    with torch.no_grad():
        for ids, labels, mask in batches(test, BATCH, shuffle=False):
            with torch.autocast(device, dtype=torch.float16, enabled=device == "cuda"):
                total += model(input_ids=ids, attention_mask=mask, labels=labels).loss.item()
            count += 1
    model.train()
    return total / max(count, 1)


start = time.time()
print(f"eval loss before: {evaluate():.3f}", flush=True)
model.train()
step = 0
for epoch in range(EPOCHS):
    for n, (ids, labels, mask) in enumerate(batches(train, BATCH, shuffle=True), 1):
        with torch.autocast(device, dtype=torch.float16, enabled=device == "cuda"):
            loss = model(input_ids=ids, attention_mask=mask, labels=labels).loss / ACCUMULATE
        scaler.scale(loss).backward()
        if n % ACCUMULATE == 0:
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            optimizer.zero_grad()
            schedule.step()
            step += 1
            if step % 25 == 0:
                print(
                    f"step {step}/{steps} loss {loss.item() * ACCUMULATE:.3f} "
                    f"{(time.time() - start) / 60:.0f} min",
                    flush=True,
                )
after = evaluate()
print(f"eval loss after: {after:.3f}; train minutes {(time.time() - start) / 60:.0f}", flush=True)

model.eval()
samples = []
for example in read("test")[:4]:
    prompt = tok.apply_chat_template(
        example["messages"][:1], tokenize=False, add_generation_prompt=True
    )
    ids = tok(prompt, return_tensors="pt", add_special_tokens=False)["input_ids"].to(device)
    with torch.no_grad():
        out = model.generate(ids, max_new_tokens=120, do_sample=False)
    samples.append(
        {
            "question": example["question"],
            "answer": tok.decode(out[0][ids.shape[1] :], skip_special_tokens=True),
            "expected": example["messages"][1]["content"],
        }
    )
json.dump(
    {"eval_loss_after": after, "samples": samples},
    open("/kaggle/working/report.json", "w"),
    ensure_ascii=False,
    indent=1,
)
print(json.dumps(samples, ensure_ascii=False, indent=1), flush=True)

merged = model.merge_and_unload()
merged.save_pretrained("/kaggle/working/ask-merged", safe_serialization=True)
tok.save_pretrained("/kaggle/working/ask-merged")
subprocess.run(
    "git clone -q --depth 1 https://github.com/ggml-org/llama.cpp /tmp/llama.cpp && "
    f"{sys.executable} -m pip install -q /tmp/llama.cpp/gguf-py sentencepiece && "
    f"{sys.executable} /tmp/llama.cpp/convert_hf_to_gguf.py /kaggle/working/ask-merged "
    "--outtype q8_0 --outfile /kaggle/working/ask-0.5b-q8_0.gguf",
    shell=True,
    check=True,
)
print("done", flush=True)
