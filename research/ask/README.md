# A small model trained for `unlimited ask`

**Question.** `ask` gives a small local model numbered sources and a question. Small models
often answer loosely: they skip citations, invent numbers, or answer when the sources do not
cover the question. Can a 0.5B model trained on examples of good answers do better, and still
run on a laptop?

## How

1. [`build.py`](build.py) turns the catalog into examples: the exact prompt `ask` sends
   (same wording, same search, same time window, same number of sources) and an answer
   written from the sources by templates, so each answer is correct by construction. Three
   kinds, each in English and Thai, asked formally and the way people type: lookup (answer
   from one item, cite it), listing (every matching source up to five, each cited), refusal
   (the key word is in no source: say so and give the closest item). One in ten items and
   topics is only ever tested. `--public` uses public data only, plus Federal Register
   documents from [unlimitedpipe/public-records](https://huggingface.co/datasets/unlimitedpipe/public-records).
2. [`real/`](real): 70 questions typed the way people type them, put through `ask`'s own search
   on a saved catalog and labelled by hand: the honest test, as the template test sets come
   from the same patterns the model learns from.
3. [`kaggle/run3.sh`](kaggle/run3.sh) trains Qwen2.5 0.5B Instruct with LoRA on a free Kaggle
   GPU ([`kaggle/train.py`](kaggle/train.py), GGUF file for Ollama included) and has any
   models answer every test set there ([`kaggle/compare3.py`](kaggle/compare3.py)).
4. [`grade.py`](grade.py) grades the answers the same way for every model: a source that
   answers is cited (three of the matching ones for a list), not every source is cited, the
   sources not covering the question is said plainly, no number is invented, no source that
   does not exist is cited, and Thai is answered in Thai.

Built from news feeds, examples hold publishers' headlines, so that dataset
(`unlimitedpipe/ask-sft`) and the model trained on it are private; the public model is trained
on public data only. The code and the scores are public.

## Results

**Baseline: `qwen2.5:0.5b` as `ask` uses it today passes 11 of 52 test questions (21%)**, up
to 10 per kind and language, 8.6 s per answer on a 2-core CPU:

| Kind | English | Thai |
| --- | --- | --- |
| lookup | 2/10 | 0/10 |
| listing | 4/6 | 0/6 |
| refusal | 1/10 | 4/10 |

It mostly leaves out the `[n]` citations the prompt asks for (25 answers), even when it names
the right items, and answers anyway when the sources do not cover the question (15). In Thai
it often repeats itself and slips into Chinese words.

**Build 1, trained** (LoRA r=16 on Qwen2.5 0.5B Instruct, one pass over 7,016 examples, 24
minutes on Kaggle's free T4; test loss 1.013 to 0.012). Graded on Kaggle, both models the
same way (greedy, 150 new tokens, 16-bit) on 132 test questions:

| Kind | Original | Trained |
| --- | --- | --- |
| lookup (en / th) | 1/30, 0/30 | 27/30, 26/30 |
| listing (en / th) | 0/6, 0/6 | 5/6, 5/6 |
| refusal (en / th) | 2/30, 2/30 | 30/30, 30/30 |
| **all** | **5/132 (4%)** | **123/132 (93%)** |

The test questions come from the same templates as the training ones, so real questions are
the honest check. On nine, asked the way people ask them, the trained model cited its sources
every time and invented nothing, where the original said "no new activist stakes" when there
were three, mixed up two crypto hacks, gave a Thai answer dated 2564 BE (2021) for 2026, and
rambled about the Bangkok flood. But build 1 had a bug: its templates cut what came before a
colon, meant for outlet names ("BBC Africa: ..."), which also cut subjects ("Bitcoin (BTC)
price: $84,056.11" became "$84,056.11"), and the model learned to drop them. Build 2 keeps
titles whole.

**Build 2** (titles kept whole, 7,606 examples, 30 minutes on the T4, test loss 0.952 to
0.010): **124/132 (94%)** against the original's 5/132, on the same grader. On the real
questions the subjects are back ("Bitcoin (BTC) price: $84,056.11 (2026-09-26) [1]"; the
Bitget hack by name; the companies of activist stakes), every answer cites its sources, and
Thai questions get clean Thai answers.

It is installed on the author's machine as `unlimitedpipe-ask:0.5b` (8-bit GGUF, 531 MB), and
`ask` now prefers it over small general models when it is there. Its style is extractive: it
answers with the sources' own headlines, which is what makes it reliable, and also what keeps
it from explaining (a 3B+ general model explains better, but cites and declines worse).

**The public model** (the same recipe on public data only: works of the US federal government
and UnlimitedPipe's own sentences from open data, no news; 6,974 examples), graded with the
two others on both test sets:

| Model | News it never saw (92) | Public data (84) |
| --- | --- | --- |
| Qwen2.5 0.5B Instruct | 5 (5%) | 5 (6%) |
| Trained on news (private) | 84 (91%) | 81 (96%) |
| **Trained on public data** | **80 (87%)** | **82 (98%)** |

The model trained without a single news item nearly matches the one trained on news, on news:
it learned the skill (cite the right source, decline what is not covered), not the topics. Its
misses are incomplete lists (one cited item where two or three were there), not inventions.
It is published as [unlimitedpipe/ask-0.5b-GGUF](https://huggingface.co/unlimitedpipe/ask-0.5b-GGUF)
with its data, [unlimitedpipe/ask-sft-public](https://huggingface.co/datasets/unlimitedpipe/ask-sft-public),
and `unlimited setup` installs it.

## Build 3: lists, and real questions (2026-09-27)

Build 2 had 56 list examples out of 6,974, always 5 sources (`ask` gives 10 by default), and
only formal questions. It passed 97% of its own template tests but, on the real questions,
only half: asked "whats new with bitget" or "ข่าวไทยวันนี้มีอะไรบ้าง", it gave one item or
said the sources did not cover it.

Build 3 (public data only): 18,468 examples to learn from (7,719 lists, 8,448 lookups, 2,301
refusals; 8,446 typed casually), from the public catalog of 2026-09-27 and 30,185 Federal
Register documents of 2025 and 2026, with `ask`'s own search and 10, 5 or 3 sources as `ask`
gives. 146 minutes on Kaggle's T4, test loss 0.925 to 0.008.

Every model below answered the same prompts on Kaggle (greedy, up to 200 new tokens, thinking
off, 16-bit) and was graded by `grade.py`:

| Model | Parameters | Real (70) | Build 3 test (120) | Build 2 public (84) | Build 2 news (92) |
| --- | --- | --- | --- | --- | --- |
| **ask-0.5b build 3** | **0.5B** | **57 (81%)** | **110 (91%)** | 78 (92%) | **87 (94%)** |
| Qwen3.5 4B | 4.2B | 56 (80%) | 57 (47%) | 71 (84%) | 62 (67%) |
| Qwen3.5 2B | 1.9B | 45 (64%) | 50 (41%) | 54 (64%) | 52 (56%) |
| Phi-4 mini | 3.8B | 43 (61%) | 31 (25%) | 35 (41%) | 34 (36%) |
| Gemma 4 E2B | 5.1B | 43 (61%) | 51 (42%) | 51 (60%) | 50 (54%) |
| Granite 4.1 3B | 3.4B | 42 (60%) | 37 (30%) | 43 (51%) | 44 (47%) |
| Llama 3.2 3B | 3.2B | 37 (53%) | 36 (30%) | 48 (57%) | 54 (58%) |
| LFM2.5 1.2B | 1.2B | 37 (53%) | 22 (18%) | 4 (4%) | 10 (10%) |
| ask-0.5b build 2 | 0.5B | 36 (51%) | 74 (61%) | **82 (97%)** | 77 (83%) |
| SmolLM3 3B | 3.1B | 35 (50%) | 44 (36%) | 34 (40%) | 38 (41%) |
| Qwen3.5 0.8B | 0.8B | 22 (31%) | 37 (30%) | 46 (54%) | 42 (45%) |
| Llama 3.2 1B | 1.2B | 21 (30%) | 37 (30%) | 31 (36%) | 42 (45%) |
| Gemma 3 1B | 1.0B | 9 (13%) | 14 (11%) | 16 (19%) | 19 (20%) |
| Qwen2.5 0.5B Instruct (base) | 0.5B | 0 (0%) | 4 (3%) | 4 (4%) | 3 (3%) |

On the real questions, build 3 passes 39 of 48 lists (build 2: 18), 12 of 14 lookups and 6
of 8 refusals. Its misses: a bare topic ("openai news", "ข่าวญี่ปุ่นล่าสุด") often gets one
item where a list was wanted; "nasa image of the day" gets a list where one was wanted; and it
gave a price when asked for next year's. Larger general models word their answers better and
explain; this one quotes its sources.

Two notes on the other models. Qwen3.5 4B ran out of GPU memory at 16 answers at a time and
was run at 4; Gemma 4 E2B gave empty answers when batched and was run one at a time. The first
grader counted a list as right when it cited three matching sources, which a model citing all
ten always did; `grade.py` also fails citing more than two sources that do not answer.

Build 3 is published as [unlimitedpipe/ask-0.5b-GGUF](https://huggingface.co/unlimitedpipe/ask-0.5b-GGUF)
(build 2 on its `build-2` branch), with its data,
[unlimitedpipe/ask-sft-public](https://huggingface.co/datasets/unlimitedpipe/ask-sft-public).
