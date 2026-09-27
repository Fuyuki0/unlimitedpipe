---
license: apache-2.0
base_model: Qwen/Qwen2.5-0.5B-Instruct
language: [en, th]
tags: [gguf, ollama, rag, citations, unlimitedpipe]
datasets: [unlimitedpipe/ask-sft-public]
pipeline_tag: text-generation
---

# unlimitedpipe/ask-0.5b

A 0.5B model that answers from numbered sources the way
[UnlimitedPipe](https://github.com/Fuyuki0/unlimitedpipe)'s `ask` needs: it cites the sources it
uses (`[1]`), lists every matching item when asked what is new, invents nothing, and says
plainly when the sources do not cover the question, in English and Thai. Small enough (531 MB,
8-bit) to run on any machine with Ollama.

```bash
ollama pull hf.co/unlimitedpipe/ask-0.5b-GGUF
unlimited ask "any big crypto hacks this week?"      # ask picks it up by itself
```

`unlimited setup` installs it for you. This is build 3 (2026-09-27); build 2 is on the
`build-2` branch.

## Scores

70 questions written the way people type them ("bitcoin price?", "whats new with bitget",
"ข่าวไทยวันนี้มีอะไรบ้าง"), put through `ask`'s own search on the public catalog of
2026-09-27 and labelled by hand. Every model got the same prompts, answered greedily (up to
200 new tokens, thinking off), and was graded the same way: it cites a source that answers
(three of the matching ones for a list), does not cite every source, says so when the sources
do not answer, invents no number, cites no source that does not exist, and answers Thai in
Thai ([`research/ask`](https://github.com/Fuyuki0/unlimitedpipe/tree/main/research/ask)).

| Model | Parameters | Real questions (70) |
| --- | --- | --- |
| **unlimitedpipe/ask-0.5b, build 3 (this model)** | **0.5B** | **57 (81%)** |
| Qwen3.5 4B | 4.2B | 56 (80%) |
| Qwen3.5 2B | 1.9B | 45 (64%) |
| Phi-4 mini | 3.8B | 43 (61%) |
| Gemma 4 E2B | 5.1B (2B active) | 43 (61%) |
| Granite 4.1 3B | 3.4B | 42 (60%) |
| Llama 3.2 3B | 3.2B | 37 (53%) |
| LFM2.5 1.2B | 1.2B | 37 (53%) |
| unlimitedpipe/ask-0.5b, build 2 | 0.5B | 36 (51%) |
| SmolLM3 3B | 3.1B | 35 (50%) |
| Qwen3.5 0.8B | 0.8B | 22 (31%) |
| Llama 3.2 1B | 1.2B | 21 (30%) |
| Gemma 3 1B | 1.0B | 9 (13%) |
| Qwen2.5 0.5B Instruct (the base) | 0.5B | 0 (0%) |

On the template test sets it was built for, it passes 110 of 120 (build 3's), 78 of 84 (build
2's public data) and 87 of 92 (news it never saw, from build 2's private set).

Build 3 over build 2: lists (39 of 48 real list questions, from 18), because build 2 had 56
list examples and build 3 has 7,719; 10 sources per question as `ask` gives by default (build 2
always had 5); and questions typed the way people type.

## Training

Qwen2.5 0.5B Instruct with LoRA (r=16, all linear layers), one pass over 18,468 examples of
[unlimitedpipe/ask-sft-public](https://huggingface.co/datasets/unlimitedpipe/ask-sft-public):
the exact prompt `ask` sends and an answer written from the sources by templates. The sources
are public data only: works of the US federal government (SEC, the Federal Register, OFAC,
USGS, NOAA, NASA, CISA, FDA, DOJ, the Federal Reserve, the White House, the State Department)
and sentences UnlimitedPipe writes from open data. No news articles. 146 minutes on one T4.

## Limits

- It answers with its sources' own words (headlines and summaries). That keeps it from
  inventing, and also means it does not explain or reason; a larger general model explains
  better.
- A bare topic ("openai news", "ข่าวญี่ปุ่นล่าสุด") often gets one item where a list was
  wanted; lists come with "any", "what's new", "this week".
- Lists make answers longer: about 15 to 20 seconds on a 2-core CPU, against about 9 for one
  item.
- It was taught one prompt format, `ask`'s. Other prompts get ordinary Qwen 0.5B behaviour.
- Thai answers keep English source titles as they are.

License: Apache 2.0, as its base model.
