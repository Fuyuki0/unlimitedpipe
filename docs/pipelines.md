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

### GitHub Actions and Pages: a free hosted feed

`unlimited publish` sets this up for a pipeline in a GitHub repository:

```bash
unlimited publish feeds/prices.yml --every 1h
```

It writes `.github/workflows/unlimitedpipe-NAME.yml` and `public/index.html` (for outputs under
`public/`) and prints the remaining steps:

1. Commit and push.
2. Turn on GitHub Pages with GitHub Actions as the source, once per repository:
   `gh api -X POST repos/OWNER/REPO/pages -f build_type=workflow`
   (or Settings → Pages → Source: GitHub Actions).
3. Start the first run: `gh workflow run unlimitedpipe-NAME.yml`.

Each run installs UnlimitedPipe from PyPI, runs the pipeline, commits the outputs and the diff
state (`.unlimitedpipe/state/`) so the next run remembers what it saw, and deploys the output
folder. A run where some sources failed still publishes the rest, with a warning; a broken
pipeline fails the run. The workflow passes GitHub's own token to the `github` source, so API
limits are generous.

Rules and limits:

- Outputs must live in a folder of their own (for example `path: public/prices.xml`); that
  folder is what gets published.
- `--every` accepts 15m, 20m, 30m, divisors of a day (1h, 2h, 3h, 4h, 6h, 8h, 12h) and 1d. The
  minute is derived from the pipeline name, so feeds do not all run at :00.
- GitHub runs scheduled workflows on a best-effort basis, may delay them, and disables them in
  repositories without activity for 60 days. GitHub's terms restrict Actions to work related to
  the repository's project: keep pipelines light.
- On free GitHub plans, Pages requires a public repository.

## Environment variables

| Variable | Effect |
| --- | --- |
| `UNLIMITEDPIPE_STATE_DIR` | Where `diff` keeps state (default: the platform's user state directory) |
| `UNLIMITEDPIPE_CACHE_DIR` | Where HTTP validators and bodies are cached for conditional requests |
| `UNLIMITEDPIPE_FORMAT=jsonl` | Write JSONL even when stdout is a terminal |
| `HTTPS_PROXY`, `HTTP_PROXY` | Standard proxy settings |
