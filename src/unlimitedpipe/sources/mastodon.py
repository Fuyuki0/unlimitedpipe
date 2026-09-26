"""The ``mastodon`` source: public posts from Mastodon servers through their open API."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from unlimitedpipe.component import Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError
from unlimitedpipe.event import Event
from unlimitedpipe.sources._posts import api_error, headline
from unlimitedpipe.sources.rss import strip_html


class Mastodon(Source):
    """Public posts from Mastodon (and other fediverse servers with the same API): a hashtag,
    an account, or what is trending. No account or key needed.

    Targets: `#tag` (or `tag:NAME`, handy in shells), `@user` or `@user@server`, `trending`.
    """

    name = "mastodon"
    examples = (
        "unlimited mastodon tag:thailand",
        "unlimited mastodon @Gargron trending --limit 10",
        "unlimited mastodon tag:python | unlimited diff --only added",
    )

    target: list[str] = arg(
        "#tag, tag:NAME, @user[@server] or trending", metavar="TARGET...", default_factory=list
    )
    server: str = opt("Mastodon server to read from", default="mastodon.social")
    limit: int = opt("Posts per target, up to 40", default=20)
    timeout: float = opt("Seconds to wait for each response", default=20.0)

    def __post_init__(self) -> None:
        if not self.target:
            raise ValueError("mastodon needs a target: tag:NAME, @user or trending")
        if not 1 <= self.limit <= 40:
            raise ValueError("--limit must be between 1 and 40")
        self._base = "https://" + self.server.removeprefix("https://").strip("/")

    async def collect(self, ctx: Context):
        for target in self.target:
            try:
                url, statuses = await self._statuses(ctx, target.strip())
            except FetchError as exc:
                if (error := ctx.fail(exc, source=self.name, url=self._base)) is not None:
                    yield error
                continue
            for status in statuses:
                if isinstance(status, dict):
                    yield self._event(url, status)

    async def _get(self, ctx: Context, url: str, params: dict[str, Any] | None = None) -> Any:
        response = await ctx.http.get(
            url, params=params, timeout=self.timeout, raise_for_status=False
        )
        if response.status == 404:
            raise FetchError(f"{url}: not found on {self.server}", url=url)
        if response.status >= 400:
            raise api_error(response, self.server, url)
        return response.json()

    async def _statuses(self, ctx: Context, target: str) -> tuple[str, list[Any]]:
        limit = {"limit": self.limit}
        if target in ("trending", "trends"):
            url = f"{self._base}/api/v1/trends/statuses"
            return url, await self._get(ctx, url, limit)
        if target.startswith("#") or target.startswith("tag:"):
            tag = target.lstrip("#").removeprefix("tag:")
            url = f"{self._base}/api/v1/timelines/tag/{quote(tag)}"
            return url, await self._get(ctx, url, limit)
        if target.startswith("@"):
            account = await self._get(
                ctx, f"{self._base}/api/v1/accounts/lookup", {"acct": target.lstrip("@")}
            )
            url = f"{self._base}/api/v1/accounts/{account['id']}/statuses"
            return url, await self._get(ctx, url, {**limit, "exclude_replies": "true"})
        raise FetchError(
            f"not a Mastodon target: {target!r}",
            url=self._base,
            hint="use tag:NAME, #tag, @user or trending",
        )

    def _event(self, url: str, status: dict[str, Any]) -> Event:
        shared_by = None
        if isinstance(status.get("reblog"), dict):
            shared_by = (status.get("account") or {}).get("acct")
            status = status["reblog"]
        account = status.get("account") or {}
        text = strip_html(status.get("content"))
        card = status.get("card") or {}
        return Event(
            source=self.name,
            type="post",
            key=status.get("url") or status.get("uri"),
            source_url=url,
            timestamp=status.get("created_at"),
            data={
                "title": headline(text) or status.get("url"),
                "text": text,
                "author": account.get("acct"),
                "author_name": account.get("display_name") or None,
                "url": status.get("url") or status.get("uri"),
                "created_at": status.get("created_at"),
                "language": status.get("language"),
                "tags": [f"#{t['name']}" for t in status.get("tags") or [] if t.get("name")],
                "links": [card["url"]] if card.get("url") else [],
                "likes": status.get("favourites_count"),
                "reposts": status.get("reblogs_count"),
                "replies": status.get("replies_count"),
                "shared_by": shared_by,
            },
            metadata={"method": "mastodon-api", "server": self.server},
        )
