"""Shared shape for posts from social platforms, so pipes treat every platform alike."""

from __future__ import annotations

import re
from typing import Any

from unlimitedpipe.errors import FetchError


def headline(text: str, limit: int = 120) -> str:
    """The start of a post, short enough to be a feed item's title: its first line, joined
    with the next ones while that line is too short to say anything (an emoji, a heading)."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    title = ""
    for line in (line for line in lines if line):
        title = f"{title} {line}".strip()
        if len(re.sub(r"[\W_]", "", title)) >= 20:
            break
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


def api_error(response: Any, service: str, url: str, hint: str | None = None) -> FetchError:
    """A readable error for an API response that failed."""
    detail = response.text.strip().replace("\n", " ")[:200]
    return FetchError(
        f"{service} returned HTTP {response.status}" + (f": {detail}" if detail else ""),
        url=url,
        hint=hint,
    )
