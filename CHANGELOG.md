# Changelog

All notable changes are listed here. The project follows [Semantic Versioning](https://semver.org/);
the event format is versioned separately by its `schema` field (see docs/events.md).

## 0.10.51 - 2026-10-04

- Archive: records are written with Unicode line separators (U+2028, U+2029, U+0085) escaped and
  read by splitting at newlines only, so a title holding one is no longer cut in two.
- `ask`: a record listed by two feeds (a Fed decision in fed-funds-target and rate-decisions) is
  shown once; storms are ranked by their winds ("strongest typhoon 2013").
- History scripts for GOV.UK, World Bank tenders, EU laws, Wikipedia's year-in-country articles,
  papers (Hugging Face Daily Papers, medRxiv), CERT-EU, Canada and Australia government news and
  FDA press announcements; history appends skip each feed's live period.

## 0.10.50 - 2026-10-04

- `unlimited current-events`: the day's events from Wikipedia's Current events portal, one item
  per event, with its section, topic and the news reports it cites (text under CC BY-SA 4.0,
  credited in each summary).
- History scripts in research/public for world events since 2002 (Wikipedia), western Pacific
  typhoons since 1951 (JMA best track), strong geomagnetic storms since 1932 (GFZ Kp), crypto
  moves and stablecoin depegs (DefiLlama), DeFi deposit drops (DefiLlama), Hacker News top
  stories and Show HN since 2007, orbital launches since 1957 (Launch Library 2), central bank
  rate decisions (ECB, Bank of England, Bank of Canada, RBA), earnings releases of large
  companies since 2018 (SEC bulk submissions), FDA new molecular entities before 2022
  (Drugs@FDA) and UK bills since 2007.

## 0.10.49 - 2026-10-04

- `unlimited evm aave|liquidations|transfers|new-pools --chain ethereum|base`: on-chain events
  from public JSON-RPC endpoints (or yours: `$ETHEREUM_RPC_URL`, `$BASE_RPC_URL`). Aave V3
  markets at 90% utilization or more, with borrowing and lending rates; Aave V3 liquidations of
  $100K or more, priced by Aave's oracle; USDT and USDC transfers of $25M or more, mints and
  burns included and flash loans left out; new Uniswap V2 and V3 pools against WETH, USDC or
  USDT once $100K is in them.
- `usaspending`: recipients decoded and named the way round ("California Department of Health
  Care Services").

## 0.10.48 - 2026-10-04

- `unlimited hyperliquid`: Hyperliquid's perpetual futures with extreme funding (0.01% an
  hour either way by default) and $50M or more open, saying who pays whom ("MON funding on
  Hyperliquid: +0.0106% an hour (+93% a year), open interest $62.9M"); `--coin BTC
  --min-funding 0` for one market as it is.
- research: `usaspending_history.py` collects new federal contracts and grants of $100M or
  more since 2008 for the us-contracts and us-grants feeds.
- (0.10.47 was tagged without its version number and not released.)

## 0.10.46 - 2026-10-04

- `quakes` also reads BMKG (Indonesia: magnitude 5 or more, places in English compass points,
  "tsunami possible" when BMKG says so) and GeoNet (New Zealand's felt quakes).
- `sec company-events --item 2.02`: follow any 8-K item, e.g. earnings releases
  ("Tesla, Inc.: earnings release"); the default stays the major events.

## 0.10.45 - 2026-10-03

- Archives keep months before the last two compressed (`YYYY-MM.jsonl.gz`, and their files by
  feed), as the index names them (`"packed": true`): the public catalog's 633 MB of history
  becomes 190 MB, and rebuilding its indexes takes less time and memory (39 s instead of 48).
  A late item for a closed month opens it, and the same run closes it again. `search`, `ask`,
  the index page, `mirror` and `validate` read compressed months; older versions of
  UnlimitedPipe do not, so update to search the archive.

## 0.10.44 - 2026-10-03

- `unlimited faa`: US airport ground stops, ground delay programs and long departure or
  arrival delays, from the FAA's National Airspace System status ("Ground stop at Orlando
  (MCO): thunderstorms, until 4:30 pm EDT").
- `unlimited usaspending contracts|grants`: new US federal contracts and grants of at least
  $100M (`--min-value`), biggest first, from USAspending.gov ("Clark Construction Group LLC won
  a $332M contract from the Department of Homeland Security").

## 0.10.43 - 2026-10-03

- `unlimited quakes`: earthquakes as soon as the first of three agencies reports them, one
  item per quake. GFZ (Germany) usually locates quakes anywhere within about ten minutes, JMA
  (Japan) reports Japan's within two or three (English place names, JMA intensity), and USGS
  reports US quakes within minutes but many elsewhere only after 15 to 30. Reports of one
  quake are matched by time and place; each quake keeps its first report, and the summary
  names every agency that has reported it.

## 0.10.42 - 2026-10-03

- `search`, `ask` and the index page: four-letter words match only their own endings ("noto"
  finds the Noto Peninsula earthquake, not "notoriously"; "gold" is not "Goldman"); "tech"
  still finds "technology", and "spac" finds blank-check companies ("... Acquisition Corp").
  On the index page, words of three letters or fewer match only whole words with plural and
  verb endings, as `search` does ("ai" is not "aid").

## 0.10.41 - 2026-10-03

- `watch --catalog`: a file can run more often than the rest (`feeds/filings.yml@30s`), in
  the same process and the same feeds.json.
- `webhook --header "Name: value"`: e.g. a token for your own ntfy server, which then lets
  only you post. Kept out of provenance and outputs.
- `ask`: "announce", "say" and "pass" are question words; "congress" finds public laws and
  "sanctions" finds OFAC's designations ("what new laws did congress pass?" no longer starts
  with an EU regulation).

## 0.10.40 - 2026-10-03

- Feed links keep their parameters as written: a link like the FEC's `fecimg/?2026...777` no
  longer gets an `=` added when tracking parameters are taken out.
- `fec`: more short words in committee names read as words ("Americans for Tax Reform").

## 0.10.39 - 2026-10-03

- `ask`: in a feed another word of the question names, a word of the feed's title counts for
  each of its items, unless the items' own titles use it ("biggest election spending in 2024"
  now finds the FEC's $30M, not a $500K item from a committee with "Election" in its name).
  For superlatives and questions about the past, every item of the named feed that has all
  the words is ranked, not only the strongest matches.
- `fec`: candidates and committees read as people write them ("Pat Harrigan", "Joseph R Biden
  Jr", "Donald J. Trump", "Get Our Jobs Back, Inc", "... Employees People").

## 0.10.38 - 2026-10-03

- `unlimited fec outside-spending`: what super PACs, parties and other committees report
  spending for or against US federal candidates, from the FEC's daily bulk files ("America PAC
  spent $1.1M opposing James Talarico for the Senate (TX)"). Only committees in the FEC's
  committee list count (the files also hold forms filed with made-up amounts); the latest
  amendment of each expenditure wins; dated when filed. www.fec.gov's ten-second crawl delay
  is kept.

## 0.10.37 - 2026-10-03

- `unlimited follow WORDS --to TARGET`: each new match of the feed catalog (and its live
  copy) is sent once, to a phone through ntfy (`--to ntfy:TOPIC`: free, no account), or to
  Telegram, Discord, Slack or any webhook; printed without `--to`. The first run notes what
  matches now and sends nothing; `--test` sends the newest match at once; `--every 5m` keeps
  following. Only items with every word count (no matches by meaning).
- `webhook` sends ntfy notifications (title, summary, a tap that opens the source) and
  Telegram messages (`https://api.telegram.org/botTOKEN/sendMessage?chat_id=ID`), plain text.
- `publish --example WORDS`: searches to try, as buttons under the index page's search box;
  one naming a year also searches the archive. The page also explains `follow`.
- `--since` takes a year (`--since 2010`).
- `search --exact`: only items with every word, and no hint when none matches.
- README: what people use it for, one command each.

## 0.10.36 - 2026-10-03

- Questions without a rare word ("affordable care act", "berkshire hathaway 13f") read the
  archive months where all their words appear, newest first, instead of finding nothing.
- "signed" also matches "became public law" ("new laws signed this month").

## 0.10.35 - 2026-10-03

- `sec private-raises` says "reported raising $X": amounts are as filed, and some Form D
  filings carry typos (billions for millions).
- `sec fund-holdings` decodes manager names ("JPMorgan Chase & Co", not "&amp;").
- Readable names keep the capitals their owners use: JPMorgan, BlackRock, SoftBank, PayPal,
  FedEx, iShares, PIMCO, TIAA, USAA.

## 0.10.34 - 2026-10-03

- `web --header "Name: value"` (repeatable; `header:` in a pipeline file, with `${VARIABLE}`):
  sends a request header such as an API key, kept out of provenance and outputs, unlike a key
  in the URL.
- `sec private-raises`: new Form D filings, who raised how much privately in what business
  ("Acme Robotics Inc raised $50M privately (other technology, Form D)"); amendments left out.
- `sec fund-holdings`: 13F holdings reports, which manager reported how much in how many
  positions for which quarter. A report whose values look filed in thousands rather than
  dollars (under $1,000 a position, or over $10 trillion) is left out, not shown 1,000 times
  too small.
- Both remember the filings they read, so `--limit` goes up to 1,000 for them.

## 0.10.33 - 2026-09-29

- For "biggest" and "smallest" questions that name a feed ("biggest earthquake ever"), that
  feed's items are compared: the M 9.5 of 1960 in Chile, not a tsunami whose summary names the
  earthquake behind it.

## 0.10.32 - 2026-09-29

- `ask` reads an item's size more carefully for "biggest", "strongest" and past questions:
  NASA's "Earthquake 7.5M" is a magnitude, not 7.5 million; a year is never a size; "(1,204,337
  affected)" and "+20.4%" are; a number deep in a title without a colon ("Report for 10
  September") is not. "biggest tsunami ever" starts with Lituya Bay, 1958 (524.6 m).

## 0.10.31 - 2026-09-29

- "ever" and "all time" search the whole archive, now back to 1900, not from 1970: "biggest
  earthquake ever" finds the M 9.5 of 1960 in Chile.

## 0.10.30 - 2026-09-29

- `validate --deep` accepts archives that go back more than a century (earthquakes since 1900,
  disaster declarations since 1953): a date is flagged when it is before 1800, or on 1 January
  1970 at a whole hour (an empty date read as Unix time zero), not when it is before 1990.

## 0.10.29 - 2026-09-28

- `archive: false` in a pipeline file: the catalog lists the feed's latest items but never
  adds them to its archive, for data whose owner allows showing the latest value but not
  republishing its history (stock indices through FRED). The catalog marks such feeds.

## 0.10.28 - 2026-09-28

- A live lane: `unlimited watch --every 1m --catalog a.yml b.yml ...` runs several pipelines
  side by side each round in one process, and writes feeds.json for them next to their
  outputs (no archive). `publish --live URL` names such a copy in the catalog (`live`, see the
  protocol), and `search`, `ask` and the index page merge its newer items in when it answers
  within 3 seconds, and use the catalog alone otherwise.
- Feed files are written whole (a web server may serve them while they change).

## 0.10.27 - 2026-09-28

- `publish` workflows run their pipelines side by side, six at a time, so a lane takes as long
  as its slowest source rather than the sum of all (the catalog's express lane: 1.5-3 minutes
  down to under half a minute). Each pipeline's log is grouped under its name.
- A run with nothing new commits its state but skips the Pages upload and deploy.
- The HTTP cache writes its files whole (pipelines side by side share it).
- The index page asks the server whether feeds.json and the archive index changed each time,
  rather than keeping them 10 minutes.

## 0.10.26 - 2026-09-28

- A listing that answers a yes-or-no question starts with "Found:", not "Yes:": "is there a
  tsunami warning?" can find information bulletins that say there is no threat, and "Yes"
  would claim a warning.

## 0.10.25 - 2026-09-28

From 45 new questions asked the way a first-day user would, answers that were wrong or
misleading:

- "biggest crypto hacks ever": "ever" and "all time" search the whole archive (LuBian $3.5B,
  Bybit $1.4B, Ronin $624M), not only the latest items.
- "biggest earthquake this year": an earthquake's size is its magnitude wherever the title has
  it ("bulletin: M5.5 120 miles W of ..." is 5.5, not 120).
- "10 year treasury yield today": when an older item has more of the question's words than
  anything recent (FRED publishes days later), `ask` shows it, and says how old it is with its
  headline: "The latest that does is from 2026-09-24: US 10-year Treasury yield: 5.18%".
- "new critical vulnerabilities in chrome": a listing whose newest item is more than 45 days
  old is no longer called "Latest"; it says "Nothing recent" and dates each item.
- "is there a tsunami warning?": "warning" also matches alerts, advisories and bulletins.
- "biggest insider purchases this month", "tesla insider sales 2025": "purchases" matches
  "bought" and "sales" matches "sold" (and no longer "Chief Purchasing Officer").
- Updates of one feed are listed newest first ("new ollama version").

## 0.10.24 - 2026-09-28

- An offline copy's archive index lists only the months it holds (`unlimited setup` copies
  three), so a question about an older month no longer stops with "cannot read
  .../2024-12.jsonl". Months that cannot be read, in older copies or when a site is out of
  reach, are left out with one warning that says how to copy them.

