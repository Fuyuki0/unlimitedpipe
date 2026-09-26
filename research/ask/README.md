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

Baseline, `qwen2.5:0.5b` as `ask` uses it today: see below once scored. Trained model: to come.
