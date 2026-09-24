# Responsible use

UnlimitedPipe is built for public data and data you are authorized to access. It is designed
so that the default behavior is the polite one.

## The front-door rule

If data is not reachable through a door its owner left open, UnlimitedPipe does not fetch it.

1. **Official API or feed first.** Connectors use documented APIs, RSS/Atom/JSON feeds and
   public product JSON that sites publish on purpose.
2. **Your own key for paid or authenticated APIs.** The connector uses your credentials under
   the platform's terms; UnlimitedPipe never ships shared keys.
3. **Polite HTML for public pages.** Only what any visitor without an account can see.

When a site says how it wants to be read, follow that. GitHub's robots.txt, for example, asks
automated clients not to fetch its `.atom` feeds and points to its API, so UnlimitedPipe reads
GitHub through the official API (`unlimited github`).

**Feeds.** `unlimited rss` works like a feed reader: it fetches only the feed URLs you give it,
at the schedule you choose, with conditional requests. Like feed readers and Google's
Feedfetcher, it does not consult robots.txt, which governs crawlers. `web`, `inspect` and
`new` do honor robots.txt. If a site asks readers not to use a feed, don't.

UnlimitedPipe does not and will not include login bypass, CAPTCHA solving, browser
fingerprint spoofing, rotating proxy pools, or other features meant to get around access
controls. Connectors that do are not accepted.

## What the defaults do

- **robots.txt** is honored for web pages as described in RFC 9309, including `Crawl-delay`.
  `--ignore-robots` exists for sites you own or have permission to fetch.
- **One request per second per host**, shared by every source in a run.
- **Conditional requests** (`ETag`, `If-Modified-Since`) so an unchanged page costs the site
  almost nothing.
- **Retries** back off and honor `Retry-After`. HTTP 429 is retried after the delay the site
  asks for, then reported; 403 is reported and never worked around.
- **An honest User-Agent**: `UnlimitedPipe/<version> (+https://github.com/Fuyuki0/unlimitedpipe)`.
- **A size cap** of 20 MB per response.

## Your responsibilities

- Follow each site's terms of service and the law where you and the site operate. Terms
  often differ for personal and commercial use.
- Check pages at a sensible frequency. Hourly or daily is enough for prices and news.
- Do not collect or publish data about private individuals. Laws such as the GDPR (EU),
  PDPA (Thailand) and CCPA (California) apply to personal data even when it is public.
- Facts such as prices and availability are generally not copyrightable; descriptions,
  articles and images usually are. When you publish a feed, prefer titles, short summaries and
  links over copies of full content.
- Real-time market data often comes with redistribution restrictions. Fetching it with your
  own key for yourself is different from republishing it.

This page is general information, not legal advice.

## Reporting misuse

If you run a website and believe UnlimitedPipe is being used against your terms, block the
`UnlimitedPipe` user agent in robots.txt (every default configuration honors it) and open an
issue. Reports about published feeds that contain personal data or infringe rights are handled
as described in [SECURITY.md](../SECURITY.md).