## 0.10.23 - 2026-09-28

- `ask` without any model (no Ollama, no ANTHROPIC_API_KEY) lists the best matches with their
  sources instead of stopping with an error, and says how to get answers: `unlimited setup`
  or the decide model. The old hints named `qwen2.5:3b`.

## 0.10.22 - 2026-09-28

- `ask`: "big", "large", "huge" and "massive" put the biggest matching items first ("what are
  the latest big insider trades?" starts with the largest recent trades, not the newest
  $129K one; "any big crypto hacks this week?" with the $387M one).
- `doctor` names the model `ask` really answers with (the decide model when pulled), and says
  a newer build is out only when the model file changed on Hugging Face, not its card.
- README: 89 feeds, the express lane every 5 minutes and the rest every hour, and the archive
  of 300,000 records back to 2000.

## 0.10.21 - 2026-09-28

- `ask` about the past puts the biggest events first where the items are events with sizes
  (dollar amounts, earthquake magnitudes): "earthquakes in japan in 2024" starts with the M 7.5
  Noto Peninsula earthquake, not the last small ones of December; "crypto hacks in 2022" with
  Ronin ($624M), and "ronin hack" with that one rather than its $12M hack of 2024. A series
  ("fed funds rate in 2019") and questions about now keep the newest first.
