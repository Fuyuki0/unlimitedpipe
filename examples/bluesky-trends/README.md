# bluesky-trends

What English-language Bluesky is suddenly talking about, live, with no AI and no account:
count how many different people use each hashtag in 10-minute windows, and report the ones
rising far above their recent average. Counting people rather than posts keeps a single
automated account from looking like a trend.

```bash
pip install "unlimitedpipe[live]"
unlimited run examples/bluesky-trends/pipeline.yml
```

The first window after starting is partial and is skipped, the second builds history, so
trends start appearing after about 20 minutes. History is kept on disk, so a restarted run
continues where it left off.

## What real output looks like

A 20-minute run over English Bluesky words (5-minute windows, counting people) on
2026-09-23 reported nothing in three of four windows, and in one:

```text
↑  +538%  details      51 now, usually 8
↑  +450%  iembot       44 now, usually 8
↑  +362%  snow         37 now, usually 8
↑  +330%  climate      43 now, usually 10
↑  +325%  precip       34 now, usually 8
```

That burst is real, but not human: a network of weather-service bot accounts (iembot) posting
their scheduled daily climate reports at once. Counting distinct accounts stops one bot from
looking like a trend; it cannot tell a coordinated bot network from people. To focus on human
topics, narrow the input (topic words, hashtags) or drop known bot terms:

```bash
unlimited run bluesky --lang en -- grep --invert iembot \
  -- count --by tags --distinct author_key --every 10m -- trend
```

The same thing without a file, for any topic:

```bash
unlimited run bluesky AI LLM --lang en -- extract words \
  -- count --by words --distinct author_key --every 10m -- trend
```

Posts come from Bluesky's public Jetstream. The source has no filter by author, and the
trend engine only counts terms.
