"""The ``bluesky`` source: new public posts, live, from Bluesky's Jetstream firehose."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from typing import Any

from unlimitedpipe._version import USER_AGENT
from unlimitedpipe.component import Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import UsageError
from unlimitedpipe.event import Event

JETSTREAM = "wss://jetstream2.us-east.bsky.network/subscribe"
# Salt for author keys: new on every run, so keys cannot be linked across runs or to accounts.
_RUN_SALT = os.urandom(16)
POST = "app.bsky.feed.post"
TAG = "app.bsky.richtext.facet#tag"
LINK = "app.bsky.richtext.facet#link"


def _connect(url: str):
    """Open the WebSocket (patched in tests)."""
    import websockets

    return websockets.connect(
        url, user_agent_header=USER_AGENT, open_timeout=20, max_size=2**20, ping_interval=30
    )


class Bluesky(Source):
    """Stream new public Bluesky posts as they are published, from Bluesky's Jetstream.

    Never ends: pair it with `limit`, `count --every` or `watch`-style outputs. Filter with
    words and languages; hashtags and links come from each post's facets. Each post has an
    opaque `author_key` (new on every run) so trends can count people, not posts:
    `count --by tags --distinct author_key`. There is deliberately no filter by author.
    Reconnects on its own and resumes where it stopped. Needs the optional WebSocket client:
    pip install "unlimitedpipe[live]".
    """

    name = "bluesky"
    finite = False
    examples = (
        "unlimited bluesky claude openai --lang en | unlimited limit 20",
        "unlimited run bluesky --lang en -- count --by tags --distinct author_key --every 10m "
        "-- trend",
    )

    search: list[str] = arg(
        "Only posts containing any of these words (default: all)", default_factory=list
    )
    lang: list[str] = opt(
        "Only posts in this language, e.g. en (repeatable)", short="-l", default_factory=list
    )
    replies: bool = opt("Include replies", default=False)
    endpoint: str = opt("Jetstream WebSocket URL", default=JETSTREAM)

    def __post_init__(self) -> None:
        if not self.endpoint.startswith(("wss://", "ws://")):
            raise ValueError("--endpoint must be a ws:// or wss:// URL")
        words = [re.escape(word) for word in self.search if word.strip()]
        self._search = re.compile(rf"(?<!\w)(?:{'|'.join(words)})(?!\w)", re.I) if words else None
        self._langs = {lang.lower() for lang in self.lang}

    def post_event(self, message: dict[str, Any]) -> Event | None:
        """One Jetstream message -> a `post` event, or None when it is filtered out."""
        commit = message.get("commit")
        if message.get("kind") != "commit" or not isinstance(commit, dict):
            return None
        if commit.get("operation") != "create" or commit.get("collection") != POST:
            return None
        record = commit.get("record") or {}
        text = record.get("text") or ""
        if record.get("reply") and not self.replies:
            return None
        langs = [lang.lower() for lang in record.get("langs") or []]
        if self._langs and not self._langs.intersection(lang.split("-")[0] for lang in langs):
            return None
        if self._search and not self._search.search(text):
            return None
        tags: dict[str, None] = {}
        links: dict[str, None] = {}
        for facet in record.get("facets") or []:
            for feature in facet.get("features") or []:
                if feature.get("$type") == TAG and feature.get("tag"):
                    tags["#" + str(feature["tag"]).lower()] = None
                elif feature.get("$type") == LINK and feature.get("uri"):
                    links[str(feature["uri"])] = None
        did, rkey = message.get("did", ""), commit.get("rkey", "")
        seen = message.get("time_us")
        return Event(
            source=self.name,
            type="post",
            source_url=self.endpoint,
            key=f"at://{did}/{POST}/{rkey}",
            timestamp=datetime.fromtimestamp(seen / 1e6, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            if isinstance(seen, int)
            else None,
            data={
                "text": text,
                "langs": langs,
                "tags": list(tags),
                "links": list(links),
                "url": f"https://bsky.app/profile/{did}/post/{rkey}",
                "created_at": record.get("createdAt"),
                "reply": bool(record.get("reply")),
                # Lets `count --distinct author_key` count people rather than posts, so one
                # account posting 100 times counts once. Opaque and different on every run.
                "author_key": hashlib.sha256(_RUN_SALT + did.encode()).hexdigest()[:16],
            },
            metadata={"method": "jetstream"},
        )

    async def collect(self, ctx: Context):
        try:
            import websockets
        except ImportError:
            raise UsageError(
                "bluesky needs the optional WebSocket client",
                hint='pip install "unlimitedpipe[live]"',
            ) from None
        cursor: int | None = None
        delay = 1.0
        while True:
            url = f"{self.endpoint}?wantedCollections={POST}"
            if cursor is not None:
                url += f"&cursor={cursor}"  # resume where the last connection stopped
            try:
                async with _connect(url) as socket:
                    delay = 1.0
                    async for raw in socket:
                        message = json.loads(raw)
                        cursor = message.get("time_us", cursor)
                        event = self.post_event(message)
                        if event is not None:
                            yield event
                await asyncio.sleep(delay)  # the server closed the stream: reconnect shortly
            except (OSError, TimeoutError, ValueError, websockets.WebSocketException) as exc:
                reason = str(exc) or type(exc).__name__
                ctx.warn(f"bluesky: connection lost ({reason}); retrying in {delay:.0f}s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60.0)