- `sec insider-trades`: a price a share over $10,000 on a trade that would be worth more than
  $5B is a filer's mistake (often the total where the price goes); the title shows the price as
  filed and says it is not plausible, instead of a trade worth "$325T".

## 0.10.20 - 2026-09-28

- `ask` and `search` know the acronyms of US agencies as the Federal Register names them
  ("epa" finds "Environmental Protection Agency: ...", also hhs, usda, dod, dhs, irs, ftc,
  fcc, fema, nasa and 20 more); they match whole words only ("fema" is not "female").
- `ask` leaves out words that only say how much something matters ("significant", "major",
  "important", "notable"): "significant epa rules in 2024" now lists EPA rules, not the one
  rule whose summary says "significant" and two of the Transportation Department. Of 310 real
  questions, only the two that use these words get other sources.

## 0.10.19 - 2026-09-28

- The archive's word indexes are also split by the first two letters of their words
  (`archive/words/ja.json`, `archive/words-by-feed/ja.json`), listed in the archive index as
  `shards`: a question reads a few small files, tens of kilobytes, instead of both whole
  indexes (22 MB on feeds.daemonfill.dev). `words.json` stays for older readers; the one-file
  `words-by-feed.json` of 0.10.18 is gone (0.10.18 then reads whole months, as before it).
