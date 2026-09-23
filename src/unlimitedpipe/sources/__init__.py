"""Built-in sources: each emits a stream of events."""

from __future__ import annotations

from collections.abc import AsyncIterator

from unlimitedpipe.context import Context
from unlimitedpipe.errors import UsageError


async def input_urls(urls: list[str], ctx: Context, *, command: str) -> AsyncIterator[str]:
    """URLs given as arguments, or else piped in: plain lines or events with ``url``/``link``.

    Piping makes crawls composable::

        unlimited web https://blog.example.com --emit links | unlimited grep 2026 | unlimited web
    """
    if urls:
        for url in urls:
            yield url
        return
    if ctx.input is None:
        raise UsageError(
            f"{command} needs a URL",
            hint=f"unlimited {command} https://example.com   (or pipe URLs into it, one per line)",
        )
    count = 0
    async for event in ctx.input:
        data = event.data
        for candidate in (data.get("url"), data.get("link"), data.get("value"), event.source_url):
            if isinstance(candidate, str) and candidate.strip():
                count += 1
                yield candidate.strip()
                break
    if count == 0:
        raise UsageError(
            f"{command} needs a URL, and none was piped in",
            hint=f"unlimited {command} https://example.com",
        )
