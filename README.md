# UnlimitedPipe

[![PyPI](https://img.shields.io/pypi/v/unlimitedpipe)](https://pypi.org/project/unlimitedpipe/)
[![Python](https://img.shields.io/pypi/pyversions/unlimitedpipe)](https://pypi.org/project/unlimitedpipe/)
[![CI](https://github.com/Fuyuki0/unlimitedpipe/actions/workflows/ci.yml/badge.svg)](https://github.com/Fuyuki0/unlimitedpipe/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/Fuyuki0/unlimitedpipe/blob/main/LICENSE)
[![Model](https://img.shields.io/badge/%F0%9F%A4%97%20model-decide--0.5b-yellow)](https://huggingface.co/unlimitedpipe/decide-0.5b-GGUF)
[![Dataset](https://img.shields.io/badge/%F0%9F%A4%97%20dataset-2.85B%20tokens-yellow)](https://huggingface.co/datasets/unlimitedpipe/public-records)
[![Feeds](https://img.shields.io/badge/live%20feeds-98-brightgreen)](https://feeds.daemonfill.dev/)

**Pipe the public internet.**

Watch anything public (a price, a filing, a feed, a government page) and get only what
changed, with a link to where it came from. Search and ask 98 live feeds of public records and
news in one command, even offline, answered by a 0.5B model that cites its sources.
Local-first, free, no account, no API key.

![unlimited ask answering "any big crypto hacks this week?" and "earthquakes in japan in 2024" with cited sources](https://raw.githubusercontent.com/Fuyuki0/unlimitedpipe/main/docs/assets/ask.svg)

Install and set everything up with one command (it asks before each step):

```bash
curl -fsSL https://raw.githubusercontent.com/Fuyuki0/unlimitedpipe/main/install.sh | sh
```

It installs the `unlimited` command and runs `unlimited setup`, which adds what this machine can
use: the browser for JavaScript pages, the `ask` model (531 MB, runs on any laptop), the tools
and skill for Claude Code, and an offline copy of the feed catalog. Already have Python?
`pip install unlimitedpipe`, then `unlimited setup`.

```bash
unlimited search "cyber attack"                     # 98 live feeds at once, one request
unlimited ask "what happened in Bangkok today?"     # answered from the feeds, with sources
unlimited web https://example.com | unlimited diff               # only what changed
unlimited new https://some-shop.example/product     # writes a price-and-stock watch for you
unlimited mirror && unlimited search flood --catalog offline    # works without the internet
```

- **Change detection with proof.** Every result carries its source link and when it was
  fetched; `diff` remembers what it saw and reports only what is new, changed or gone.
- **[98 free feeds](https://feeds.daemonfill.dev/)** of public records and news on GitHub
  Actions: SEC filings and insider trades, sanctions, new rules, rate decisions, economic data
  and market closes, disasters and solar storms, disease outbreaks, crypto, business and tech,
  and news from every region. Earthquakes, tsunamis, storms, disaster alerts, solar storms,
  cloud outages and crypto hacks reach search, ask and the page within about a minute (a live
  copy on a small server, `unlimited watch --catalog`); other time-sensitive feeds (security,
  SEC filings, headlines) about every 2 minutes; the rest every hour. Each feed is a YAML file
  of about 15 lines; [fork them](https://github.com/Fuyuki0/unlimitedpipe-feeds).
- **History, not only the latest.** Every item the feeds ever listed stays in a monthly
  archive, 645,000 records back to 1900 (earthquakes, tsunamis, every US law since 1973, Fed
  rate decisions, disaster declarations, recalls, sanctions, federal rules, SEC filings, fund
  holdings, private raises, papers and more): ask about a year ("earthquakes in japan in
  2024", "crypto hacks in 2022") and the biggest come first, in about a second.
- **Answers that cite.** `ask` finds the facts with plain search, then a small local model
  trained for the job answers from them: on 40 blind questions typed the way people type, 90%
  of its answers pass (Qwen3.5 2B, four times its size, 87%), ahead of the 3 to 4B models we
  tried.
- **Open.** What it publishes is an [open protocol](docs/protocol.md) any tool can read or
  write, and its public-domain corpus of US government records is
  [on Hugging Face](https://huggingface.co/datasets/unlimitedpipe/public-records) (2.85 billion
  tokens, every document with its source).

## What people use it for

| You are | Try |
| --- | --- |
| An investor | `unlimited ask "biggest insider purchases this month"`, `unlimited follow berkshire hathaway --feed sec-fund-holdings --to ntfy:TOPIC` |
| A journalist or researcher | `unlimited ask "sec charges in 2015"`, `unlimited search "affordable care act" --since 2010`: every record links to its source, dated when it was first seen |
| Watching for disasters | `unlimited follow tsunami --to ntfy:TOPIC --every 5m`, `unlimited ask "earthquakes in japan in 2024"` |
| In Thailand | `unlimited ask "bangkok weather tomorrow"`, `unlimited ask "น้ำท่วมกรุงเทพตอนนี้เป็นอย่างไร"` |
| A developer or on call | `unlimited follow outage --feed cloud-status --to "$SLACK_WEBHOOK"`, `unlimited ask "fortinet vulnerability"` |
| Building AI agents | `claude mcp add unlimitedpipe -- unlimited mcp`: fresh public records with sources, as tools |
| Training or studying models | 1.25M public-record events and 2.85B tokens of government records on Hugging Face |

`follow` sends each new match once: to your phone with [ntfy](https://ntfy.sh) (free, no account:
install the app and subscribe to the topic you chose), or to Telegram, Discord, Slack or any
webhook.

## What is UnlimitedPipe?

A small set of Unix-style commands that pass **events** to each other:

```text
SOURCE  ->  EVENTS  ->  OPERATORS  ->  OUTPUT
web         JSONL       filter         json, jsonl, csv
rss                     select         feed (RSS / Atom / JSON Feed)
file                    diff           your terminal
...                     ...            any tool that reads JSONL
```

Every event is one line of JSON that records what was observed, where, when, how it was
fetched, and every step that touched it. Pipes work with `jq`, `grep`, `head` and friends.
The same components run from a YAML file with `unlimited run`.

## Why?

Everyone who works with the web has written the same throwaway script: fetch a page, pull out
a few values, compare with last time, send a notification. UnlimitedPipe is that script, done
once and done well:

- **Change detection built in.** `diff` remembers what it saw and emits only what was added,
  removed or modified, field by field.
- **Reads the most reliable layer first.** Product data from Shopify, schema.org JSON-LD or
  OpenGraph before any CSS selector. Feeds before HTML.
- **Provenance on every event.** Source URL, observation time, fetch method, and each operator
  that transformed it.
- **Polite by default.** robots.txt (RFC 9309), one request per second per host,
  `ETag`/`If-Modified-Since` revalidation, an honest User-Agent.
- **Composable.** JSONL in, JSONL out. Plain JSON from other tools is accepted too.
- **Extensible.** A connector is one small Python class; `pip install` makes it a command.

How it compares:

- **Yahoo Pipes** (2007–2015) had the right idea: wire feeds and pages together, filter them,
  get a feed out. It was a hosted app, and it died with its host. UnlimitedPipe is the same
  idea as local commands and text files you own; `publish` hosts the result for free on
  GitHub.
- **Huginn and n8n** are always-on servers with a database and a web UI. UnlimitedPipe needs
  neither: a pipeline is a YAML file, state is a small JSON file, and a schedule is cron or
  GitHub Actions.
- **RSS-Bridge and RSSHub** turn sites into feeds with a server and one bridge per site.
  UnlimitedPipe reads what sites already publish (feeds, JSON APIs, product data), filters and
  merges it, and writes feeds as one output among several.
- **changedetection.io** and paid monitors are apps. `diff` gives the same field-level change
  detection as a pipe stage you can combine with anything.
- **`curl | jq`** has no memory, no politeness and no change detection. **Firecrawl** and
  similar crawlers turn pages into text for LLMs; UnlimitedPipe turns public sources into
  typed events with history and receipts.

## Quick start

```bash
pip install unlimitedpipe          # Python 3.11+
```

Look at a page. In a terminal you get readable output; in a pipe you get JSONL.

```bash
unlimited web https://example.com
```

See what a site offers and the best way to read it:

```bash
unlimited inspect https://news.ycombinator.com
```

```text
Hacker News
https://news.ycombinator.com  ·  200  ·  text/html  ·  76 ms
✓ robots.txt    allowed
✗ JSON-LD       none
✗ Products      no product data
✗ OpenGraph     none
✓ Feeds         https://news.ycombinator.com/rss
✗ Sitemap       none found
✓ Readable HTML 666 words without JavaScript
Try:
  unlimited rss https://news.ycombinator.com/rss
  unlimited web https://news.ycombinator.com
  unlimited web https://news.ycombinator.com --selector 'h2'   # pick exact elements
```

Watch a product. The first run saves a baseline; later runs print only changes.

```bash
unlimited web https://www.allbirds.com/products/mens-strider-explore | unlimited diff
```

Or let UnlimitedPipe write the watch for you, then keep it running:

```bash
unlimited new https://www.allbirds.com/products/mens-strider-explore
# Wrote allbirds-com-products-mens-strider-explore.yml: price and stock changes (product data via shopify).
unlimited watch --every 1h allbirds-com-products-mens-strider-explore.yml
```

`new` picks the most reliable approach it finds: product data for store pages, the feed for
blogs and news sites, and page text otherwise, with commented hints for narrowing it down.

## Sources

| Command | Emits |
| --- | --- |
| `unlimited web URL...` | A `document` per page (title, description, headings, text, feeds). Pages with product data become one `product` per variant. `--selector CSS` emits `element`s, `--field NAME=CSS` builds `record`s, `--emit links` emits `link`s. `--browser` renders pages that need JavaScript first (optional extra), `--screenshot DIR` keeps a picture of each page as evidence. |
| `unlimited rss URL...` | One `entry` per item of an RSS, Atom or JSON Feed. Given a page, uses the feed it advertises. |
| `unlimited file PATH...` | One `record` per JSON item, JSONL line or CSV row. `-` reads stdin. |
| `unlimited github releases\|repo\|tags\|commits\|issues OWNER/REPO...` | Public GitHub data through the official REST API. Optional `GITHUB_TOKEN` for higher limits. |
| `unlimited mastodon tag:NAME\|@user\|trending` | Public Mastodon posts through the open API, no key. |
| `unlimited telegram CHANNEL...` | Posts of public Telegram channels, from their public web preview. |
| `unlimited youtube videos\|search ...` | Videos through the official YouTube Data API (free key: `YOUTUBE_API_KEY`). |
| `unlimited reddit r/NAME...` | Posts through Reddit's official API with your own free app (`REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`). |
| `unlimited x search\|posts ...` | Posts through X's official API with your own key (`X_BEARER_TOKEN`; reading needs a paid plan). |
| `unlimited bluesky [WORDS...]` | New public Bluesky posts, live, from Bluesky's Jetstream (endless; `pip install "unlimitedpipe[live]"`) |
| `unlimited sec insider-trades` | Insider purchases and sales as they are filed with the SEC: who, their role, shares, price and total value. Needs a contact email (`--contact` or `SEC_CONTACT`), as the SEC asks. |
| `unlimited sec activist-stakes` | New Schedule 13D filings: which investor disclosed 5% or more of which company. |
| `unlimited sec company-events` | 8-K filings that report a bankruptcy, a completed acquisition, layoffs, a delisting notice, an auditor change, a restatement, a change in control or a cyberattack. |
| `unlimited sec ipo-filings` | S-1 and F-1 registrations by companies going public (not public companies registering more shares). |

With `--since` and `--until` in the past, the SEC sources read that period from EDGAR's
full-text search, so `unlimited backfill` can fill a catalog with years of them.
| `unlimited search WORDS...` | Items from every feed of a published catalog that mention all the words, in one request (default catalog: [feeds.daemonfill.dev](https://feeds.daemonfill.dev/)). `--list-feeds` lists its feeds. |
| `unlimited ask QUESTION` | An `answer` to a question from a feed catalog, explained by a local model (Ollama) or Claude from numbered sources, which are always listed with their links. Optional: see [Ask](#ask). |
| `unlimited inspect URL...` | An `inspection`: robots.txt, feeds, JSON-LD, products, sitemap, JavaScript, suggested commands. |

Sources also read URLs from stdin, so crawls compose:

```bash
unlimited web https://blog.example.com --emit links | unlimited grep 2026 | unlimited web
```

Insider trades read like news, straight from the filings:

```text
$ unlimited sec insider-trades --min-value 500000
LENNAR CORP (LEN): Berkshire Hathaway Inc (10% owner) bought 1,679,700 shares at $81.19 ($136.4M)
PubMatic, Inc. (PUBM): Rajeev K. Goel (CHIEF EXECUTIVE OFFICER, director, 10% owner) sold 50,453 shares at $18.45 ($930.6K)
```

Public GitHub data comes through the official API, no account needed:

```bash
unlimited github releases astral-sh/uv ollama/ollama --limit 3
unlimited github repo pallets/click | unlimited select title stars forks
```

## Operators

| Command | Does |
| --- | --- |
| `select title price=offers.0.price link=link\|url` | Keep, rename, or fall back between fields |
| `filter 'price > 100 and availability == "InStock"'` | Keep matching events ([syntax](https://github.com/Fuyuki0/unlimitedpipe/blob/main/docs/expressions.md)) |
| `filter --field country --eq Thailand` | The same without expression syntax |
| `map 'price=number(price)' --drop junk` | Set fields from expressions, drop fields |
| `grep AI LLM` | Keep events mentioning any word (whole words, any case) |
| `dedupe --by url` | Drop repeats within the stream |
| `sort --by published_at -r` | Sort (reads the whole stream) |
| `limit 20` | First N events, then stop upstream |
| `diff` | Only what changed since the last run |
| `extract hashtags\|cashtags\|domains\|words\|REGEX` | Pull matches out of text into a list |
| `count --by tags --every 10m` | Count per value, overall or per time window |
| `trend` | Values rising sharply compared with earlier windows |

Fields are looked up in `data` first, then in the envelope (`source_url`, `metadata.status`).

## Outputs

| Command | Writes |
| --- | --- |
| `jsonl [PATH]` | Full events, one per line (`--data` for data only) |
| `json [PATH]` | One JSON array of data (`--full` for whole events) |
| `csv [PATH]` | Data as CSV, nested fields as dotted columns |
| `feed PATH` | RSS (`.xml`), Atom (`.atom`) or JSON Feed (`.json`), keeping earlier items |
| `webhook URL` | A Discord or Slack message per event (recognized from the URL), or the event as JSON |
| `sqlite FILE` | One row per distinct observation, with JSON columns for SQL queries |
| `pretty` | Readable terminal output (the default when stdout is a terminal) |

## Pipelines

The same components, in one process, from a file:

```yaml
# competitor-watch.yml
name: competitor-watch

sources:
  - type: web
    url: https://competitor.example/pricing
    each: .plan
    field: [name=.plan-name, price=.price]

operators:
  - type: diff
    key: name

outputs:
  - type: feed
    path: public/competitor.xml
  - type: pretty
```

```bash
unlimited run competitor-watch.yml
unlimited run competitor-watch.yml --validate
unlimited watch --every 1h competitor-watch.yml     # run it every hour until Ctrl+C
```

Short pipelines don't need a file. Separate stages with `--` and they run in one process:

```bash
unlimited run web https://example.com -- select title url -- json
unlimited watch --every 30m rss https://hnrss.org/frontpage -- grep AI -- diff --only added
```

`watch` keeps going when a run fails, reloads the pipeline file when you edit it, and adds a
little random delay so many watches don't hit a site at the same second.

Mistakes are reported with file, line and a suggestion:

```text
error: competitor-watch.yml:8: sources[0] (web): unknown option 'feild' for web
hint: did you mean 'field'?
```

## Publish a feed for free

`publish` turns a pipeline into a hosted feed: GitHub Actions runs it on a schedule, keeps the
diff state in your repository, and GitHub Pages serves the result. No server, no account
beyond GitHub.

```bash
unlimited publish feeds/*.yml --every 1h
# Wrote .github/workflows/unlimitedpipe-feeds.yml (runs every 1h, cron "54 * * * *")
# Wrote public/index.html
# ...
# Index: https://feeds.daemonfill.dev/
```

Live example: [the feed catalog](https://github.com/Fuyuki0/unlimitedpipe-feeds), 75+ feeds published this way from one
workflow. A feed whose source is down keeps its last good state while the others update. Each
JSON Feed carries full events, so another pipeline can read it with `unlimited rss` and keep
the provenance chain. Details, cron and manual setups:
[docs/pipelines.md](https://github.com/Fuyuki0/unlimitedpipe/blob/main/docs/pipelines.md).

## The Feed Catalog Protocol

What `publish` writes is an open format, not an UnlimitedPipe secret: a `feeds.json` that
lists a site's feeds and their latest items, feed files any reader understands, and a monthly
archive, all static files with a source link for every item. Any tool can write a catalog,
and every catalog can be searched, mirrored and asked the same way. The format is specified in
[docs/protocol.md](docs/protocol.md), with JSON Schemas in [docs/schemas](docs/schemas):

```bash
unlimited validate https://feeds.daemonfill.dev/     # check any catalog against the protocol
unlimited validate ./public --deep                   # and every feed file and archive month
```

Proposed next: discovery (`/.well-known/feed-catalog.json`), catalogs that list each other
as peers, and signed archives, so a copy can prove it is the original.

## Change detection

![UnlimitedPipe detecting a price change, a new plan and a removed plan on a pricing page](https://raw.githubusercontent.com/Fuyuki0/unlimitedpipe/main/docs/assets/demo.svg)

`diff` stores a small state file per watch and compares each item with the previous run:

- Items are matched by their key: product URL + SKU, feed item id, or `--key FIELD`.
- Changes come out as `change` events with field-level `old` and `new` values.
- An item counts as removed only if its page or feed was fetched in this run, so a network
  failure never looks like everything disappeared.
- `--only added` turns any feed into a stream of new items; add `webhook` to get each change
  as a Discord or Slack message. `--ignore FIELD` skips noisy
  fields. `--reset` starts a new baseline.

```json
{"type": "change", "key": "https://acme.example/pricing#Pro", "source_url": "https://acme.example/pricing",
 "data": {"change": "modified", "label": "Pro", "summary": "price: $49 → $59",
          "fields": [{"path": "price", "old": "$49", "new": "$59"}], "after": {"name": "Pro", "price": "$59"}}}
```

State lives in your platform's user state directory; set `UNLIMITEDPIPE_STATE_DIR` or
`diff --state FILE` to keep it elsewhere (for example, in a Git repository).

## AI integration

UnlimitedPipe is useful without AI. `ask` uses a small local model trained for it (see
[Ask](#ask)), and `search` and `ask` fall back to a 46 MB embedding model when words find
nothing; both run in Ollama on your machine. Agents can use UnlimitedPipe as a tool (see the
next section). To do more with events, pipe them into any LLM command-line tool:

```bash
unlimited web https://example.com/changelog | jq -r .data.text | llm "What changed?"
```

## Ask

`ask` answers a question from the feed catalog. Finding the facts is plain code, the same
matching as `search`; a model only explains what was found, citing numbered sources that are
always printed with their links. When nothing in the catalog matches, it says so without asking
a model.

Matching forgives the way people ask: a typo is searched as the catalog word one letter away
("bitcion"), common words the sources put differently match ("fed" finds the Federal Reserve,
"jobless" unemployment claims, "gdp" gross domestic product), and when no item has the
question's words at all, a small local model (all-minilm, 46 MB, installed by `unlimited
setup`) finds the items that mean the same ("delisted stocks" finds delisting notices).

```text
$ unlimited ask "any big insider buys this week?"
Found: CEMEX SAB DE CV (CX): Lozano Rogelio Zambrano (director) bought 400,800 shares at
$17.28 ($6.9M) [1]; DoubleLine Yield Opportunities Fund (DLY): Jeffrey J. Sherman (Vice
President) bought 10,000 shares at $13.03 ($130.3K) [2].

Sources (decided by hf.co/unlimitedpipe/decide-0.5b-GGUF:latest)
[1] CEMEX SAB DE CV (CX): Lozano Rogelio Zambrano (director) bought 400,800 shares...
[2] DoubleLine Yield Opportunities Fund (DLY): Jeffrey J. Sherman (Vice President) bought...
    https://www.sec.gov/Archives/edgar/data/1788399/000090445426000490/0000904454-26-000490-index.htm
```

It uses a local model through [Ollama](https://ollama.com) when it is running (free, and
nothing leaves your machine), otherwise Claude when `ANTHROPIC_API_KEY` is set. UnlimitedPipe
itself never needs a model.

The model `unlimited setup` installs is
[unlimitedpipe/decide-0.5b](https://huggingface.co/unlimitedpipe/decide-0.5b-GGUF), a 0.5B
decision model (531 MB): given the numbered sources and the question, it replies only with the
sources that answer it (`USE 2 5`) or `NONE`, and `ask` writes the answer from those sources'
own titles, dates and summaries. So the answer holds no word or number the sources do not, it
comes in a few seconds on a small computer, and the decision's probability says how sure it
was. It was trained on public data only, and graded strictly (an answer that says "not covered"
fails when a source answers) on questions typed the way people type ("microsoft news", "whats
new with bitget", "earthquakes in japan in 2024"), through `ask`'s own search, labelled by hand.
Three blind rounds, written before the model was trained:

| Model | Size | Blind (40) | Blind 2 (42) | Blind 3, the past (43) |
| --- | --- | --- | --- | --- |
| **unlimitedpipe/decide-0.5b, build 7** (decides; the code writes) | **0.5B** | **36 (90%)** | 27 (64%) | **37 (86%)** |
| unlimitedpipe/decide-0.5b, build 6 | 0.5B | 36 (90%) | 28 (67%) | 26 (60%) |
| unlimitedpipe/ask-0.5b (writes its answers) | 0.5B | 35 (87%) | | |
| Qwen3.5 2B | 1.9B | 35 (87%) | | |
| Phi-4 mini | 3.8B | 34 (85%) | | |
| Qwen3.5 4B | 4.2B | 31 (77%) | | |
| Llama 3.2 3B | 3.2B | 25 (62%) | | |

On the first round the 0.5B model is level with Qwen3.5 2B, a model four times its size (one
question ahead), and ahead of the 3 to 4B models. Build 7 learned questions about the past;
blind 3 is scored on 43 of its 46 questions, as three turn up word for word among build 7's
generated training questions, and it flatters build 7, whose data was made to fix build 6's
misses there. Its weak spot is saying "not covered" for some current questions a source does
answer ("crude oil price"); `ask` then still shows the closest sources. The model card has
every set and the other models' scores.

```bash
ollama pull hf.co/unlimitedpipe/decide-0.5b-GGUF     # or let unlimited setup do it
```

The answers read as lists of headlines; a larger general model explains more (`--model`). How
it was built and graded, with all the models: [research/ask](research/ask).

## History and offline

Every run of a published catalog also appends its new items to a monthly archive
(`archive/2026-09.jsonl`), so questions can reach back further than the latest items. A
question that names a year or a month reads the archive for it by itself:

```bash
unlimited ask "strongest earthquake in Japan in 2024?"   # the largest, picked by code
unlimited ask "ronin hack"                          # no date: the months its words are in
unlimited search sanctions march 2025
unlimited ask "how did the Ebola outbreak develop?" --since 2026-07
```

`backfill` fills the archive with a feed's past items, from sources that can be asked about
the past: an API that takes a date range (the feed's `${DAYS_AGO_N}` and `${TODAY}`) or a list
that keeps every item. It runs the feed's own pipeline once per month (or `--every` week,
quarter, year, 30d), so old items read like new ones, and leaves the feed's files and state
alone:

```bash
unlimited backfill feeds/earthquakes.yml --from 2016 --dry-run    # count first
unlimited backfill feeds/exploited-vulnerabilities.yml --from 2021
```

A catalog also works without the internet. `mirror` downloads it, including the search index,
the archive and the index page with its search box, into your offline copy (or a folder you
name). `search` and `ask` switch to that copy by themselves when the internet is down, and say
how old it is. `serve` shares it with other devices on the same network (a school, a newsroom,
a disaster area):

```bash
unlimited mirror --since 2026-08                    # run it again to refresh
unlimited search flood --catalog offline            # the offline copy, on purpose
unlimited ask "what happened in Bangkok?" --catalog offline   # with a local model
unlimited serve --lan                               # phones on the same Wi-Fi get the search page
unlimited mirror ~/feeds && unlimited serve ~/feeds # or any folder
```

## Platforms

Every platform is read through the door it offers: open APIs and feeds where they exist, and
your own key where a platform requires one (YouTube, Reddit, X). Nothing tries to get around
logins, paywalls or blocks. [docs/platforms.md](https://github.com/Fuyuki0/unlimitedpipe/blob/main/docs/platforms.md)
has the full table, and how to feed other tools' JSON into UnlimitedPipe's change detection.

`unlimited doctor` shows what works on your machine (network, browser, local AI, keys) and the
command that fixes each missing piece.

## For AI agents (MCP)

`unlimited mcp` is a Model Context Protocol server, so Claude, Cursor and other agents can
read the public web through UnlimitedPipe and cite where every value came from:

```bash
claude mcp add unlimitedpipe -- unlimited mcp                       # Claude Code
unlimited mcp competitor-watch.yml ai-news.yml                      # your pipelines as tools
```

To give an agent UnlimitedPipe as a skill, tell it:
`Install UnlimitedPipe: https://raw.githubusercontent.com/Fuyuki0/unlimitedpipe/main/docs/install-for-agents.md`.
It installs the command, runs `unlimited doctor`, and learns the commands from
[`skills/unlimitedpipe/SKILL.md`](https://github.com/Fuyuki0/unlimitedpipe/blob/main/skills/unlimitedpipe/SKILL.md).

Built-in tools: `search_feeds` and `list_feeds` (the whole public catalog, searched in one
request: ask "did any company disclose a cyberattack to the SEC this week?"), `fetch_page`
(products, documents or CSS selections), `read_feed`, `inspect_url` and `github`. Each pipeline file becomes a tool too, so an agent can ask "what
changed on the competitor's pricing page?" and get the `diff` result. Results are events with
their source URL, observation time and provenance. Built-in tools refuse private and local
addresses, including through redirects, so a page an agent reads cannot steer it into your
network.

## Creating a connector

A source is a small Python class. Its typed fields become CLI options, YAML keys and Python
arguments at once:

```python
from unlimitedpipe import Event, Source, arg, opt


class HackerNews(Source):
    """Search Hacker News stories."""

    name = "hackernews"
    query: str = arg("Search words")
    limit: int = opt("Maximum stories", default=30)

    async def collect(self, ctx):
        response = await ctx.http.get(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={"query": self.query, "tags": "story", "hitsPerPage": self.limit},
        )
        for hit in response.json()["hits"]:
            yield Event(source="hackernews", type="story", key=hit["objectID"],
                        data={"title": hit["title"], "url": hit["url"], "points": hit["points"]})
```

Register it with one entry point, `pip install` it, and `unlimited hackernews "local llm"`
works, with rate limiting, retries, robots.txt, `--help` and YAML support included.
[examples/plugin-hackernews](https://github.com/Fuyuki0/unlimitedpipe/tree/main/examples/plugin-hackernews) is a complete package to copy, and
[docs/connectors.md](https://github.com/Fuyuki0/unlimitedpipe/blob/main/docs/connectors.md) walks through creating, registering, testing,
documenting and submitting one.

## Architecture

- **Event** (`unlimitedpipe.event/1`): `id`, `source`, `type`, `key`, `source_url`,
  `timestamp`, `observed_at`, `data`, `metadata`, `provenance`. See [docs/events.md](https://github.com/Fuyuki0/unlimitedpipe/blob/main/docs/events.md).
- **Components** are dataclasses: sources implement `collect`, operators `process` or
  `apply`, outputs `open`/`write`/`close`. The CLI and YAML loader are generated from their
  fields.
- **Engine**: async generators chained source -> operators -> outputs. Streaming by default;
  only `sort` and whole-document outputs buffer. Stopping early (`limit`, Ctrl+C, a closed
  pipe) closes every stage, and outputs and diff state are always saved.
- **Network layer**: one shared client per run with per-host throttling, retries honoring
  `Retry-After`, RFC 9309 robots.txt with `Crawl-delay`, conditional requests, and a size cap.
- **Plugins**: the `unlimitedpipe.plugins` entry point group. Commands load lazily, so a pipe
  stage starts in about 150 ms.

```text
src/unlimitedpipe/
  event.py  component.py  engine.py  context.py  http.py  config.py  cli.py
  expr.py   watch.py  scaffold.py  publish.py  mcp.py
  sources/    web, rss, file, github, sec, bluesky, mastodon, telegram, youtube, reddit, x,
              search, ask, inspect
  operators/  select, filter, map, grep, dedupe, limit, sort, diff, extract, count, trend
  outputs/    jsonl, json, csv, feed, webhook, sqlite, pretty
```

## Examples

Runnable pipelines in [examples/](https://github.com/Fuyuki0/unlimitedpipe/tree/main/examples): website to JSON, an RSS news filter published as
a feed, GitHub release watching, price monitoring with Discord alerts, competitor pricing
watch, multi-source research into CSV, Bluesky trends, and a complete connector package. The
[feed catalog](https://github.com/Fuyuki0/unlimitedpipe-feeds/tree/main/feeds) has 75+
more.

## Research

[`research/`](research) holds experiments on UnlimitedPipe's data, with their results written
up, good or bad. Two short reads: [A 0.5B model that cites its sources: from 5% to
87%](docs/posts/a-small-model-that-cites.md) and [We tried a fruit fly's brain on the
news](docs/posts/fruit-fly-on-the-news.md).

- [A small model trained for `ask`](research/ask): a 0.5B model fine-tuned to answer from
  numbered sources, with citations, and to say plainly when the sources do not cover a
  question.
- [A fruit-fly brain circuit on news](research/fly): the fly's mushroom body did no better
  than plain compression; a main network with separate modules kept old knowledge when
  learning new feeds, where one model forgot it.
- [Public records](research/public): collectors for the dataset
  [unlimitedpipe/public-records](https://huggingface.co/datasets/unlimitedpipe/public-records),
  public-domain US government text (the Federal Register, SEC annual reports) with provenance
  for every document.

## Roadmap

- **v0.1 Pipe**: engine, CLI, `web` with product detection, `rss`, `file`, `inspect`, eight
  operators, JSON/JSONL/CSV/feed outputs, YAML pipelines, plugins.
- **v0.2 Feed**: `watch`, `new`, `publish` (free hosted feeds), the `github` connector.
- **v0.3 Live**: `webhook` (Discord, Slack), `sqlite`, the trend engine
  (`extract`, `count`, `trend`), the live `bluesky` source, and the MCP server for AI agents.
- **v0.4 Search**: `search` across a whole feed catalog, `catalog` indexes,
  `list_feeds`/`search_feeds` for AI agents, the `sec` source for insider trades, arithmetic
  and `short()` in expressions.
- **v0.5 Ask**: `ask` answers questions from the catalog with a local model or Claude,
  always with sources; published index pages get a search box; feed health in the catalog.
- **v0.6 Browser**: `web --browser` renders pages that need JavaScript in a headless
  browser under the same rules (robots.txt, pacing, honest User-Agent), with screenshots as
  evidence.
- **v0.7 Platforms**: `mastodon`, `telegram`, `youtube`, `reddit` and `x` through
  their official doors, `unlimited doctor`, and a skill file for AI agents.
- **v0.8 History**: a monthly archive of every catalog item, `--since` for
  `search`, `ask` and the MCP tool, local catalogs, `mirror` and `serve` for offline use.
- **v0.9 Setup**: a one-line installer and `unlimited setup`, which sets up the
  browser, a local AI model, Claude Code's tools and skill, and an offline catalog.
- **v0.10 Open** (current): the Feed Catalog Protocol with `unlimited validate`, a 0.5B model
  trained for `ask` on public data (90% on blind questions typed the way people type, level
  with Qwen3.5 2B), and the public dataset unlimitedpipe/public-records.
- **Next**: searching the archive from the web page,
  bot-network filtering for trends, a network of catalogs.

## Responsible use

UnlimitedPipe is for public data and data you are authorized to access. It uses the front
door: official APIs and feeds when they exist, polite HTML otherwise. It does not bypass
logins, CAPTCHAs or blocks, and it is not for collecting data about individuals. You are
responsible for complying with each site's terms and applicable law. See
[docs/responsible-use.md](https://github.com/Fuyuki0/unlimitedpipe/blob/main/docs/responsible-use.md).

## Contributing

Connectors, recipes and bug reports are all welcome. Start with
[CONTRIBUTING.md](https://github.com/Fuyuki0/unlimitedpipe/blob/main/CONTRIBUTING.md); `make test lint` runs the same checks as CI.

## License

[Apache-2.0](https://github.com/Fuyuki0/unlimitedpipe/blob/main/LICENSE)
