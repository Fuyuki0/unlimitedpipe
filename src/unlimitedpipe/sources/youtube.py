"""The ``youtube`` source: videos through the official YouTube Data API (free key)."""

from __future__ import annotations

import os
from typing import Any, Literal

from unlimitedpipe.component import Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError, UsageError
from unlimitedpipe.event import Event
from unlimitedpipe.sources._posts import api_error

API = "https://www.googleapis.com/youtube/v3"
KEY_HINT = (
    "create a free key: console.cloud.google.com, enable YouTube Data API v3, "
    "then set YOUTUBE_API_KEY"
)


class YouTube(Source):
    """YouTube videos through the official Data API: a channel's newest uploads, or a search.

    Needs a free API key (`--key` or `$YOUTUBE_API_KEY`). A channel's uploads cost 2 units of
    the daily 10,000; a search costs 100.
    """

    name = "youtube"
    examples = (
        "unlimited youtube videos @NASA",
        "unlimited youtube videos UCLA_DiR1FfKNvjuUpBHmylQ --limit 5",
        'unlimited youtube search "bangkok flood"',
    )

    resource: Literal["videos", "search"] = arg("What to read")
    target: list[str] = arg(
        "Channels (@handle or channel ID) for videos; words for search",
        metavar="TARGET...",
        default_factory=list,
    )
    key: str | None = opt("API key (default: $YOUTUBE_API_KEY)", default=None, secret=True)
    limit: int = opt("Videos per channel or search, up to 50", default=10)
    timeout: float = opt("Seconds to wait for each response", default=20.0)

    def __post_init__(self) -> None:
        if not self.target:
            raise ValueError("youtube needs channels (@handle or ID) or search words")
        if not 1 <= self.limit <= 50:
            raise ValueError("--limit must be between 1 and 50")

    async def collect(self, ctx: Context):
        key = self.key or os.environ.get("YOUTUBE_API_KEY")
        if not key:
            raise UsageError("youtube needs a YouTube Data API key", hint=KEY_HINT)
        targets = [" ".join(self.target)] if self.resource == "search" else self.target
        for target in targets:
            try:
                url, items = await self._items(ctx, key, target)
            except FetchError as exc:
                if (error := ctx.fail(exc, source=self.name, url=API)) is not None:
                    yield error
                continue
            for item in items:
                if (event := self._event(url, item)) is not None:
                    yield event

    async def _get(self, ctx: Context, path: str, params: dict[str, Any]) -> Any:
        url = f"{API}/{path}"
        response = await ctx.http.get(
            url, params=params, timeout=self.timeout, raise_for_status=False, cache=False
        )
        if response.status >= 400:
            quota = "quotaExceeded" in response.text
            hint = "the daily quota resets at midnight Pacific time" if quota else KEY_HINT
            raise api_error(response, "YouTube Data API", url, hint=hint)
        return response.json()

    async def _items(self, ctx: Context, key: str, target: str) -> tuple[str, list[Any]]:
        if self.resource == "search":
            params = {
                "part": "snippet",
                "type": "video",
                "order": "date",
                "q": target,
                "maxResults": self.limit,
                "key": key,
            }
            return f"{API}/search", (await self._get(ctx, "search", params)).get("items", [])
        which = {"forHandle": target} if target.startswith("@") else {"id": target}
        found = await self._get(ctx, "channels", {"part": "contentDetails", "key": key, **which})
        if not found.get("items"):
            raise FetchError(f"YouTube channel {target!r} not found", url=f"{API}/channels")
        uploads = found["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        params = {"part": "snippet", "playlistId": uploads, "maxResults": self.limit, "key": key}
        return f"{API}/playlistItems", (await self._get(ctx, "playlistItems", params)).get(
            "items", []
        )

    def _event(self, url: str, item: dict[str, Any]) -> Event | None:
        snippet = item.get("snippet") or {}
        video = (item.get("id") or {}).get("videoId") if isinstance(item.get("id"), dict) else None
        video = video or (snippet.get("resourceId") or {}).get("videoId")
        if not video:
            return None
        link = f"https://www.youtube.com/watch?v={video}"
        return Event(
            source=self.name,
            type="video",
            key=link,
            source_url=url,
            timestamp=snippet.get("publishedAt"),
            data={
                "title": snippet.get("title"),
                "summary": (snippet.get("description") or "")[:500] or None,
                "channel": snippet.get("channelTitle"),
                "url": link,
                "published_at": snippet.get("publishedAt"),
                "video_id": video,
            },
            metadata={"method": "youtube-data-api"},
        )