- `unlimited offline` keeps the one-file word index in its copy.
- The index page reads the split word indexes too, and the archive files of a search at once
  rather than one after another.

## 0.10.18 - 2026-09-28

- The archive is also split by feed (`archive/2024-02/sec-ipo-filings.jsonl`), with a word
  index by feed (`archive/words-by-feed.json`): a question about a year reads only the feeds
  that can hold its words and those it names, 5 to 10 times less data than whole months
  ("earthquakes in japan in 2024": 1.8 MB instead of 17.8 MB, 6,398 items ranked instead of
  44,659). Month files stay, so older readers and mirrors keep working; a month whose split
  does not add up is read whole, and the next run splits it again.
- The index page's archive search reads the split too.

## 0.10.17 - 2026-09-28

- The archive's word index also has keys by feed for words that are not rare
  ("reddit@sec-ipo-filings"): a question word naming a feed narrows the others to that feed,
  so `ask` and the index page find "reddit ipo" (its S-1 of 2024), "hertz bankruptcy" and
  both Ronin hacks. The index is rebuilt whole on every run to keep those keys exact.

## 0.10.16 - 2026-09-28

- A catalog's index page, redesigned: its numbers up front (feeds, live feeds, records in the
  archive, last update), the search, and the feeds as cards grouped by topic, each with its
  readable name, a "Live" mark for the express lane, its latest item and RSS/JSON buttons;
  light and dark, no third-party requests.
