# A 0.5B model that cites its sources: from 5% to 87%

*2026-09-27. UnlimitedPipe's `ask`, and what it took to make a tiny model answer honestly.*

`unlimited ask` answers questions from 77 live feeds of public records and news. The facts
are found by plain search, not by a model; a model only turns the numbered sources into an
answer. That design means the model can be small enough to run on any laptop, but it still has
to do one job well: say what the sources say, cite them, and admit when they do not answer the
question.

## A general small model does not

Qwen2.5 0.5B Instruct, a good small general model, given exactly the prompt `ask` sends:

- asked "any new activist stakes?" with three new SEC Schedule 13D filings in its sources, it
  answered "No new activist stakes have been disclosed";
- it mixed two crypto hacks into one, dated a Thai earthquake answer 2021 in a question about
  2026, and in Thai slipped into Chinese words and repeated itself;
- it left out the `[n]` citations the prompt asks for, most of the time.

Graded on test questions (right citation, no source cited that does not exist, no number that
is not in the sources, Thai answers to Thai questions, plain refusals), it passed **5 of 92**.

## Teaching it the one job

We built training examples from the catalog itself: the exact prompt `ask` sends, with the
same search picking the sources, and an answer written from those sources by templates, so
every answer is right by construction. Four kinds, in English and Thai: answer from one item
and cite it; list several and cite each; and when the question's key word is in no source, say
so and point to the closest item.

Then LoRA fine-tuning: about 1.7% of the weights, one pass over ~7,000 examples, 30 minutes
on one free Kaggle GPU.

To make a model anyone may download, the training data had to be free to republish, so the
public model saw **no news at all**: only works of the US federal government (SEC filings, the
Federal Register, NOAA, USGS, NASA, FDA, DOJ and more) and sentences UnlimitedPipe writes
itself from open data. The question was whether it would still work on news.

| Model | News it never saw (92 questions) | Public data (84) |
| --- | --- | --- |
| Qwen2.5 0.5B Instruct | 5 (5%) | 5 (6%) |
| Same recipe, trained on news (kept private) | 84 (91%) | 81 (96%) |
| **unlimitedpipe/ask-0.5b** (public data only) | **80 (87%)** | **82 (98%)** |

It learned the skill, not the topics: trained without a single news item, it nearly matches
the model trained on news, on news.

## What we got wrong on the way

The first build's templates trimmed everything before a colon, meant to drop outlet names
("BBC Africa: ..."). That also dropped subjects: "Bitcoin (BTC) price: $84,056.11" became
"$84,056.11", and the model faithfully learned to drop them. The grader did not catch it (the
answers still cited the right source); reading real answers did. Build two keeps titles whole.

## Limits

It answers with its sources' own words. That is what keeps it from inventing, and also why it
does not explain or reason; a larger general model explains more and cites less. Asked what is
new in a feed, it often lists one item where two or three were there. And it knows one prompt,
`ask`'s.

## Try it

```bash
curl -fsSL https://raw.githubusercontent.com/Fuyuki0/unlimitedpipe/main/install.sh | sh
unlimited ask "any big insider buys this week?"
```

The model: [unlimitedpipe/ask-0.5b-GGUF](https://huggingface.co/unlimitedpipe/ask-0.5b-GGUF)
(531 MB). Its data: [unlimitedpipe/ask-sft-public](https://huggingface.co/datasets/unlimitedpipe/ask-sft-public).
How it was built and graded: [research/ask](../../research/ask).
