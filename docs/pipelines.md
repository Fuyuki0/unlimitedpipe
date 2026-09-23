# Pipelines

A pipeline file runs sources, operators and outputs in one process. Every component and
option is the same as on the command line: `unlimited web URL --each .plan` becomes
`type: web` with `url` and `each` keys.

```yaml
name: tech-news                # names diff state; defaults to the file name

sources:                       # one or more; they run concurrently and their events merge
  - type: rss
    url:
      - https://hnrss.org/frontpage
      - https://lobste.rs/rss

operators:                     # applied in order
  - type: grep
    patterns: [AI, LLM]
  - type: dedupe
    by: [link]
  - type: diff
    only: [added]

outputs:                       # every event goes to every output; default: the terminal
  - type: jsonl
    path: ai-news.jsonl
    append: true
  - type: feed
    path: ai-news.xml

settings:
  errors_as_events: false      # true: failures become `error` events instead of messages
```

```bash
unlimited run tech-news.yml
unlimited run tech-news.yml --validate     # check without running
```

## Rules

- `type` picks the component; the other keys are its options. Run `unlimited TYPE --help`
  to list them (use `snake_case` keys for `--kebab-case` flags: `--emit-initial` is
  `emit_initial`).
- A component without options can be written as a plain string: `- diff`.
- A single value is accepted where a list is expected: `url: https://...`.
- Relative `path` and `state` values are resolved from the pipeline file's directory, so a
  pipeline works from any working directory.
- Each `diff` gets its state name from the pipeline `name` (`tech-news`, then `tech-news-2`
  for a second diff) unless `namespace` or `state` is set.

## Errors

Every mistake names the file, the line and the option, with a suggestion when one is close:

```text
error: tech-news.yml:11: operators[0] (grep): unknown option 'pattern' for grep
hint: did you mean 'patterns'?
```

## Inline pipelines

Short pipelines can skip the file. Stages are separated by `--`, written exactly like the
separate commands, and run in one process:

```bash
unlimited run web https://example.com -- select title url -- json
unlimited run rss https://hnrss.org/frontpage -- grep AI -- dedupe --by link -- feed ai.xml
```

Sources come first, then operators, then outputs. Without an output, events go to the
terminal (or as JSONL into a pipe).

## Running on a schedule

### watch

```bash
unlimited watch --every 1h tech-news.yml
unlimited watch --every 30m web https://store.example/p -- diff -- feed prices.xml
```

- `--every` takes `30s`, `5m`, `1h`, `1h30m` or `1d`; the minimum is 30 seconds.
- A failed run is reported and the watch continues on schedule.
- The pipeline file is reloaded when it changes. If the new version is invalid, the error is
  shown and the previous version keeps running.
- `--jitter 0.1` (the default) adds up to 10% random delay to each interval.
- `--times N` stops after N runs.
- Outputs run once per round. `feed` keeps its history; a `jsonl` file needs `append: true`
  to keep earlier rounds. Pair `watch` with `diff` to see only what changed.

`watch` runs in the foreground until Ctrl+C. To keep it running after you log out, use a
service manager (systemd, launchd), `tmux`, or a scheduler instead.

### cron

```cron
# every hour at minute 17
17 * * * *  cd ~/feeds && unlimited run prices.yml >> prices.log 2>&1
```

### GitHub Actions: a free hosted feed

A scheduled workflow can run a pipeline, keep the diff state in the repository and publish
the feed with GitHub Pages. Keep schedules modest (hourly or slower) and pipelines light:
GitHub's terms restrict Actions to work related to the repository's project.

```yaml
# .github/workflows/feeds.yml
name: feeds
on:
  schedule:
    - cron: "17 * * * *"
  workflow_dispatch:

permissions:
  contents: write

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install unlimitedpipe
      - run: unlimited run feeds/prices.yml
        env:
          UNLIMITEDPIPE_STATE_DIR: state
      - name: Commit feed and state
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add feeds state
          git diff --cached --quiet || git commit -m "Update feeds"
          git push
```

Enable GitHub Pages for the repository and subscribe to
`https://USER.github.io/REPO/feeds/prices.xml` in any feed reader. Scheduled workflows can run
late, and GitHub disables them in repositories without activity for 60 days.

## Environment variables

| Variable | Effect |
| --- | --- |
| `UNLIMITEDPIPE_STATE_DIR` | Where `diff` keeps state (default: the platform's user state directory) |
| `UNLIMITEDPIPE_CACHE_DIR` | Where HTTP validators and bodies are cached for conditional requests |
| `UNLIMITEDPIPE_FORMAT=jsonl` | Write JSONL even when stdout is a terminal |
| `HTTPS_PROXY`, `HTTP_PROXY` | Standard proxy settings |
