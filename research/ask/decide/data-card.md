---
license: other
license_name: public-domain-and-cc-by
language: [en, th]
task_categories: [question-answering]
pretty_name: UnlimitedPipe decision examples (public data)
---

# decide-sft-public

Decision examples for `unlimited ask`: the prompt `unlimitedpipe.decide.PROMPT` (numbered
sources and a question) and the decision, `USE` with the numbers of the sources that answer
it, or `NONE`. Built by `research/ask/build.py --public --decide` in
https://github.com/Fuyuki0/unlimitedpipe from public data only: works of the US federal
government (SEC, the Federal Register, OFAC, USGS, NOAA, NASA, CISA, FDA, DOJ, the Federal
Reserve, the White House, the State Department) and sentences UnlimitedPipe writes itself from
open data. 19,516 examples to learn from ("not covered" ones counted twice) and 1,993 to test.

Attribution: weather data by MET Norway (CC BY 4.0); breach data by Have I Been Pwned (CC BY
4.0); crypto data by DefiLlama.
