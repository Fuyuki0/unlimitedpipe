# Platforms

UnlimitedPipe reads every platform through the door the platform offers. Where a platform
requires an account or charges for access, you bring your own key; nothing here tries to get
around that. `unlimited doctor` shows which keys are set.

| Platform | Command | Needs | Notes |
| --- | --- | --- | --- |
| Any web page | `web URL` | - | robots.txt respected; `--browser` for pages that need JavaScript |
| RSS, Atom, JSON Feed | `rss URL` | - | a page that links its feed works too |
| JSON APIs | `web URL --records PATH` | - | public APIs; keys in `${VAR}` in pipelines |
| GitHub | `github releases\|repo\|tags\|commits\|issues` | optional `GITHUB_TOKEN` | official REST API |
| SEC EDGAR | `sec insider-trades` | `SEC_CONTACT` (an email) | the SEC asks automated readers to identify themselves |
| Bluesky | `bluesky [WORDS]` | - | live, through Jetstream |
| Mastodon | `mastodon tag:NAME \| @user \| trending` | - | open API of any Mastodon server |
| Telegram | `telegram CHANNEL` | - | public channels' web preview only |
| YouTube | `youtube videos @handle \| search WORDS` | `YOUTUBE_API_KEY` (free) | official Data API, 10,000 units a day |
| Reddit | `reddit r/NAME` | your free Reddit app | official API; Reddit's robots.txt disallows crawling, and its terms allow API use for non-commercial purposes |
| X (Twitter) | `x search WORDS \| posts @user` | `X_BEARER_TOKEN` | official API; reading needs a paid plan |
| Instagram, Facebook, TikTok | - | - | their APIs are limited to business and research partners; not supported |

Content from Reddit and X is for your own watches and alerts. Their terms do not allow
republishing it, so public catalogs made with `unlimited publish` leave them out.

## Other tools

Every command reads JSON from other programs, so tools that fetch data their own way can feed
UnlimitedPipe's change detection, alerts and feeds:

```bash
yt-dlp --dump-json --flat-playlist "https://www.youtube.com/@NASA/videos" \
  | unlimited diff --key id --only added | unlimited webhook "$DISCORD_WEBHOOK"
some-cli --json | unlimited select title url | unlimited diff --only added | unlimited feed new.xml
```

What such a tool does, and whether it follows each platform's rules, is up to that tool and
the person who runs it.
