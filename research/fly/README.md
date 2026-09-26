# A fruit-fly brain circuit on news items

**Question.** The fruit fly's mushroom body, the part of its brain that learns smells, turns
about 50 inputs into a sparse code over about 2,000 Kenyon cells: each cell sums a few random
inputs and only the most active few percent fire. Its output neurons then learn which codes
matter. Dasgupta, Stevens and Navlakha (*Science*, 2017) showed the same circuit works as a
similarity search. With the whole fly brain now mapped (FlyWire, *Nature*, 2024), could the
circuit give UnlimitedPipe a small model that understands its feeds?

**Answer, on this data: no.** The fly circuit did no better than the simple compression that
feeds it, and worse at finding duplicate stories. A negative result, reported as such.

## Setup

- 3,553 items (headline and summary) from the 41 catalog feeds with 30 items or more, taken on
  2026-09-26; 75% to learn from, 25% to test, the same split for every model.
- Words: TF-IDF over 20,000 words. Compression: those reduced to 100 dense inputs (SVD), which
  play the fly's projection neurons. Fly: the 100 inputs wired at random into 2,000 to 20,000
  Kenyon cells, 6 or 12 inputs per cell, 2 to 10% of cells firing; the best of six sizes is
  shown.

Run it yourself (see [../README.md](../README.md) for the setup):

```bash
research/.venv/bin/python research/fly/experiment.py research/data
```

## Results

**1. Which feed does an unseen item come from?** (41 feeds; always guessing the biggest: 5.6%)

| Model | Accuracy | Learned parameters |
| --- | --- | --- |
| Words, learned readout | **92.0%** | 673,589 |
| 100 inputs, learned readout (no fly) | 87.6% | **4,100** |
| Fly, 10,000 cells, learned readout | 87.3% | 410,000 |

**2. Nearest neighbours, no learning: are an item's 5 most similar items from its feed?**

| Model | Accuracy | Search time (889 items) | Size per item |
| --- | --- | --- | --- |
| Words | 80.0% | 7.00 s | ~266 bytes |
| 100 inputs (no fly) | **83.6%** | **0.13 s** | 400 bytes |
| Fly code, 10,000 bits | 82.8% | 0.39 s | 1,250 bytes |

**3. Duplicates: 17 stories listed by two feeds (mostly one BBC story in two feeds).** Is the
other copy the nearest item?

| Model | Found |
| --- | --- |
| Words | **16/17** |
| 100 inputs | 13/17 |
| Fly code | 10/17 |

## What it means

- The fly circuit adds nothing over its own input here: 100 compressed inputs with 4,100
  learned weights match the fly's accuracy with 100 times fewer parameters.
- Its speed in similarity search came from the compression, not from the fly: the same 100
  inputs without the fly are faster and a little more accurate.
- For duplicates, exact words matter most, and the fly's random wiring blurs them.
- "Small but smart" on this data came from ordinary compression, not from copying a brain.

## Limits

- 3,553 items is small, and headlines are short; the fly's code may do better on richer text.
- The fly's claimed strengths not tested here: learning new categories one after another
  without forgetting old ones, noticing novelty, and cheap hardware (binary codes compared by
  counting bits, which this run did with ordinary floating-point arithmetic).
- One run with fixed seeds; differences of about a point are within noise.

## Next, if worth it

Test what the fly is said to be good at: continual learning (the catalog keeps gaining feeds:
can the circuit learn new ones without retraining, where ordinary models forget?), and novelty
(is a new item unlike anything this month?). Liang et al. (ICLR 2021, "Can a Fruit Fly Learn
Word Embeddings?") trained word meanings with the same circuit; that needs a larger public
corpus than the catalog.

# Many small flies and one main network

**Question.** A brain is many specialised circuits, and only a few work at a time: that is
how 86 billion neurons run on about 20 watts. So: many small fly circuits, each for its own
kind of item, with a main network that sends each item to one of them. Is that accurate,
cheap in energy, and able to keep learning?

**Setup.** The same 41 feeds and split as above. The main network (the router) sorts items
into 8 groups by similarity; each group gets its own small fly (2,000 cells) or its own
ordinary model. Energy counts the arithmetic per item with 45 nm chip figures (Horowitz,
ISSCC 2014): 4.6 pJ for a 32-bit float multiply-add, 0.23 pJ for an 8-bit one, 0.03 pJ for the
8-bit addition a fly's on-or-off connection needs. `research/fly/modules.py` runs it.

| Model | Accuracy | Energy per item (arithmetic) |
| --- | --- | --- |
| One ordinary model | 87.6% | 18.9 nJ |
| One big fly (10,000 cells) | 87.3% | 4.2 nJ |
| Main network + 8 small flies | 83.8% | 4.2 nJ |
| Main network + 8 ordinary models | 84.8% | 22.5 nJ |
| **One ordinary model on 8-bit numbers** | **87.3%** | **0.9 nJ** |

**Keep learning:** 30 feeds first, then 11 new feeds, without seeing the old items again.

| Model | Old feeds | New feeds |
| --- | --- | --- |
| One ordinary model, before the new feeds | 84.9% | - |
| **One ordinary model, after** | **8.4%** | 98.9% |
| Main network + fly modules | 81.8% | 83.5% |
| Main network + ordinary modules | 82.0% | 84.7% |

## What it means

- **The architecture works; the fly part does not add to it.** One ordinary model forgets
  almost everything it knew when it learns something new without the old data ("catastrophic
  forgetting"); a main network with separate modules keeps it, whether the modules are flies
  or ordinary models. New knowledge goes into new modules, and old modules are left alone.
- **Energy: 8-bit arithmetic beats the fly.** The fly's saving comes from needing additions
  only, but an ordinary model on 8-bit numbers, as phones already run models, costs less again
  (0.9 against 4.2 nJ) at the same accuracy.
- The energy figures count arithmetic only. On real chips, moving weights from memory costs
  more than the arithmetic, which favours small models and, in principle, the fly's one-bit
  connections: the part worth measuring on real hardware (or a neuromorphic chip, which runs
  sparse spiking circuits like the fly's natively).
- The modular idea is how large language models already save energy ("mixture of experts":
  only a few expert blocks run for each word). A main network with small specialists is a
  sound direction; the specialists need not copy a fly.
