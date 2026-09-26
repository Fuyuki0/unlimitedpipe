# A small model trained for `unlimited ask`

**Question.** `ask` gives a small local model numbered sources and a question. Small models
often answer loosely: they skip citations, invent numbers, or answer when the sources do not
cover the question. Can a 0.5B model trained on examples of good answers do better, and still
run on a laptop?

## How

1. [`build.py`](build.py) turns the catalog into examples: the exact prompt `ask` sends
   (same wording, same source ranking) and an answer written from the sources by templates,
   so each answer is correct by construction. Four kinds, each in English and Thai: lookup
   (answer from one item, cite it), listing (several items, cite them), refusal (the key word
   is in no source: say so and give the closest item). 10% of items are only ever tested.
   Build 1 (catalog of 2026-09-26): 7,016 examples to learn from, 795 to test.
2. [`score.py`](score.py) grades any Ollama model on the test examples: right citation, no
   citation of a source that does not exist, no invented number, Thai answers to Thai
   questions, and plain refusals.
3. [`train_kaggle.ipynb`](train_kaggle.ipynb) trains Qwen2.5 0.5B Instruct with LoRA on a free
   Kaggle GPU and uploads the model and a GGUF file for Ollama.
4. [`install_model.sh`](install_model.sh) adds the trained model to Ollama as
   `unlimitedpipe-ask:0.5b`; then `unlimited ask "..." --model unlimitedpipe-ask:0.5b`.

The examples hold publishers' headlines, so the dataset (`unlimitedpipe/ask-sft`) and the
trained model are private; the code and the scores are public.

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
