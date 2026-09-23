# Changelog

All notable changes are listed here. The project follows [Semantic Versioning](https://semver.org/);
the event format is versioned separately by its `schema` field (see docs/events.md).

## Unreleased

- `webhook` output: one Discord or Slack message per event (format recognized from the URL),
  or the event as JSON. Mentions are disabled, Markdown is escaped, messages per run are capped
  with one summary message, rate limits are retried, and webhook URLs never appear in errors.
- `bluesky` source: new public posts, live, from Bluesky's Jetstream, filtered by words and
  language, with hashtags and links from post facets; reconnects and resumes from its cursor.
  Optional dependency: `pip install "unlimitedpipe[live]"`.
- SIGTERM (docker stop, systemd, CI timeouts) now shuts down like Ctrl+C, closing outputs and
  saving state; JSONL files are flushed whenever the pipeline goes idle; `file -` streams JSONL
  from stdin instead of waiting for the end of the input.
- Trend engine: `extract` (hashtags, $cashtags, domains, words without stopwords, or any
  regex), `count --by FIELD [--every WINDOW]` (windows follow each event's time, in any order),
  and `trend` (spikes against earlier windows, with history kept across runs). Windows the
  data only partly covers are marked and never used for comparisons.
- `sqlite` output: one row per distinct observation (re-runs add only what is new), with
  data, metadata and provenance as JSON columns for SQLite's JSON functions.
- `${NAME}` in pipeline files reads environment variables; `publish` passes them to the
  workflow from repository secrets.
- Feed items and messages drop metadata-only summaries (Hacker News "Article URL: … Points: 74",
  Lobsters "Comments"), no longer repeat a change in both title and summary, and show the values
  of newly added records.
- `grep` skips web addresses when searching for plain words.

## 0.2.0 - 2026-09-23

Second release: "Feed".

- `unlimited watch --every DURATION`: run a pipeline on an interval in one process, keep going
  after failed runs, reload the pipeline file when it changes.
- `unlimited new URL`: inspect a page and write a commented pipeline file that watches it
  through its product data, its feed, or its text.
- `unlimited publish PIPELINE --every 1h`: generate a GitHub Actions workflow that runs a
  pipeline on a schedule, commits its outputs and diff state, and deploys them to GitHub Pages.
- Feed items for newly added entries read like the entry itself (no "New:" prefix, the entry's
  own summary); summaries are capped at 500 characters.
- `github` source: releases, repository stats, tags, commits and issues through GitHub's
  official REST API, with optional `GITHUB_TOKEN`, ETag revalidation and clear rate-limit
  errors. The examples use it instead of GitHub's Atom feeds, which GitHub's robots.txt
  disallows for automated clients.
- `select NAME=a|b` falls back to the first field that exists.
- Inline pipelines: `unlimited run web URL -- select title -- json` runs stages separated by
  `--` in one process; `watch` accepts the same form.
- Fixed a race on Python 3.11 where the stdin reader thread could print a traceback when a
  pipe stopped early.
- Faster JSONL pipes: one serialization per event id, batched stdout flushes.

## 0.1.0 - 2026-09-23

First release: "Pipe".

- Event format `unlimitedpipe.event/1` with keys, provenance and fetch metadata.
- Streaming engine: async sources -> operators -> outputs, early stop, clean Ctrl+C.
- CLI generated from component definitions, lazy loading (about 150 ms per pipe stage),
  readable terminal output and JSONL in pipes.
- Sources: `web` (documents; products from Shopify, JSON-LD and OpenGraph; CSS selectors and
  fields; links; JSON), `rss` (RSS, Atom, JSON Feed, feed discovery), `file` (JSON, JSONL,
  CSV), `inspect`.
- Operators: `select`, `filter` (safe expression language), `map`, `grep`, `dedupe`, `limit`,
  `sort`, `diff` (field-level change detection with persistent state).
- Outputs: `jsonl`, `json`, `csv`, `feed` (RSS, Atom, JSON Feed with history), `pretty`.
- YAML pipelines with line-numbered validation errors.
- Polite HTTP: robots.txt (RFC 9309), per-host rate limits, retries with `Retry-After`,
  conditional requests, size cap.
- Plugin system through the `unlimitedpipe.plugins` entry point group, with a complete example
  connector.
