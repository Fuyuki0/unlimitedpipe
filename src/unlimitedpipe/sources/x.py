"""The ``x`` source: posts on X (Twitter) through its official API, with your own key."""

from __future__ import annotations

import os
from typing import Any, Literal

from unlimitedpipe.component import Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError, UsageError
from unlimitedpipe.event import Event
from unlimitedpipe.sources._posts import api_error, headline

API = "https://api.x.com/2"
KEY_HINT = (
    "reading X needs an API plan that includes reads (developer.x.com); "
    "set X_BEARER_TOKEN to your app's bearer token"
)
FIELDS = {
    "tweet.fields": "created_at,public_metrics,lang,entities,author_id",
    "expansions": "author_id",
    "user.fields": "username,name",
}


class X(Source):
    """Posts on X (Twitter) through the official API: a recent search, or an account's posts.

    X only allows reading through its API, and reading needs a paid plan: set
    `X_BEARER_TOKEN` (or `--token`) to your app's bearer token. Nothing here works without one,
    and nothing tries to get around that.
    """

    name = "x"
    examples = (
        'unlimited x search "bitcoin ETF" --limit 20',
        "unlimited x posts nasa spacex",
    )

    resource: Literal["search", "posts"] = arg("What to read")
    target: list[str] = arg(
        "Search words, or account names for posts", metavar="TARGET...", default_factory=list
    )
    token: str | None = opt("Bearer token (default: $X_BEARER_TOKEN)", default=None, secret=True)
    limit: int = opt("Posts per search or account, 10 to 100", default=10)
    timeout: float = opt("Seconds to wait for each response", default=20.0)

    def __post_init__(self) -> None:
        if not self.target:
            raise ValueError("x needs search words or account names")
        if not 10 <= self.limit <= 100:
            raise ValueError("--limit must be between 10 and 100 (X's API range)")

    async def collect(self, ctx: Context):
        token = self.token or os.environ.get("X_BEARER_TOKEN")
        if not token:
            raise UsageError("x needs an X API bearer token", hint=KEY_HINT)
        headers = {"Authorization": f"Bearer {token}"}
        targets = [" ".join(self.target)] if self.resource == "search" else self.target
        for target in targets:
            try:
                url, payload = await self._posts(ctx, headers, target)
            except FetchError as exc:
                if (error := ctx.fail(exc, source=self.name, url=API)) is not None:
                    yield error
                continue
            users = {u.get("id"): u for u in (payload.get("includes") or {}).get("users", []) if u}
            for post in payload.get("data") or []:
                if isinstance(post, dict):
                    yield self._event(url, post, users.get(post.get("author_id")) or {})

    async def _get(self, ctx: Context, url: str, headers: dict[str, str], params: Any) -> Any:
        response = await ctx.http.get(
            url,
            params=params,
            headers=headers,
            timeout=self.timeout,
            raise_for_status=False,
            cache=False,
        )
        if response.status in (401, 403):
            raise api_error(response, "X API", url, hint=KEY_HINT)
        if response.status >= 400:
            raise api_error(response, "X API", url)
        return response.json()

    async def _posts(self, ctx: Context, headers: dict[str, str], target: str):
        params = {**FIELDS, "max_results": str(self.limit)}
        if self.resource == "search":
            url = f"{API}/tweets/search/recent"
            return url, await self._get(ctx, url, headers, {**params, "query": target})
        name = target.lstrip("@")
        user = await self._get(ctx, f"{API}/users/by/username/{name}", headers, None)
        if not (user.get("data") or {}).get("id"):
            raise FetchError(f"X account {name!r} not found", url=f"{API}/users/by/username")
        url = f"{API}/users/{user['data']['id']}/tweets"
        return url, await self._get(ctx, url, headers, params)

    def _event(self, url: str, post: dict[str, Any], user: dict[str, Any]) -> Event:
        name = user.get("username")
        link = f"https://x.com/{name or 'i'}/status/{post.get('id')}"
        metrics = post.get("public_metrics") or {}
        hashtags = (post.get("entities") or {}).get("hashtags") or []
        text = post.get("text") or ""
        return Event(
            source=self.name,
            type="post",
            key=link,
            source_url=url,
            timestamp=post.get("created_at"),
            data={
                "title": headline(text),
                "text": text,
                "author": f"@{name}" if name else None,
                "author_name": user.get("name"),
                "url": link,
                "created_at": post.get("created_at"),
                "language": post.get("lang"),
                "tags": [f"#{h.get('tag')}" for h in hashtags if h.get("tag")],
                "likes": metrics.get("like_count"),
                "reposts": metrics.get("retweet_count"),
                "replies": metrics.get("reply_count"),
            },
            metadata={"method": "x-api"},
        )
