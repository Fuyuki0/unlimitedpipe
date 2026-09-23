"""How to test a connector: fake the HTTP API, run the source, check the events."""

import asyncio
import json

import httpx
from unlimitedpipe_hackernews import HackerNews

from unlimitedpipe import Context

HITS = {
    "hits": [
        {
            "objectID": "1",
            "title": "Local LLMs are fast now",
            "url": "https://blog.example/llm",
            "author": "ana",
            "points": 120,
            "num_comments": 40,
            "created_at": "2026-09-23T10:00:00Z",
        },
        {
            "objectID": "2",
            "title": "Ask HN: local models?",
            "url": None,
            "author": "bo",
            "points": 5,
            "num_comments": 2,
            "created_at": "2026-09-23T09:00:00Z",
        },
    ]
}


def test_stories_become_events(tmp_path):
    requests = []

    def api(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=HITS)

    ctx = Context(
        transport=httpx.MockTransport(api), cache_dir=tmp_path, host_interval=0, quiet=True
    )

    async def run():
        try:
            return [event async for event in HackerNews(query="local llm", limit=2).collect(ctx)]
        finally:
            await ctx.aclose()

    first, second = asyncio.run(run())
    assert requests[0].url.params["query"] == "local llm"
    assert first.type == "story"
    assert first.key == "https://news.ycombinator.com/item?id=1"
    assert first.data["url"] == "https://blog.example/llm"
    assert first.data["points"] == 120
    assert second.data["url"] == "https://news.ycombinator.com/item?id=2"
    assert json.loads(first.to_json())["timestamp"] == "2026-09-23T10:00:00Z"
