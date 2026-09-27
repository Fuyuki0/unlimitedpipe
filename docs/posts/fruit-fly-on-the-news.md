# We tried a fruit fly's brain on the news

*2026-09-27. What worked, what did not, and what we kept.*

The whole brain of the fruit fly has been mapped: about 140,000 neurons and 50 million
connections (FlyWire, *Nature*, 2024). The part that learns smells, the mushroom body, is a
famously simple circuit: about 50 inputs fan out at random to about 2,000 Kenyon cells, only
the most excited few percent fire, and output neurons learn which of those sparse patterns
matter. In 2017, Dasgupta, Stevens and Navlakha showed in *Science* that the same circuit is a
good similarity search.

So: could a fly-shaped circuit give UnlimitedPipe a small, cheap model that understands its
feeds? We tested it on 3,553 items from 41 feeds, against ordinary methods, on the same split.
Code and full numbers: [research/fly](../../research/fly).

## One fly: no better than plain compression

| Task | Plain words | Same 100 inputs, no fly | Fly circuit |
| --- | --- | --- | --- |
| Which feed is this item from? | 92.0% | 87.6% (4,100 weights) | 87.3% (410,000 weights) |
| Are its nearest items from its feed? | 80.0% | **83.6%**, 0.13 s | 82.8%, 0.39 s |
| Is its duplicate from another feed the nearest item? | **16 of 17** | 13 of 17 | 10 of 17 |

An early result looked like a win: the fly's nearest-neighbour search beat plain words by 4
points and was 17 times faster. The fair comparison adds the same 100 compressed inputs
without the fly, and that did as well, faster. The gain came from the compression. We had
reported the early result before checking; the table above is the checked one.

## Many flies and a main network: the brain's idea works, the fly part does not add

A brain is many specialised circuits with only a few working at a time. So we built a main
network that routes each item to one of 8 small modules, and asked the question that matters
for a catalog that keeps gaining feeds: can it learn 11 new feeds without forgetting 30 old
ones, and without seeing the old items again?

| Model | Old feeds after learning new ones | New feeds |
| --- | --- | --- |
| One ordinary model | **8.4%** (from 84.9%) | 98.9% |
| Main network + fly modules | 81.8% | 83.5% |
| Main network + ordinary modules | 82.0% | 84.7% |

One model forgets almost everything ("catastrophic forgetting"). Separate modules keep it,
whether they are flies or not: new knowledge goes into new modules and old ones are left alone.

## Energy

Counting the arithmetic per item with 45 nm chip figures (Horowitz, ISSCC 2014), the fly's
on-or-off connections need only additions: 4.2 nJ, against 18.9 nJ for an ordinary model in
32-bit floats. But the same ordinary model on 8-bit integers, as phones already run models,
costs 0.9 nJ at the same accuracy. Low energy came from small numbers, not from the fly.

## What we kept

Not the fly's wiring: the principle. Small specialists beat one big generalist at their own
job, and only what is needed should run. UnlimitedPipe's `ask` model is exactly that, a 0.5B
specialist trained for one task, which went from 5% to 87% at it
([the other write-up](a-small-model-that-cites.md)).

What we did not test, and would: the fly on real neuromorphic hardware, where sparse spiking
circuits run natively; fly-style word meanings (Liang et al., ICLR 2021) on a large corpus; and
novelty detection, the fly's other claimed strength.
