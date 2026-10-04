---
license: other
license_name: public-domain-and-open-government-licences
language: [en, th]
task_categories: [question-answering]
pretty_name: UnlimitedPipe decision examples (public data)
---

# decide-sft-public

Decision examples for `unlimited ask`: the prompt `unlimitedpipe.decide.PROMPT` (numbered
sources and a question) and the decision, `USE` with the numbers of the sources that answer
it, or `NONE`. Built by `research/ask/build.py --public --decide` in
https://github.com/Fuyuki0/unlimitedpipe from public and openly licensed data only: works of the
US federal government (SEC, the Federal Register, OFAC, USGS, NOAA, NASA, CISA, FDA, DOJ, BTS,
USAspending, the Federal Reserve, the White House, the State Department), UK, Canadian and EU
government records under their open licences, and sentences UnlimitedPipe writes itself from
open data. Build 8: 70,609 examples to learn from and 8,378 to test, about 30% of them "not
covered": build 7's, and 22,821 questions about history added to the catalog on 2026-10-04
(hurricanes, typhoons, solar storms, earnings releases, government records, federal contracts
and grants, crypto market events). Stock index values (S&P 500, Dow, Nasdaq,
Nikkei, VIX) are left out: their owners do not allow republishing them. Build 7's data is on the
`build-7` branch, build 6's on `build-6`, build 5's on `build-5`.

Attribution: weather data by MET Norway (CC BY 4.0); breach data by Have I Been Pwned (CC BY
4.0); crypto data by DefiLlama; typhoon best tracks by the Japan Meteorological Agency (RSMC
Tokyo); Kp index by GFZ Potsdam (CC BY 4.0). Contains public sector information licensed under
the Open Government Licence v3.0 (GOV.UK) and the Open Parliament Licence v3.0 (UK Parliament
bills); contains information licensed under the Open Government Licence - Canada; EU legislation
metadata from EUR-Lex, (c) European Union, reused under Commission Decision 2011/833/EU.
