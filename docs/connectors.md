# Writing a connector

A connector is a **source**: a Python class that emits events. Adding one is the easiest way
to contribute to UnlimitedPipe, and it takes five steps: create it, register it, test it,
document it, and submit it.

The complete result of this guide is in
[examples/plugin-hackernews](../examples/plugin-hackernews). Copy that folder to start.

## 1. Create the source

```python
# src/unlimitedpipe_hackernews/__init__.py
from typing import Literal

from unlimitedpipe import Context, Event, Source, arg, opt

API = "https://hn.algolia.com/api/v1/search_by_date"


class HackerNews(Source):
    """Search Hacker News stories through the public Algolia API (no key needed).

    Emits one `story` event per result, newest first.
    """

    name = "hackernews"          # the command: `unlimited hackernews`
    version = "0.1.0"            # recorded in each event's provenance
    examples = ('unlimited hackernews "local llm"',)

    query: str = arg("Search words")
    limit: int = opt("Maximum stories (up to 1000)", default=30)
    min_points: int = opt("Only stories with at least this many points", default=0)
    kind: Literal["story", "show_hn", "ask_hn"] = opt("Kind of post", default="story")

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 1000:
            raise ValueError("--limit must be between 1 and 1000")

    async def collect(self, ctx: Context):
        response = await ctx.http.get(API, params={"query": self.query, "tags": self.kind,
                                                   "hitsPerPage": self.limit})
        for hit in response.json()["hits"]:
            discussion = f"https://news.ycombinator.com/item?id={hit['objectID']}"
            yield Event(
                source=self.name,
                type="story",
                source_url=API,
                key=discussion,
                timestamp=hit.get("created_at"),
                data={"title": hit["title"], "url": hit.get("url") or discussion,
                      "points": hit.get("points")},
            )
```

What you get from those few lines:

- **Options.** Each annotated field is an option. `arg(...)` makes a positional CLI argument,
  `opt(...)` a `--flag`. The same fields are the YAML keys and the Python keyword arguments
  (`HackerNews(query="rust")`). Supported types: `str`, `int`, `float`, `bool`,
  `Literal[...]`, `X | None` and `list[...]` of those. `list` options default to `[]` and
  `bool` options to `False`. Mark tokens with `opt(..., secret=True)` so they never appear in
  provenance.
- **Help.** The docstring's first paragraph is the one-line summary in `unlimited --help`;
  the rest, the option help texts and `examples` make up `unlimited hackernews --help`.
- **Validation.** Raise `ValueError` in `__post_init__`. The CLI shows it as a usage error and
  YAML shows it with the file and line.
- **HTTP.** `ctx.http.get` shares one client per run: per-host rate limiting (1 request per
  second by default), retries honoring `Retry-After`, conditional requests, a size cap and
  readable errors. Pass `robots=True` when you fetch pages rather than an API.

`name`, `version`, `examples` and `finite` are reserved class attributes; defining an option
with one of those names raises an error when the class is defined.

### Choosing what to emit

- `type`: what the event is (`story`, `product`, `release`, `entry`). Operators and outputs
  use it for rendering.
- `key`: the stable identity of the thing observed (a URL, an id). `diff` and `dedupe` rely on
  it, so pick something that does not change when the content changes.
- `source_url`: the URL you fetched. `diff` uses it to decide which items can count as
  removed, so keep it the same for every event from one request.
- `timestamp`: when the thing happened (published, released), if known.
- `data`: plain JSON values. Prefer flat, descriptive keys (`title`, `url`, `price`,
  `currency`) so `select`, `filter` and `feed` work without configuration.

### Handling failures

For several URLs or pages, report a failure and continue instead of stopping the whole
pipeline:

```python
from unlimitedpipe.errors import FetchError

async def collect(self, ctx):
    for page in range(1, 4):
        try:
            response = await ctx.http.get(API, params={"page": page})
        except FetchError as exc:
            if (error := ctx.fail(exc, source=self.name, url=API)) is not None:
                yield error          # with --errors-as-events
            continue
        ...
```

Raise `unlimitedpipe.errors.UnlimitedError(message, hint=...)` for anything the user must fix;
it is printed without a traceback.

## 2. Register it

One entry point in `pyproject.toml`:

```toml
[project]
name = "unlimitedpipe-hackernews"
dependencies = ["unlimitedpipe>=0.1"]

[project.entry-points."unlimitedpipe.plugins"]
hackernews = "unlimitedpipe_hackernews:HackerNews"
```

```bash
pip install -e .
unlimited --help            # hackernews is listed under Sources
unlimited hackernews "local llm" --min-points 50
```

The same group registers operators (`Operator` subclasses) and outputs (`Output` subclasses).
Built-in names win over plugins with the same name.

## 3. Test it

Fake the HTTP API with `httpx.MockTransport`, run the source, check the events. No network,
no flakiness:

```python
import asyncio

import httpx

from unlimitedpipe import Context
from unlimitedpipe_hackernews import HackerNews


def test_stories_become_events(tmp_path):
    def api(request):
        return httpx.Response(200, json={"hits": [{"objectID": "1", "title": "Hi", "url": None}]})

    ctx = Context(transport=httpx.MockTransport(api), cache_dir=tmp_path, host_interval=0)

    async def run():
        try:
            return [e async for e in HackerNews(query="x").collect(ctx)]
        finally:
            await ctx.aclose()

    [story] = asyncio.run(run())
    assert story.key == "https://news.ycombinator.com/item?id=1"
```

Test the cases users will hit: an empty result, a missing field, an HTTP error.

## 4. Document it

In your package README, show:

1. One command that works immediately (`unlimited hackernews "local llm"`).
2. Each option, with its default.
3. The event: `type`, `key` and the `data` fields.
4. A YAML example.
5. Limits: rate limits, API terms, whether a key is needed and where the user gets one.

## 5. Submit it

- **As its own package** (recommended for most connectors): publish
  `unlimitedpipe-<name>` to PyPI and open an issue or PR adding it to the connector list, so
  others can find it.
- **Into the core**: only for sources most users need (like `web` and `rss`) with no extra
  dependencies. Open an issue first to discuss.

Before submitting, check the connector:

- [ ] uses an official API, feed or public page ("front door"), never a login or block bypass;
- [ ] does not collect data about private individuals;
- [ ] respects the platform's terms, and says so in its README;
- [ ] handles errors with readable messages;
- [ ] has tests that run without network.
