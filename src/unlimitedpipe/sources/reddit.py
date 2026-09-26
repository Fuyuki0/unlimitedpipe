"""The ``reddit`` source: subreddit posts through Reddit's official API (your own free app)."""

from __future__ import annotations

import os
from typing import Any, Literal

from unlimitedpipe._version import __version__
from unlimitedpipe.component import Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError, UsageError
from unlimitedpipe.event import Event
from unlimitedpipe.expr import _date
from unlimitedpipe.sources._posts import api_error, headline

TOKEN = "https://www.reddit.com/api/v1/access_token"
API = "https://oauth.reddit.com"
APP_HINT = (
    "create a free 'script' app at https://www.reddit.com/prefs/apps, then set "
    "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET (non-commercial use)"
)


class Reddit(Source):
    """Posts from subreddits through Reddit's official API, with your own free app.

    Reddit does not allow reading it without the API (its robots.txt disallows all crawling),
    so this source signs in as your app: set `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET`
    (and `REDDIT_USERNAME`, which Reddit asks to see in the User-Agent). Reddit's terms
    allow this for non-commercial use; content is for your own watches, not republishing.
    """

    name = "reddit"
    examples = (
        "unlimited reddit r/Thailand",
        "unlimited reddit r/python r/rust --sort top --period day",
        'unlimited reddit r/Thailand --search "flood"',
    )

    subreddit: list[str] = arg(
        "Subreddits, as r/NAME or NAME", metavar="SUBREDDIT...", default_factory=list
    )
    sort: Literal["new", "hot", "top", "rising"] = opt("Which listing", default="new")
    period: Literal["hour", "day", "week", "month", "year", "all"] = opt(
        "For --sort top and --search: the time window", default="day"
    )
    search: str | None = opt("Search the subreddits for these words instead", default=None)
    limit: int = opt("Posts per subreddit, up to 100", default=25)
    timeout: float = opt("Seconds to wait for each response", default=20.0)

    def __post_init__(self) -> None:
        if not self.subreddit:
            raise ValueError("reddit needs at least one subreddit, e.g. r/Thailand")
        if not 1 <= self.limit <= 100:
            raise ValueError("--limit must be between 1 and 100")
        self._subs = [
            s.strip().removeprefix("/").removeprefix("r/").strip("/") for s in self.subreddit
        ]

    async def collect(self, ctx: Context):
        client_id = os.environ.get("REDDIT_CLIENT_ID")
        secret = os.environ.get("REDDIT_CLIENT_SECRET")
        if not client_id or not secret:
            raise UsageError("reddit needs your own free Reddit app", hint=APP_HINT)
        user = os.environ.get("REDDIT_USERNAME", "unknown")
        agent = f"python:unlimitedpipe:{__version__} (by /u/{user})"
        try:
            token = await self._token(ctx, client_id, secret, agent)
        except FetchError as exc:
            if (error := ctx.fail(exc, source=self.name, url=TOKEN)) is not None:
                yield error
            return
        headers = {"Authorization": f"bearer {token}"}
        for sub in self._subs:
            if self.search:
                url = f"{API}/r/{sub}/search"
                params = {"q": self.search, "restrict_sr": "1", "sort": "new", "t": self.period}
            else:
                url = f"{API}/r/{sub}/{self.sort}"
                params = {"t": self.period} if self.sort == "top" else {}
            params.update({"limit": str(self.limit), "raw_json": "1"})
            try:
                response = await ctx.http.get(
                    url,
                    params=params,
                    headers=headers,
                    user_agent=agent,
                    timeout=self.timeout,
                    raise_for_status=False,
                    cache=False,
                )
                if response.status >= 400:
                    raise api_error(response, "Reddit API", url)
                listing = response.json()
            except FetchError as exc:
                if (error := ctx.fail(exc, source=self.name, url=url)) is not None:
                    yield error
                continue
            for child in (listing.get("data") or {}).get("children", []):
                if isinstance(child, dict) and isinstance(child.get("data"), dict):
                    yield self._event(url, child["data"])

    async def _token(self, ctx: Context, client_id: str, secret: str, agent: str) -> str:
        response = await ctx.http.post(
            TOKEN,
            data={"grant_type": "client_credentials"},
            auth=(client_id, secret),
            headers={"User-Agent": agent},
            timeout=self.timeout,
            secret_url=False,
        )
        token = response.json().get("access_token")
        if not token:
            raise FetchError("Reddit did not return an access token", url=TOKEN, hint=APP_HINT)
        return token

    def _event(self, url: str, post: dict[str, Any]) -> Event:
        link = f"https://www.reddit.com{post.get('permalink', '')}"
        external = post.get("url") if not post.get("is_self") else None
        created = _date(post.get("created_utc"))
        title = post.get("title") or ""
        return Event(
            source=self.name,
            type="post",
            key=link,
            source_url=url,
            timestamp=created,
            data={
                "title": title,
                "text": "\n".join(x for x in (title, (post.get("selftext") or "")[:2000]) if x),
                "author": f"u/{post.get('author')}" if post.get("author") else None,
                "subreddit": post.get("subreddit_name_prefixed"),
                "url": link,
                "links": [external] if external else [],
                "created_at": created,
                "score": post.get("score"),
                "comments": post.get("num_comments"),
                "flair": post.get("link_flair_text"),
                "tags": [],
                "summary": headline(post.get("selftext") or "", 300) or None,
            },
            metadata={"method": "reddit-api"},
        )
