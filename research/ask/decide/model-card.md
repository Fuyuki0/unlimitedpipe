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
unlimited ask "earthquakes in japan in 2024"         # and questions about the past
```

`unlimited setup` installs it for you.

## Scores

Questions written the way people type them, put through `ask`'s own search and labelled by hand
([`research/ask`](https://github.com/Fuyuki0/unlimitedpipe/tree/main/research/ask)); each
decision is graded strictly by the answer the code writes from it: an answer that says the
sources do not answer fails when they do.

| Model | Blind (40) | Blind 2 (42) | Blind 3, the past (43) | Real (70) | More English (45) | Median time on 2 CPUs |
| --- | --- | --- | --- | --- | --- | --- |
| **unlimitedpipe/decide-0.5b, build 8 (this model)** | **37 (92%)** | 28 (67%) | **37 (86%)** | **67 (96%)** | 44 (97%) | about 5 s |
| unlimitedpipe/decide-0.5b, build 7 | 36 (90%) | 27 (64%) | 37 (86%) | 67 (96%) | 44 (97%) | about 4.5 s |
| unlimitedpipe/decide-0.5b, build 6 | 36 (90%) | 28 (67%) | 26 (60%) | 66 (94%) | 44 (97%) | 3 to 5 s |
| unlimitedpipe/decide-0.5b, build 5 | 35 (87%) | 29 (69%) | | 65 (93%) | 45 (100%) | 3 to 5 s |
| unlimitedpipe/ask-0.5b, build 4 (writes its answers) | 35 (87%) | | | 67 (95%) | 45 (100%) | about 13 s |
| Qwen3.5 2B (writes its answers) | 35 (87%) | | | 45 (64%) | 29 (64%) | |
| Phi-4 mini (writes its answers) | 34 (85%) | | | 42 (60%) | 34 (75%) | |
| Qwen3.5 4B (writes its answers) | 31 (77%) | | | 56 (80%) | 39 (86%) | |

Read the blind columns first: those questions were written before the model was trained and
never used to build it. Two caveats for blind 3, 46 questions about the past ("earthquakes in
japan in 2024", "ronin hack", "cpi march 2021"): three of them ("data breaches in 2024", "crypto
hacks in 2022", "ipo filings in 2021") also appear word for word among build 7's generated
training questions, so it is scored on the other 43; and build 6's misses on it are what build 7
was made to fix, so it flatters builds 7 and 8. The real and English sets shaped these models too.

Build 8 adds 22,821 questions about history added to the catalog on 2026-10-04: hurricanes since
1851, typhoons since 1951, solar storms, company earnings releases, UK, Canadian and EU
government records, US federal contracts and grants, and crypto market events. On
the five sets it passes 216 of 243 against build 7's 214. It wrongly calls a covered question "not
covered" less often (8 times across the four sets other than blind 3, against 14), but says "not
covered" when nothing answers less often too (21 of those 28 questions, against 24).

Build 7 added 24,544 questions about the past, a named year or month or none, built from the
catalog's archive of public records. It answers them far better (37 of 43 against 26), and says
"not covered" when nothing answers more often (24 of the 28 such questions in the other four
sets, against 21). It pays for that with more current questions it wrongly calls not covered
(14 across those sets, against 9), such as "crude oil price" and "recalled baby formula". Stock
index values (S&P 500, Dow, Nasdaq, Nikkei, VIX) are left out of the data: their owners do not
allow republishing them.

For build 8, when the decision was 95% sure or more (233 of the 240 answers, the 3 blind-3
questions above left out), it was right 210 times; below that, 3 of 7.

## Limits

- Some current questions get "not covered" when a source answers ("crude oil price"); `ask`
  then shows the closest items, so the sources are still there.
- Some questions no source answers get an answer from the nearest sources anyway; each cites
  its sources, so check them.
- For some listings it picks all five sources it may, including ones that do not answer.
- The answers read as lists of headlines; a larger model can explain them.
- It knows one prompt, `unlimitedpipe.decide.PROMPT`.

## Training

Qwen2.5 0.5B Instruct with LoRA (r=16, all linear layers), one pass over 70,609 decision
examples (build 7's 47,788 and 22,821 about the history added for build 8) built from public and
openly licensed data only (works of the US federal government, UK, Canadian and EU government
records under their open licences, and UnlimitedPipe's own sentences from open data; about 30% of
them "not covered"), about 6 hours on one T4. Build 7 is on the `build-7` branch, build 6 on
`build-6`, build 5 on `build-5`.

License: Apache 2.0, as its base model.
