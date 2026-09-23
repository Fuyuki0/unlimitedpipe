from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from typing import Any

import httpx
import pytest

from unlimitedpipe import Context, Event
from unlimitedpipe.component import Operator, Source
from unlimitedpipe.engine import build_stream

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeWeb:
    """A tiny fake internet for tests: URL -> response. robots.txt is 404 unless set."""

    def __init__(self) -> None:
        self.pages: dict[str, Any] = {}
        self.requests: list[httpx.Request] = []

    def add(
        self,
        url: str,
        body: bytes | str = b"",
        *,
        status: int = 200,
        content_type: str = "text/html; charset=utf-8",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.pages[url] = (status, body, {"content-type": content_type, **(headers or {})})

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        page = self.pages.get(url)
        if callable(page):
            return page(request)
        if page is None:
            return httpx.Response(404, text="not found")
        status, body, headers = page
        return httpx.Response(
            status, content=body.encode() if isinstance(body, str) else body, headers=headers
        )

    def urls(self) -> list[str]:
        return [str(r.url) for r in self.requests]


@pytest.fixture
def web() -> FakeWeb:
    return FakeWeb()


@pytest.fixture
def make_ctx(tmp_path: Path, web: FakeWeb):
    def make(**kwargs: Any) -> Context:
        kwargs.setdefault("quiet", True)
        return Context(
            transport=httpx.MockTransport(web.handler),
            state_dir=tmp_path / "state",
            cache_dir=tmp_path / "cache",
            host_interval=0,
            **kwargs,
        )

    return make


@pytest.fixture
def ctx(make_ctx) -> Context:
    return make_ctx()


async def _aiter(events: Iterable[Event]) -> AsyncIterator[Event]:
    for event in events:
        yield event


class ListSource(Source):
    """Emits a fixed list of events (tests only)."""

    name = "list"

    def __init__(self, events: list[Event]) -> None:  # type: ignore[no-redef]
        self._events = events

    def provenance_step(self):
        return None

    async def collect(self, ctx):
        for event in self._events:
            yield event


def run_source(source: Source, ctx: Context) -> list[Event]:
    async def go() -> list[Event]:
        try:
            return [event async for event in source.collect(ctx)]
        finally:
            await ctx.aclose()

    return asyncio.run(go())


def run_ops(events: list[Event], *operators: Operator, ctx: Context | None = None) -> list[Event]:
    ctx = ctx or Context(quiet=True)

    async def go() -> list[Event]:
        stream = build_stream([ListSource(events)], list(operators), ctx)
        return [event async for event in stream]

    return asyncio.run(go())


def ev(data: dict[str, Any] | None = None, **kwargs: Any) -> Event:
    kwargs.setdefault("source", "test")
    return Event(data=data or {}, **kwargs)
