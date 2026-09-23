# rss-news-pipeline

Merge several feeds, keep stories about AI, emit only stories you have not seen, and publish
the result as your own RSS feed.

```bash
unlimited run examples/rss-news-pipeline/pipeline.yml
```

Each run appends new stories to `ai-news.xml` (up to 100 items, newest first). Subscribe to
that file in any feed reader, or host it (see [docs/pipelines.md](../../docs/pipelines.md)).

The same thing as a one-liner:

```bash
unlimited rss https://hnrss.org/frontpage https://lobste.rs/rss \
  | unlimited grep AI LLM \
  | unlimited dedupe --by link \
  | unlimited diff --only added
```

`grep` matches whole words and ignores case: `AI` finds "AI" but not "said".