- Pipelines can name their topic with `group:`; `publish --group NAME` orders the topics and
  `publish --link LABEL=URL` adds links to the page's header. feeds.json lists each feed's
  `title` and `group`.
- Express runs install Chromium only when a pipeline in the lane needs it.

## 0.10.15 - 2026-09-28

- Readable names: the SEC sources write companies listed in capitals as people write them
  ("Hertz Global Holdings, Inc", keeping "BNSF", "AT&T", "REIT"), and pipelines get
  `readable(name)` for the same.
- Every feed's items: titles lose HTML entities, tags and extra spaces; links lose tracking
  parameters (utm_*, fbclid, gclid).
- `ask` ranks 3.5 times faster over large archives (a substring check before each word's
  pattern), with exactly the same results.

## 0.10.14 - 2026-09-28

- `ask` looks in the archive for a question without a date whenever the latest items miss
  one of its words ("supreme court netchoice" finds Moody v. NetChoice of 2024), and ranks the
  word index's months by how many of the question's words each holds.
- A word the archive has is not taken for a typo because the latest items lack it ("reddit"
  was searched as "reddio").

## 0.10.13 - 2026-09-28

- `web --not-found-is-empty`: read HTTP 404 as no records, for APIs such as openFDA that answer
  a search with no results that way (the feed stays healthy in a quiet week).
- `backfill` reads a source that takes no dates once, not once per period.
- Search: "flaws" and "bug" find vulnerabilities.

## 0.10.12 - 2026-09-28

