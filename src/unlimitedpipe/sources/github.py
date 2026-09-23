"""The ``github`` source: public repository data through GitHub's official REST API."""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Literal

from unlimitedpipe.component import Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError
from unlimitedpipe.event import Event

API = "https://api.github.com"
_REPO = re.compile(r"^(?:https?://github\.com/)?([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def parse_repo(text: str) -> str:
    """``owner/repo`` or ``https://github.com/owner/repo`` -> ``owner/repo``."""
    match = _REPO.match(text.strip())
    if not match:
        raise ValueError(f"not a GitHub repository: {text!r}; use owner/repo")
    return f"{match.group(1)}/{match.group(2)}"


def _login(value: Any) -> str | None:
    return value.get("login") if isinstance(value, dict) else None


def _first_line(text: Any) -> str:
    return str(text or "").strip().splitlines()[0] if str(text or "").strip() else ""


class GitHub(Source):
    """Public GitHub data through the official REST API: releases, repository stats, tags,
    commits or issues.

    Works without an account at 60 requests per hour. Set `GITHUB_TOKEN` (or `--token`) for
    5,000 per hour. Unchanged results are revalidated with ETags, which GitHub does not count
    against the limit.
    """

    name = "github"
    examples = (
        "unlimited github releases astral-sh/uv ollama/ollama",
        "unlimited github repo pallets/click | unlimited select full_name stars forks",
        "unlimited github issues owner/repo --limit 50 | unlimited diff --only added",
    )

    resource: Literal["releases", "repo", "tags", "commits", "issues"] = arg("What to read")
    repo: list[str] = arg("Repositories as owner/repo", metavar="OWNER/REPO...")
    limit: int = opt("Items per repository, up to 100 (not used for `repo`)", default=30)
    token: str | None = opt("API token (default: $GITHUB_TOKEN)", default=None, secret=True)
    timeout: float = opt("Seconds to wait for each response", default=20.0)

    def __post_init__(self) -> None:
        if not self.repo:
            raise ValueError("github needs at least one owner/repo")
        self._repos = [parse_repo(r) for r in self.repo]
        if not 1 <= self.limit <= 100:
            raise ValueError("--limit must be between 1 and 100")

    async def collect(self, ctx: Context):
        token = self.token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        for repo in self._repos:
            path = f"/repos/{repo}" if self.resource == "repo" else f"/repos/{repo}/{self.resource}"
            url = API + path
            try:
                payload = await self._get(ctx, url, headers, authenticated=bool(token))
            except FetchError as exc:
                if (error := ctx.fail(exc, source=self.name, url=url)) is not None:
                    yield error
                continue
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                if isinstance(item, dict):
                    yield self._event(repo, url, item)

    async def _get(
        self, ctx: Context, url: str, headers: dict[str, str], *, authenticated: bool
    ) -> Any:
        params = None if self.resource == "repo" else {"per_page": self.limit}
        response = await ctx.http.get(
            url, params=params, headers=headers, timeout=self.timeout, raise_for_status=False
        )
        remaining = response.headers.get("x-ratelimit-remaining")
        if response.status in (403, 429) and remaining == "0":
            reset = response.headers.get("x-ratelimit-reset", "")
            when = (
                datetime.fromtimestamp(int(reset)).strftime("%H:%M") if reset.isdigit() else "soon"
            )
            raise FetchError(
                f"GitHub API rate limit reached; it resets at {when}",
                url=url,
                hint=None if authenticated else "set GITHUB_TOKEN for 5,000 requests per hour",
            )
        if response.status == 404:
            raise FetchError(
                f"{url}: repository not found (or private)", url=url, hint="check owner/repo"
            )
        if response.status >= 400:
            raise FetchError(f"{url} returned HTTP {response.status}", url=url)
        return response.json()

    def _event(self, repo: str, url: str, item: dict[str, Any]) -> Event:
        kind, key, timestamp, data = self._shape(repo, item)
        return Event(
            source=self.name,
            type=kind,
            source_url=url,
            key=key,
            timestamp=timestamp,
            data={"repo": repo, **data},
            metadata={"method": "github-api"},
        )

    def _shape(
        self, repo: str, item: dict[str, Any]
    ) -> tuple[str, str, str | None, dict[str, Any]]:
        user = _login(item.get("user")) or _login(item.get("author"))
        if self.resource == "releases":
            return (
                "release",
                item.get("html_url") or str(item.get("id")),
                item.get("published_at"),
                {
                    "title": item.get("name") or item.get("tag_name"),
                    "tag": item.get("tag_name"),
                    "url": item.get("html_url"),
                    "published_at": item.get("published_at"),
                    "prerelease": item.get("prerelease"),
                    "author": user,
                    "summary": str(item.get("body") or "")[:2000] or None,
                    "assets": len(item.get("assets") or []),
                },
            )
        if self.resource == "repo":
            license_info = item.get("license") or {}
            return (
                "repository",
                item.get("html_url") or repo,
                None,
                {
                    "title": item.get("full_name"),
                    "description": item.get("description"),
                    "url": item.get("html_url"),
                    "stars": item.get("stargazers_count"),
                    "forks": item.get("forks_count"),
                    "open_issues": item.get("open_issues_count"),
                    "watchers": item.get("subscribers_count"),
                    "language": item.get("language"),
                    "topics": item.get("topics") or [],
                    "license": license_info.get("spdx_id")
                    if isinstance(license_info, dict)
                    else None,
                    "homepage": item.get("homepage") or None,
                    "archived": item.get("archived"),
                    "pushed_at": item.get("pushed_at"),
                },
            )
        if self.resource == "tags":
            name = item.get("name")
            commit = item.get("commit") or {}
            return (
                "tag",
                f"https://github.com/{repo}/releases/tag/{name}",
                None,
                {
                    "title": name,
                    "sha": commit.get("sha"),
                    "url": f"https://github.com/{repo}/releases/tag/{name}",
                },
            )
        if self.resource == "commits":
            commit = item.get("commit") or {}
            date = (commit.get("author") or {}).get("date")
            return (
                "commit",
                item.get("html_url") or item.get("sha", ""),
                date,
                {
                    "title": _first_line(commit.get("message")),
                    "sha": item.get("sha"),
                    "url": item.get("html_url"),
                    "author": user or (commit.get("author") or {}).get("name"),
                    "date": date,
                },
            )
        return (
            "issue",
            item.get("html_url") or str(item.get("id")),
            item.get("created_at"),
            {
                "title": item.get("title"),
                "number": item.get("number"),
                "url": item.get("html_url"),
                "state": item.get("state"),
                "author": user,
                "labels": [
                    label.get("name")
                    for label in item.get("labels") or []
                    if isinstance(label, dict)
                ],
                "comments": item.get("comments"),
                "pull_request": "pull_request" in item,
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            },
        )
