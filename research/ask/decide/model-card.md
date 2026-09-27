---
license: apache-2.0
base_model: Qwen/Qwen2.5-0.5B-Instruct
language: [en, th]
tags: [gguf, ollama, rag, citations, decision-model, unlimitedpipe]
datasets: [unlimitedpipe/decide-sft-public]
pipeline_tag: text-generation
---

# unlimitedpipe/decide-0.5b

A 0.5B decision model for [UnlimitedPipe](https://github.com/Fuyuki0/unlimitedpipe)'s `ask`: given
numbered sources and a question, it replies with the sources that answer it (`USE 2 5`) or
`NONE`, and nothing else. UnlimitedPipe then writes the answer from those sources' own titles,
dates and summaries, so the answer holds no word or number the sources do not, and the
probability of the first token says how sure the decision was.

```bash
ollama pull hf.co/unlimitedpipe/decide-0.5b-GGUF
unlimited ask "any big crypto hacks this week?"      # ask uses it by itself
```

`unlimited setup` installs it for you.

## Scores

Questions written the way people type them, put through `ask`'s own search and labelled by hand
([`research/ask`](https://github.com/Fuyuki0/unlimitedpipe/tree/main/research/ask)); each
decision is graded by the answer the code writes from it, the same way as models that write
their answers:

| Model | Real (70) | More English (45) | Blind (40) | Median time on 2 CPUs |
| --- | --- | --- | --- | --- |
| **unlimitedpipe/decide-0.5b (this model)** | **66 (94%)** | **45 (100%)** | **35 (87%)** | **4.6 s** |
| unlimitedpipe/ask-0.5b, build 4 (writes its answers) | 67 (95%) | 45 (100%) | 35 (87%) | about 13 s |
| Qwen3.5 4B (writes its answers) | 56 (80%) | 39 (86%) | | |

The blind questions were written after both 0.5B models were trained and used for neither.
When the decision was 95% sure or more (150 of 155 answers), it was right 144 times; below that,
2 of 5.

## Limits

- It says "the sources do not answer this" too rarely: 10 of 16 questions the sources did not
  answer, usually with high confidence ("tsunami warning?" with a story about a "Himalayan
  tsunami"). This is the next thing to train.
- The answers read as lists of headlines; a larger model can explain them.
- It knows one prompt, `unlimitedpipe.decide.PROMPT`.

## Training

Qwen2.5 0.5B Instruct with LoRA (r=16, all linear layers), one pass over 19,516 decision
examples built from public data only (works of the US federal government and UnlimitedPipe's
own sentences from open data; "not covered" examples counted twice), 135 minutes on one T4.

License: Apache 2.0, as its base model.