- `web --next-page next --pages 12` follows JSON APIs that answer a page at a time (the
  field that holds the next page's address), so a feed reads all of a period, not its first
  25 items.
- `${TOMORROW}` in a pipeline, for APIs whose end date is not included; in a backfill, the day
  after the period.

## 0.10.11 - 2026-09-28

- `unlimited sec company-events`: 8-K filings that report a bankruptcy, a completed
  acquisition, layoffs, an impairment, a delisting notice, an auditor change, a restatement,
  a change in control or a cybersecurity incident.
- `sec activist-stakes` and `sec company-events` take `--since` and `--until`: a period that
  ends before today is read from EDGAR's full-text search, so `unlimited backfill` can fill an
  archive with years of them, titled the same as the latest ones.

## 0.10.10 - 2026-09-28

- `unlimited sec ipo-filings --since DATE --until DATE`: new S-1 and F-1 registrations by
  companies that had filed no annual or quarterly report yet, for any period. Public
  companies registering more shares and life insurers' annuities are left out; past IPOs are
  kept even though EDGAR now shows their ticker.
- Searching by meaning compares a question with the newest 2,000 items at most (a year of
  the archive took minutes on a small computer), and keeps up to 8,000 vectors between runs.
- `mirror` also copies the archive's word index, for questions without a date offline.

## 0.10.9 - 2026-09-28

- `ask` answers "strongest", "biggest", "highest", "lowest" questions by the numbers in the
  items (M 7.5, $624M, 7.79%): the code picks the largest and writes the answer, in about a
  second, without a model.
- A question that names no date and finds nothing recent ("ronin hack") reads the archive
  months its rare words appear in, from a word index (`archive/words.json`) that the archive
  keeps up to date.
- Catalog files are read without the pause between requests meant for scraping, four at a
  time: a year of the archive loads in 0.2 s instead of 13 s.
- `validate --deep` warns about archive items dated before 1990 or in the future, listed twice,
  or in the wrong month.
- Answers no longer end a summary at "St." or "U.S." or repeat a date the title has.

## 0.10.8 - 2026-09-28

- `unlimited backfill FEED.yml --from 2016` fills a catalog's archive with a feed's past
  items: it runs the feed's own sources and operators once per month (or `--every` week,
  quarter, year or a number of days) with `${TODAY}` and `${DAYS_AGO_N}` set to that period,
  leaves out its `diff`, `limit` and outputs, and adds each item once.
- `search` and `ask` read the archive by themselves for a year or month the question names
  ("earthquakes in 2023", "sanctions march 2025", "last year").
