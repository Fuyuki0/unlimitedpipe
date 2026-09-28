# Feed Catalog Protocol

A way for any website to publish **what it follows and what changed**, as static files that
anyone can read: people in a browser, feed readers, scripts, and AI agents. No server to run,
no account, no API key; a folder on GitHub Pages, a USB stick or a school's Wi-Fi works.

UnlimitedPipe writes and reads this format, and [feeds.daemonfill.dev](https://feeds.daemonfill.dev/)
is a live example, but the protocol does not depend on UnlimitedPipe: anything that writes
these files is a catalog, and anything that reads them can use every catalog.

Status: **version 1**. Sections 1 to 4 describe what is published today. Sections 5 to 7 are
proposed extensions, not implemented yet.

The key words MUST, SHOULD and MAY are used as in RFC 2119.

## Principles

- **Static files.** JSON (UTF-8) and feed files served over HTTP GET, or read from a folder.
- **Provenance.** Every item links to where it came from; full items say when and how they
  were fetched.
- **Relative paths.** Paths inside a catalog are relative to `feeds.json`, so a copy works
  under any domain or folder (mirrors, offline copies).
- **Versioned.** Each document names its format in a `schema` field. Within a major version,
  fields may be added but never removed or renamed; readers MUST ignore fields they do not
  know, and MUST refuse a major version they do not know.
- **Front door.** Content comes from public sources read politely (robots.txt, rate limits,
  official APIs). A catalog SHOULD NOT carry data taken from behind logins or paywalls.

## 1. The catalog: `feeds.json`

One document that lists a site's feeds and their latest items, so a whole site can be searched
with one request.

```json
{
  "schema": "unlimitedpipe.catalog/1",
  "title": "UnlimitedPipe public feeds",
  "archive": "archive/index.json",
  "feeds": [
    {
      "name": "insider-trades",
      "description": "Insider purchases and sales worth $100K or more (SEC Form 4)",
      "files": ["insider-trades.xml", "insider-trades.json"],
      "health": {"status": "ok", "since": "2026-09-26T03:37:34Z", "latest": "2026-09-26T02:08:07Z"}
    }
  ],
  "items": [
    {
      "feed": "insider-trades",
      "title": "GigaCloud Technology Inc (GCT): Marshall Bernes (director) sold 18,297 shares at $54.13 ($990.4K)",
      "summary": "Traded 2026-09-24.",
      "link": "https://www.sec.gov/Archives/edgar/data/2045034/000204503426000009/0002045034-26-000009-index.htm",
      "date": "2026-09-26T02:08:07Z"
    }
  ]
}
```

| Field | Rule |
| --- | --- |
| `schema` | MUST be `unlimitedpipe.catalog/1`. |
| `title` | SHOULD name the catalog. |
| `feeds` | MUST be a list. Each feed has a `name` (MUST, unique, lowercase letters, digits and `-`), a `description` (SHOULD say what it follows), `files` (MUST, paths of the feed's files: RSS, Atom or JSON Feed), and MAY have `health`. |
| `health` | `status`: `ok` (the last run worked), `partial` (some sources failed) or `failing`; `since`: when that status began; `latest`: the newest item's date. |
| `items` | MUST be a list of the latest items of every feed, newest first. Each has `feed` (a feed's `name`), `title` (MUST), `link` (SHOULD, an absolute URL of the original), `date` (ISO 8601, UTC, or null) and `summary` (text or null). A catalog SHOULD list the same story once per feed. |
| `archive` | MAY point to the archive index (section 3). |

## 2. Feed files

Each feed's `files` are ordinary feeds: RSS 2.0, Atom 1.0 or JSON Feed 1.1, so any feed reader
can subscribe. A JSON Feed item MAY carry the full event (section 4) under
`_unlimitedpipe.event`, which lets other pipelines read it back with its provenance.

## 3. The archive

Every item a catalog ever listed, one file per month, so searches can reach back further than
the latest items. The files only grow at the end, which keeps them cheap to store and mirror.

`archive/index.json`:

```json
{"schema": "unlimitedpipe.archive/1", "months": [{"month": "2026-09", "file": "2026-09.jsonl", "items": 1995}]}
```

`archive/2026-09.jsonl`: one item per line, as in `feeds.json`, plus `key` and `seen`:

```json
{"feed": "stablecoin-supply", "title": "USDC supply +$205.9M in a day, now $76.6B", "summary": "...", "link": "https://defillama.com/stablecoin/usd-coin", "date": "2026-09-26T12:15:10Z", "key": "9653693d8e7537a6", "seen": "2026-09-26T12:15:49Z"}
```

| Field | Rule |
| --- | --- |
| `months` | Newest first; `month` is `YYYY-MM`, `file` is a path next to the index, `items` its line count. |
| `key` | Identifies the item across runs: the first 16 hex digits of SHA-256 over `feed`, `link` and the title (whitespace collapsed, case folded), joined by newlines. Readers MUST recompute it rather than trust the stored value when they merge archives. |
| `seen` | When the catalog first listed the item. An item goes into the month of its `date`, or of `seen` when it has no date. |

Each month may also be split by feed, `archive/2024-02/sec-ipo-filings.jsonl`, the same lines
grouped by their `feed`; the index then lists each month's `feeds` and their item counts
(`{"month": "2024-02", "file": "2024-02.jsonl", "items": 1234, "feeds": {"sec-ipo-filings": 55,
...}}`). The month files stay, so readers that do not know the split keep working; a reader
uses the split only when its counts add up to the month's `items`, and reads the whole month
otherwise. `archive/words-by-feed.json` (optional) lists, for each title word, the feeds and
months it appears in (`{"words": {"japan": {"earthquakes": ["2024-01", ...]}}}`), so a question
about a period reads only the feeds that can hold its words, and the feeds whose name or
description has them.

`archive/words.json` (optional) lists the months each title word appears in, so a reader can
answer a question that names no date by reading only the months that can answer it:

```json
{"schema": "unlimitedpipe.archive-words/1", "words": {"ronin": ["2022-03", "2024-08"]}}
```

Words are lowercased and stemmed as `search` stems them; numbers and words of one or two
letters are left out. A word in more than 12 months also has keys by feed, `word@feed`, when it
appears in fewer months in that feed ("reddit@sec-ipo-filings": ["2024-02"]), for up to 120
months; a question word that names a feed ("ipo") then narrows the others to that feed.

## 4. Events

Full items are `unlimitedpipe.event/1` events, described in [events.md](events.md): the data,
where it came from (`source_url`), when it was observed (`observed_at`), how it was fetched
(`metadata`), and every step it went through (`provenance`).

## 5. Discovery (proposed)

A site says it has a catalog with either:

- `/.well-known/feed-catalog.json`: `{"catalog": "https://example.org/feeds.json"}`; or
- in its HTML pages: `<link rel="feed-catalog" href="/feeds.json">`.

An agent or a reader visiting any site can then find what it follows without guessing.

## 6. Peers (proposed)

A catalog MAY list other catalogs it trusts, in `peers.json` next to `feeds.json`:

```json
{"schema": "unlimitedpipe.peers/1", "peers": [{"url": "https://thai-feeds.example/", "topics": ["thailand"], "language": "th"}]}
```

A reader searching one catalog MAY also search its peers (to a depth it chooses), merging
results by item `key`. Catalogs then form a network without a central owner.

## 7. Signatures (proposed)

So that a mirror (an offline copy, a USB stick in a disaster area) can prove its data is the
original: the discovery document names an Ed25519 public key, and the archive index carries
the SHA-256 of each month file and a signature over the index. A reader verifies the index,
then each file it reads.

## Validating a catalog

```bash
unlimited validate https://feeds.daemonfill.dev/        # or a folder: unlimited validate ~/feeds
```

JSON Schemas for sections 1 and 3 are in [schemas/](schemas/).
