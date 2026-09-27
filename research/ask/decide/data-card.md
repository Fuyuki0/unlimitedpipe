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
open data. Build 6: 23,244 examples to learn from and 2,964 to test, about 30% of them
"not covered", including questions about a source's topic that ask for something no source
says ("hurricane death toll"). Build 5's data is on the `build-5` branch.

Attribution: weather data by MET Norway (CC BY 4.0); breach data by Have I Been Pwned (CC BY
4.0); crypto data by DefiLlama.
