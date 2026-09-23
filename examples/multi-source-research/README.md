# multi-source-research

Follow one topic across Hacker News, a blog and two GitHub projects, then keep the results
as a CSV you can open in a spreadsheet.

```bash
unlimited run examples/multi-source-research/pipeline.yml
```

Sources are fetched concurrently (politely: one request per second per host), merged,
filtered, de-duplicated by link and sorted newest first. Every row still knows where it came
from: run without `select` and look at `source_url` and `provenance`.
