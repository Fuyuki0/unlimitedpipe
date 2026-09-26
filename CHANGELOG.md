# Changelog

All notable changes are listed here. The project follows [Semantic Versioning](https://semver.org/);
the event format is versioned separately by its `schema` field (see docs/events.md).

## 0.9.1 - 2026-09-26

"Checked": fixes from using everything as a new user would, checked against the live
catalog, and what the catalog needed to grow from 54 feeds to 77.

- `unlimited sec activist-stakes`: new Schedule 13D filings, an investor owning 5% or more
  of a company, with the company and its investors joined into one readable line.
- `web --records PATH` also takes a JSON object keyed by id (DefiLlama's and Kraken's
  prices): each entry becomes a record with its `key`. JSON served under another content type
  (NASA's EONET says `application/rss+xml`) is read as JSON.
- Expressions: `commas(x, digits)` (`84,079.69`) and `title(s)`.
- Dates with an offset are converted to UTC: a feed wrote 17:11-04:00 as 17:11Z, four hours
  off, for every source that gives local times.
- `rss` survives map data feedparser cannot read (a GML `srsName` URL made it throw), and
  company names from EDGAR keep their initials (`AJB Capital LLC`, not `Ajb Capital Llc`).
- A personal example for Thai gold prices (`examples/thai-gold-price`), from a page that needs
  JavaScript; its terms allow personal use only, so it is not in the public catalog.
- `setup --skip` takes steps with commas too (`--skip browser,ai`).

- Search results no longer crash in a terminal: the readable output expected a feed's details
  where a catalog gives its name. Headlines wrap instead of losing their end (the dollar value
  of an insider trade), and `search --list-feeds` shows each feed's health.
- The archive kept only one item of a feed whose items all link to the same page (30 crypto
  hacks became 1; volcano reports and typhoon warnings too). Items are now keyed by feed, link
  and title; archives written before are read with the new keys, so nothing is duplicated and
  the missing items come back on the next run. A story that two sources list twice is listed
  once in the catalog.
- `rss` links are web pages: an Atom entry whose id comes before its links (the US Tsunami
  Warning Centers) linked to `urn:uuid:...`.
- `ask` answers only what the catalog covers. Items covering more of the question come first;
  "today" or "this week" leaves out older items; a question only half matched ("bitcoin price",
  when the catalog has Bitcoin Core releases) lists the closest items without asking a model;
  and numbers in an answer that appear in none of the sources are flagged.
- Thai questions and searches are split into words ("ราคาทองวันนี้" is ราคา + ทอง), and Thai
  news words also match their English equivalents, so a Thai question finds English sources.
  English words match their other forms: "hacks" finds "hacked", "buys" finds "bought".
- Without the internet, `search` and `ask` use the offline copy `unlimited setup` saved, and
  say how old it is.
- Every source command takes `--limit N`; `search --feed NAME` without words lists a feed's
  latest items.
- MCP: `list_feeds` returns names and descriptions only (a third of the size), results are
  compact JSON, and an empty search tells the agent what to try next.
- `publish` refuses to publish the folder the pipelines are in. `new` writes a description, a
  feed link to the watched site, and a commented `browser: true` for pages that need JavaScript.
- Readable output: posts older than today show their date, pages rendered in a browser say so
  and show the screenshot path, links show in full, and Mastodon hashtags read `#Thailand`,
  not `# Thailand`.
- A search that finds nothing says so and what to try, instead of printing nothing; a feed
  name that does not exist is an error with a suggestion (`insider-trade`: did you mean
  `insider-trades`?).
- `ask` caps a local model's answer length: a small model repeating itself could run for
  minutes on a CPU. Models under 3B parameters are asked for two sentences, as they make
  things up once they ramble.
- `ask` weighs rare words above common ones ("bitcoin" over "price"), ignores filler ("I think
  it is called"), and names what the catalog lacks when it declines ("Nothing in the catalog
  is about market, set100"). A made-up percentage is flagged even when a source is numbered
  [10], and numbers inside names (the 100 in SET100) are not taken for facts.
- The offline copy lives in the user's data folder (it was `~/unlimited/catalog`, which could
  land inside a cloned repository). `mirror` and `serve` use it when no folder is given, and
  `--catalog offline` searches it on purpose.

## 0.9.0 - 2026-09-26

"Setup": one command.

- `install.sh`: `curl -fsSL .../install.sh | sh` installs `unlimited` with uv, pipx or pip,
  then runs `unlimited setup`. It runs the command it just installed, even when an older one
  comes first on the PATH, and asks its questions on the terminal when piped from curl.
- `unlimited setup` checks the machine, then sets up (asking first, or all with `--yes`, each
  step skippable with `--skip`): Playwright and Chromium; Ollama and a model sized for the
  machine's memory (0.5B to 7B); the MCP tools and skill for Claude Code, registered with the
  running copy; and an offline copy of the catalog with three months of archive. Steps already
  done are skipped, so it is safe to run again. Without a terminal and `--yes` it only checks.
- The agent skill ships inside the package.

## 0.8.0 - 2026-09-26

"History": look back, and work offline.

- `unlimited catalog` appends every new item to a monthly archive next to `feeds.json`
  (`archive/YYYY-MM.jsonl`, by the item's date or when it was first seen), each once, with an
  `archive/index.json` of the months. The files only grow at the end.
- `search --since DATE` and `ask --since DATE` also search the archive from that month or day
  on; the MCP tool `search_feeds` takes `since` too.
- A catalog can be a local folder or file (`--catalog ~/feeds`), so search and ask work offline.
- `unlimited mirror DIR` downloads a catalog (search index, archive, index page, and with
  `--feeds` every feed file) into a folder; it never writes outside it.
- `unlimited serve DIR` serves such a folder, search box included, on this machine or with
  `--lan` to the local network, and warns when the address is public.

## 0.7.0 - 2026-09-26

"Platforms": social platforms through their official doors, and a skill for AI agents.

- `mastodon`: hashtags, accounts and trending posts from any Mastodon server's open API.
- `telegram`: posts of public Telegram channels, from their public web preview.
- `youtube`: a channel's uploads or a search, through the official Data API (free key).
- `reddit`: subreddit listings and searches through Reddit's official API, signed in as the
  user's own free app (Reddit's robots.txt disallows crawling; its terms allow API use for
  non-commercial purposes).
- `x`: searches and accounts through X's official API, with the user's own bearer token.
- All of them emit `post` (or `video`) events with the same fields: title, text, author, url,
  time, tags, links and counts, so pipes treat every platform alike.
- `unlimited doctor` (and `--json`) checks the network, the catalog, optional extras, local AI
  and API keys, with the command that fixes each missing piece; key values are never shown.
- `skills/unlimitedpipe/SKILL.md` teaches AI agents the commands, and
  `docs/install-for-agents.md` is a one-line install for them. `docs/platforms.md` explains
  what each platform needs.

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
