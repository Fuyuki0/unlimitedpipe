"""A complete UnlimitedPipe source in one small file: search Hacker News stories."""

from __future__ import annotations

from typing import Literal

from unlimitedpipe import Context, Event, Source, arg, opt

API = "https://hn.algolia.com/api/v1/search_by_date"


class HackerNews(Source):
    """Search Hacker News stories through the public Algolia API (no key needed).

    Emits one `story` event per result, newest first. Pipe it into `diff --only added` to get
    only new stories on each run.
    """

    name = "hackernews"
    version = "0.1.0"
    examples = (
        'unlimited hackernews "local llm"',
        "unlimited hackernews rust --min-points 100 | unlimited select title url points",
    )

    query: str = arg("Search words")
    limit: int = opt("Maximum stories (up to 1000)", default=30)
    min_points: int = opt("Only stories with at least this many points", default=0)
    kind: Literal["story", "show_hn", "ask_hn"] = opt("Kind of post", default="story")

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= 1000:
            raise ValueError("--limit must be between 1 and 1000")

    async def collect(self, ctx: Context):
        params = {
            "query": self.query,
            "tags": self.kind,
            "hitsPerPage": self.limit,
            "numericFilters": f"points>={self.min_points}",
        }
        response = await ctx.http.get(API, params=params)
        for hit in response.json().get("hits", []):
            discussion = f"https://news.ycombinator.com/item?id={hit['objectID']}"
            yield Event(
                source=self.name,
                type="story",
                source_url=API,
                key=discussion,
                timestamp=hit.get("created_at"),
                data={
                    "title": hit.get("title"),
                    "url": hit.get("url") or discussion,
                    "discussion": discussion,
                    "author": hit.get("author"),
                    "points": hit.get("points"),
                    "comments": hit.get("num_comments"),
                },
            )
