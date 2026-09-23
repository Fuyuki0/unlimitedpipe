# bluesky-trends

What English-language Bluesky is suddenly talking about, live, with no AI and no account:
count how many different people use each hashtag in 10-minute windows, and report the ones
rising far above their recent average. Counting people rather than posts keeps a single
automated account from looking like a trend.

```bash
pip install "unlimitedpipe[live]"
unlimited run examples/bluesky-trends/pipeline.yml
```

```text
↑   +340%  #earthquake   22 now, usually 5
↑     new  #launchday    9 now, usually 0
```

The first window after starting is partial and is skipped, the second builds history, so
trends start appearing after about 20 minutes. History is kept on disk, so a restarted run
continues where it left off.

The same thing without a file, for any topic:

```bash
unlimited run bluesky AI LLM --lang en -- extract words \
  -- count --by words --distinct author_key --every 10m -- trend
```

Posts come from Bluesky's public Jetstream. The source has no filter by author, and the
trend engine only counts terms.
