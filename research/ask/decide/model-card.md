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

| Model | Blind (40) | Blind 2 (42) | Real (70) | More English (45) | Median time on 2 CPUs |
| --- | --- | --- | --- | --- | --- |
| **unlimitedpipe/decide-0.5b, build 6 (this model)** | **36 (90%)** | 28 (67%) | 66 (94%) | 44 (97%) | 3 to 5 s |
| unlimitedpipe/decide-0.5b, build 5 | 35 (87%) | 29 (69%) | 65 (93%) | 45 (100%) | 3 to 5 s |
| unlimitedpipe/ask-0.5b, build 4 (writes its answers) | 35 (87%) | | 67 (95%) | 45 (100%) | about 13 s |
| Qwen3.5 2B (writes its answers) | 35 (87%) | | 45 (64%) | 29 (64%) | |
| Phi-4 mini (writes its answers) | 34 (85%) | | 42 (60%) | 34 (75%) | |
| Qwen3.5 4B (writes its answers) | 31 (77%) | | 56 (80%) | 39 (86%) | |

Graded strictly (corrected 2026-09-28): an answer that says the sources do not answer fails
when they do, even though it cites the right source as "the closest". The first version of this
card counted those, and gave build 6 32 of 42 on blind set 2.

Read the blind columns first: those questions were written before the model was trained and
never used to build or tune it. The real and English sets shaped these models and flatter them.

Build 6 practised questions about a source's topic that ask for something no source says
("hurricane death toll", "python 3.15 release date"). Of the 28 questions in all four sets
that the sources do not answer, it says so for 21 (build 5: 14). It pays for that with three
questions it now wrongly calls not covered ("stablecoin supply change", "cyber attack disclosed
to sec").

When the decision was 95% sure or more (191 of 197 answers), it was right 174 times; below
that, 5 of 6.

## Limits

- 7 of the 28 "not covered" questions still get an answer, with high confidence ("tsunami
  warning?" with a story about a "Himalayan tsunami", "linux kernel release" with other
  releases).
- For some listings it picks all five sources it may, including ones that do not answer.
- The answers read as lists of headlines; a larger model can explain them.
- It knows one prompt, `unlimitedpipe.decide.PROMPT`.

## Training

Qwen2.5 0.5B Instruct with LoRA (r=16, all linear layers), one pass over 23,244 decision
examples built from public data only (works of the US federal government and UnlimitedPipe's
own sentences from open data; about 30% of them "not covered"), 156 minutes on one T4.
Build 5 is on the `build-5` branch.

License: Apache 2.0, as its base model.
