# Changelog

All notable changes are listed here. The project follows [Semantic Versioning](https://semver.org/);
the event format is versioned separately by its `schema` field (see docs/events.md).

## 0.6.0 - 2026-09-26

"Browser": public pages that need JavaScript.

- `web --browser` renders pages in a headless Chromium (Playwright) before reading them, for
  public pages that fill in their content with JavaScript. It follows the same rules as every
  fetch: robots.txt and Crawl-delay, one pace per site shared with plain requests, the same
  User-Agent. Images, fonts and media are not downloaded. Optional:
  `pip install "unlimitedpipe[browser]" && playwright install chromium`.
- `web --browser --screenshot DIR` saves a full-page screenshot of each page, as evidence of
  what it showed; events record the file in `metadata.screenshot`.
- `publish` installs Chromium in the workflow when a pipeline renders pages.
- `inspect` suggests `--browser` for pages that only show their content with JavaScript.

## 0.5.1 - 2026-09-26

- Feed health: published workflows record each pipeline's result, and `unlimited catalog
  --results FILE` stores every feed's status in `feeds.json` (ok, partial or failing, since
  when, and its newest item). The status time only moves when the status changes. The index
  page marks failing feeds, and GitHub Actions shows a warning for each.
- `publish --install SPEC` sets what the workflow installs with pip, such as a Git tag
  (`git+https://github.com/Fuyuki0/unlimitedpipe@v0.5.1`) instead of the release on PyPI.

## 0.5.0 - 2026-09-26

"Ask": questions answered from the feeds, with sources.

- `unlimited ask QUESTION`: finds the catalog items that match the question (plain code, the
  same matching as `search`, keeping only strong matches), then has a model explain them from
  numbered sources, which are always listed with their links. A local model through Ollama
  when it is running (the best installed one, or `--model`), otherwise Claude with
  `ANTHROPIC_API_KEY` (`--provider` to choose). With nothing relevant, no model is asked.
- Index pages written by `publish` get a search box that searches `feeds.json` in the
  visitor's browser: no server, no tracking.
- `search` also matches the name of an item's feed: "insider" finds every insider trade.

## 0.4.0 - 2026-09-26

"Search": ask a whole feed catalog at once, and insider trades from the SEC.

- `unlimited search WORDS...` searches every feed of a published catalog in one request and
  returns the matching items with their links; `--feed` narrows it, `--list-feeds` lists the
  feeds. The default catalog is https://feeds.daemonfill.dev/ (50 feeds); `--catalog` or
  `UNLIMITEDPIPE_CATALOG` points it at any site made by `unlimited publish`.
- `unlimited catalog PIPELINES...` writes `feeds.json` next to published feeds: each feed with
  its description and files, plus the latest items of all of them. `publish` writes it, and
  its workflows refresh it after every run.
- MCP: `search_feeds` and `list_feeds` let AI agents search the catalog ("did any company
  disclose a cyberattack to the SEC this week?") without knowing which feed to read.
- `sec insider-trades`: the latest Form 4 filings as readable trades, from each filing's own
  data: who (and their role) bought or sold how many shares, at what price, for how much.
  Open-market purchases and sales by default (`--code` for others), `--min-value` for big
  ones. The SEC asks for a contact email: `--contact` or `SEC_CONTACT`.
- Expressions: `-`, `*` and `/` (with precedence and parentheses), `round(x, digits)`,
  `abs(x)` and `short(x)` (`1400000000` -> `"1.4B"`).
- `publish` no longer needs secret values on the machine that publishes, only their names.
- Published workflows check out the branch tip, so a run queued behind another no longer
  works from stale outputs and fails to push.

## 0.3.2 - 2026-09-24

The launch release.

- Expressions: `date(value)` turns ISO 8601, RFC 2822 or Unix times (seconds or milliseconds,
  as JSON APIs often send them) into ISO 8601 UTC: `published_at=date(properties.time)`.
- Feed items read their date from Unix times and RFC 2822 text too, and skip a date they
  cannot read instead of falling back to the time of the run.
- The User-Agent, package links and published index pages point to the GitHub repository.
- README: the live feed catalog, and how UnlimitedPipe compares with Yahoo Pipes, Huginn,
  n8n, RSS-Bridge and changedetection.io.

## 0.3.1 - 2026-09-24

What the seed feed catalog needed. 0.3.0 on PyPI was built before these changes.

- `unlimited publish feeds/*.yml` publishes a catalog: one workflow runs every pipeline, a
  failing one does not block the others, pushes rebase on concurrent changes, and the index
  page lists each feed with its `description`.
- `web --records PATH` picks the list of records out of a JSON response.
- Expressions: `+` joins text and adds numbers; `replace(text, pattern, replacement)`.
- Feed items take their date from `published_at`/`date` when the event has no timestamp;
  GitHub release notes arrive as plain text; rate-limited 403s say so.

## 0.3.0 - 2026-09-23

Third release: "Live". Alerts, a queryable history, trends, a live source and an MCP server.

- `webhook` output: one Discord or Slack message per event (format recognized from the URL),
  or the event as JSON. Mentions are disabled, Markdown is escaped, messages per run are capped
  with one summary message, rate limits are retried, and webhook URLs never appear in errors.
- `unlimited mcp [PIPELINE...]`: a Model Context Protocol server (stdio). Built-in tools
  fetch_page, read_feed, inspect_url and github, plus one tool per pipeline file (with `diff`
  state kept between calls). Results carry provenance; built-in tools refuse private and local
  addresses, including through redirects. Tested against the official MCP Python SDK.
- List and bool options of built-in components declare their defaults explicitly, so the
  Python API type-checks.
- `bluesky` source: new public posts, live, from Bluesky's Jetstream, filtered by words and
  language, with hashtags and links from post facets and an opaque per-run `author_key` for
  distinct counting; reconnects and resumes from its cursor.
  Optional dependency: `pip install "unlimitedpipe[live]"`.
- SIGTERM (docker stop, systemd, CI timeouts) now shuts down like Ctrl+C, closing outputs and
  saving state; JSONL files are flushed whenever the pipeline goes idle; `file -` streams JSONL
  from stdin instead of waiting for the end of the input.
- Trend engine: `extract` (hashtags, $cashtags, domains, words without stopwords, links,
  handles or dates, or any regex), `count --by FIELD [--every WINDOW] [--distinct FIELD]`
  (windows follow each event's time, in any order; `--distinct` counts people rather than
  posts), and `trend` (spikes against earlier windows as soon as a window completes, with
  history kept across runs). Windows the data only partly covers are marked and never
  compared, and values below a `--top` cut are not mistaken for new.
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
