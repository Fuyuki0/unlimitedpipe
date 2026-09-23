# Changelog

All notable changes are listed here. The project follows [Semantic Versioning](https://semver.org/);
the event format is versioned separately by its `schema` field (see docs/events.md).

## Unreleased

- `unlimited watch --every DURATION`: run a pipeline on an interval in one process, keep going
  after failed runs, reload the pipeline file when it changes.
- `unlimited new URL`: inspect a page and write a commented pipeline file that watches it
  through its product data, its feed, or its text.
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
