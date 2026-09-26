import asyncio
import io

import pytest

from unlimitedpipe.event import Event
from unlimitedpipe.outputs.pretty import _RENDERERS, Pretty


def render(*events: Event, width: int = 80) -> str:
    from rich.console import Console

    output = Pretty()

    async def go() -> None:
        await output.open(None)
        output._console = Console(file=io.StringIO(), width=width, highlight=False)
        for event in events:
            await output.write(event)

    asyncio.run(go())
    return output._console.file.getvalue()


def test_a_search_result_names_its_feed_and_shows_the_whole_headline():
    event = Event(
        source="search",
        type="entry",
        data={
            "title": "GigaCloud Technology Inc (GCT): Marshall Bernes (director) sold 18,297 "
            "shares at $54.13 ($990.4K)",
            "link": "https://www.sec.gov/Archives/edgar/data/2045034/index.htm",
            "published_at": "2026-09-26T02:08:07Z",
            "feed": "insider-trades",  # a catalog's feed is a name, not a dict
        },
    )
    text = render(event)
    assert "($990.4K)" in " ".join(text.split())
    assert "insider-trades" in text


def test_a_catalog_feed_shows_its_health():
    event = Event(
        source="search",
        type="feed",
        data={
            "title": "earthquakes",
            "summary": "Big earthquakes",
            "files": ["https://feeds.example/earthquakes.xml"],
            "health": {"status": "ok", "latest": "2026-09-25T21:23:03Z"},
        },
    )
    assert render(event).splitlines()[0] == "earthquakes  ok  latest 2026-09-25"


@pytest.mark.parametrize("kind", sorted(_RENDERERS))
@pytest.mark.parametrize(
    "data",
    [{}, {"feed": "name", "fields": [], "sources": [], "checks": []}, {"feed": None}],
)
def test_every_renderer_survives_sparse_events(kind, data):
    render(Event(source="test", type=kind, data=data))
