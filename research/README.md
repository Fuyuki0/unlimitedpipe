# Research

Experiments around UnlimitedPipe's data. Nothing here is part of the installed tool.

| Folder | Question |
| --- | --- |
| [fly](fly) | Does a fruit-fly brain circuit (the mushroom body) help understand news items? |
| [ask](ask) | Can a 0.5B model trained on good answers make `unlimited ask` more reliable? |

Setup, from the repository root:

```bash
uv venv research/.venv && uv pip install --python research/.venv/bin/python -r research/requirements.txt
unlimited mirror --feeds research/data     # the catalog and its archive, for the experiments
```

The catalog's items are headlines and summaries owned by their publishers. They are used here
for research only: the data and anything trained on it stay private.
