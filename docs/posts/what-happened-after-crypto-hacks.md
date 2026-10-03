# What happened to a token after its protocol was hacked

*2026-10-03. 190 hacks since 2019, from open data. Not investment advice.*

UnlimitedPipe keeps every crypto hack DefiLlama records, back to 2011, with when it happened
and how much was taken. A question people ask: when a protocol is hacked, what happens to its
token? Not a prediction: what did happen, the last 190 times we can measure.

## Method

- **Hacks:** DefiLlama's hacks list. Of 1,293 hacks, 539 name the protocol hacked; 190 of
  those protocols have a token with prices before and after the hack.
- **Prices:** DefiLlama's open coin prices, daily. The change is from the day before the hack
  to 1, 7 and 30 days after it.
- **Against Bitcoin:** each change minus Bitcoin's over the same days, so a market-wide fall
  is not counted as the hack's.
- **Control:** small tokens often lose ground to Bitcoin anyway. So the same tokens are also
  measured over the same spans 90 days before their hack. The hack's part is the difference.

## Results

Median change against Bitcoin, and the share of tokens that did worse than Bitcoin:

| Hacks | n | 1 day | 7 days | 30 days | Control, 30 days |
| --- | --- | --- | --- | --- | --- |
| All | 190 | -11.8% (81%) | -16.3% (83%) | -28.3% (84%) | -9.5% (65%) |
| $100M or more | 6 | -20.3% (83%) | -31.9% (100%) | -40.4% (100%) | -9.3% (60%) |
| $10M to $100M | 35 | -32.1% (97%) | -40.0% (97%) | -51.6% (97%) | -11.0% (59%) |
| Under $10M | 149 | -9.5% (77%) | -13.3% (79%) | -23.1% (80%) | -9.5% (66%) |

In plain words: a hacked protocol's token fell about 12% more than Bitcoin the next day, and
about 28% more within a month. In ordinary times the same tokens lagged Bitcoin by about 10%
a month, so roughly 19 points of the month are the hack's. Hacks of $10M to $100M were the
worst: 33 of the 34 measured did worse than Bitcoin within a month, with a median of -52%. Some
examples: CREAM Lending ($130M, 2021) -74% in 30 days, Qubit ($80M, 2022) -78%, Multichain
($126M, 2023) -45%; and the other way, Ronin ($624M, 2022) +5% the next day before -31% in a
month.

## Caveats

- **Only tokens that still trade.** A token whose price data stops (delisted, abandoned) has
  no row, and those are likely the worst cases; the real numbers are probably worse.
- **Dates are the day of the hack**, not the minute it became public; the first day mixes
  before and after.
- **Small samples**: six hacks of $100M or more. Medians, not means, so one collapse to zero
  does not decide the result.
- **Not a strategy.** Prices move within minutes of a hack becoming public; UnlimitedPipe
  sees it about a minute later. This says how bad it usually is for holders, not how to trade
  it. Nothing here is investment advice.

## Reproduce it

```bash
research/.venv/bin/python research/events/crypto_hacks.py hacks.csv
```

It reads DefiLlama's open APIs (hacks, protocols, coin prices), writes one row per hack and
prints the table above. Every hack is also in the catalog:
`unlimited ask "biggest crypto hacks ever"`, or `unlimited search hack --feed crypto-hacks
--since 2022`.