- Pipelines: `${YEAR}` is the current year (a period's year in a backfill); expressions get
  `max()`, `min()` and `default(value, fallback)`, since text joined with a missing value is
  missing.

## 0.10.7 - 2026-09-27

- `unlimited setup` installs the decision model, unlimitedpipe/decide-0.5b: it picks the
  sources that answer (or none) and `ask` writes the answer from their own words. As accurate
  as the writing model on 155 hand-labelled questions, three times faster, and it cannot put a
  word in an answer that its sources do not have.

## 0.10.6 - 2026-09-27

- `unlimited check FEED.yml` tries a pipeline before it joins a catalog: it must load, run,
  write a JSON feed of items with a title and a web link, and find nothing new on a second
  run moments later. `--markdown` writes a report for a pull request.
- A workflow made by `publish --express` takes a `lane` input: an outside timer starts it with
  `express` (the express lane, the rest when due), because GitHub starts scheduled runs late
  or not at all when it is busy. Started by hand, it still runs everything.
- `ask` has a decision mode: when the decision model is installed it picks the sources that
  answer (or none), and the answer is written by code from those sources' own words, with how
  sure the model was.

## 0.10.5 - 2026-09-27

- `search` and `ask` forgive the way people ask: a typo is searched as the catalog word one
  letter away ("bitcion" as "bitcoin"), common words the sources put differently match ("fed"
  the Federal Reserve, "jobless" unemployment, "gdp" gross domestic product, "purchase"
  bought), and when no item has the words at all, a small local embedding model (all-minilm,
  46 MB, which `unlimited setup` now installs) finds the items that mean the same.
- `ask` prefers the model trained for it over general models: on questions typed the way
  people type it passes more answers than general models eight times its size.
- `publish --express NAME` puts time-sensitive pipelines in an express lane that runs every
  `--express-every` (default 15m); the rest run every `--every`.
- `web` reads CSV files, one record per row.
- `unlimited doctor` says when a newer ask model is out, and when the embedding model is
  missing.
- `diff` records a change only once what follows has taken it, so a run stopped in between
  reports it again next time instead of losing it (feed outputs keep it once).

## 0.10.4 - 2026-09-27

- `search` and `ask` show at most two updates of one story (a storm's advisories, a coin's
  price, a package's releases), so one busy story no longer pushes everything else out of the
  results; `search --every-update` shows them all.
- `sec insider-trades --all-new` reads every Form 4 filed since the last run (up to
  `--limit 1000`), remembering which it read: the latest 200 are only an hour or two on a busy
  day. SEC requests go at five a second, half the SEC's limit.
- `diff --remember` keeps items that disappear, so a source that leaves items out now and then
  does not report them as new when they come back.
- Pipeline files can use `${TODAY}` and `${DAYS_AGO_30}` (UTC dates) in values, for APIs that
  take a date range.
- `unlimited validate` warns about feeds that have never had an item, or none for two weeks.
- The index page of a published catalog says that GitHub starts scheduled runs when it has
  room, often later than scheduled.

## 0.10.3 - 2026-09-27

- The `ask` model `unlimited setup` installs is build 3: it lists every matching source when
  asked what is new, and on 70 questions typed the way people type passes 81% (build 2: 51%),
  level with Qwen3.5 4B. `ollama pull hf.co/unlimitedpipe/ask-0.5b-GGUF` updates it.
- Search and `ask`: words of three letters or fewer match whole words only, so "SEC" no longer
  finds "security", "AI" no longer "aid", "US" no longer "user" (longer words still match any
  ending: "hack" finds "hackers").
- `ask` leaves out casual filler ("update", "lately"; in Thai ใหม่, ขอ, ว่าไง, อัปเดต) instead of
  searching for it, and "show hn" searches for "hn".
- When "today" or "this week" finds nothing that recent, `ask` shows the latest matching items
  and their date instead of nothing ("baht rate today" on a Sunday gets Friday's rate).

## 0.10.2 - 2026-09-27

- `publish --title` and `--about` give a catalog's site a title and a sentence under it;
  `unlimited catalog` keeps the title between runs.
- The index page says how many feeds it has, that the workflow is scheduled (GitHub runs
  scheduled workflows when it can, sometimes hours late), and how to search and ask it from a
  terminal.
- README: what UnlimitedPipe is in one paragraph, pictures of `ask` and `search` recorded
  from real runs (docs/assets/make_demos.py), and two write-ups in docs/posts.

## 0.10.1 - 2026-09-27

- `bluesky` works out of the box: its WebSocket client is a dependency now (a few hundred
  KB). The one-line installer puts UnlimitedPipe in its own environment, where the old hint,
  `pip install "unlimitedpipe[live]"`, could not reach. `[live]` still installs.
- The browser hints point to `unlimited setup`, which installs Playwright and Chromium however
  UnlimitedPipe was installed.

## 0.10.0 - 2026-09-27

"Open": the format as a protocol, a model trained for `ask`, and public data.

- The Feed Catalog Protocol, version 1 (docs/protocol.md): what `publish` writes (feeds.json,
  feed files, the monthly archive, events) specified as an open format any tool can write and
  read, with JSON Schemas in docs/schemas; discovery, peers and signed archives are proposed.
- `unlimited validate CATALOG`: checks a site, a feeds.json URL or a folder against the
  protocol; `--deep` reads every feed file and archive month, `--json` prints the findings.
- `unlimited setup` installs `unlimitedpipe/ask-0.5b` (531 MB), a 0.5B model trained to
  answer from numbered sources with citations and to say when they do not cover the question,
  in English and Thai. Trained on public data only, it passes 87% of test questions on news it
  never saw, against 5% for Qwen2.5 0.5B, its base; `ask` prefers it over general models of
  its size.
- Releases publish to PyPI from GitHub Actions (trusted publishing, no stored token) with a
  GitHub release for each tag.
- research/: the ask model's data, training on Kaggle and grading; fruit-fly circuits on the
  catalog (a negative result, and a modular one that does not forget); collectors for the
  public dataset unlimitedpipe/public-records (Federal Register, SEC 10-K).

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
