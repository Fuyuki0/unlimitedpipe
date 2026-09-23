import asyncio

import pytest

from tests.conftest import ev, run_ops
from unlimitedpipe import Context, Source, __version__
from unlimitedpipe.engine import build_stream
from unlimitedpipe.errors import ConfigError, ExpressionError
from unlimitedpipe.operators.dedupe import Dedupe
from unlimitedpipe.operators.filter import Filter
from unlimitedpipe.operators.grep import Grep
from unlimitedpipe.operators.limit import Limit
from unlimitedpipe.operators.map import Map
from unlimitedpipe.operators.select import Select
from unlimitedpipe.operators.sort import Sort


def test_select_keeps_renames_and_fills_missing_with_null():
    events = [ev({"title": "A", "offers": [{"price": 5}], "noise": 1}, source_url="https://a")]
    [out] = run_ops(events, Select(fields=["title", "price=offers.0.price", "source_url", "gone"]))
    assert out.data == {"title": "A", "price": 5, "source_url": "https://a", "gone": None}
    assert out.source_url == "https://a"
    assert out.provenance == [
        {
            "step": "select",
            "version": __version__,
            "args": {"fields": ["title", "price=offers.0.price", "source_url", "gone"]},
        }
    ]


def test_select_falls_back_to_alternative_paths():
    events = [ev({"title": "A", "link": "https://a"}), ev({"title": "B", "url": "https://b"})]
    out = run_ops(events, Select(fields=["title", "link=link|url"]))
    assert [e.data for e in out] == [
        {"title": "A", "link": "https://a"},
        {"title": "B", "link": "https://b"},
    ]


def test_select_rejects_name_clashes():
    with pytest.raises(ValueError, match="both be named"):
        Select(fields=["a.title", "b.title"])


def test_filter_expression_and_field_form():
    events = [
        ev({"price": p, "country": c})
        for p, c in [(10, "Thailand"), (200, "Thailand"), (300, "Laos")]
    ]
    assert [e.data["price"] for e in run_ops(events, Filter(expr="price > 100"))] == [200, 300]
    assert [e.data["price"] for e in run_ops(events, Filter(field="country", eq="Thailand"))] == [
        10,
        200,
    ]
    assert [e.data["price"] for e in run_ops(events, Filter(field="price", gt=100, lt=250))] == [
        200
    ]


def test_filter_needs_exactly_one_form():
    with pytest.raises(ValueError):
        Filter()
    with pytest.raises(ValueError):
        Filter(expr="a > 1", field="a", eq="1")
    with pytest.raises(ValueError, match="needs a test"):
        Filter(field="a")
    with pytest.raises(ExpressionError):
        Filter(expr="a >")


def test_map_assigns_in_order_and_drops():
    events = [ev({"name": "shoe", "price": "89.00", "junk": 1})]
    [out] = run_ops(
        events,
        Map(
            assign=["title=upper(name)", "cheap=price < 100", 'currency="USD"', "shout=title"],
            drop=["junk"],
        ),
    )
    assert out.data == {
        "name": "shoe",
        "price": "89.00",
        "title": "SHOE",
        "cheap": True,
        "currency": "USD",
        "shout": "SHOE",
    }


def test_grep_matches_whole_words_ignoring_case():
    events = [
        ev({"title": t})
        for t in ["New AI model", "She said hello", "ai-powered tool", "Maintenance"]
    ]
    assert [e.data["title"] for e in run_ops(events, Grep(patterns=["AI"]))] == [
        "New AI model",
        "ai-powered tool",
    ]
    assert len(run_ops(events, Grep(patterns=["ai"], substring=True))) == 4
    assert [e.data["title"] for e in run_ops(events, Grep(patterns=["AI"], invert=True))] == [
        "She said hello",
        "Maintenance",
    ]
    assert len(run_ops(events, Grep(patterns=["ai"], case_sensitive=True))) == 1


def test_grep_skips_web_addresses_for_plain_words():
    events = [
        ev(
            {"title": "Jev in 25 lines", "summary": "Article URL: https://www.nobodywho.ai/posts/x"}
        ),
        ev({"title": "New AI model", "link": "https://example.com"}),
    ]
    assert [e.data["title"] for e in run_ops(events, Grep(patterns=["AI"]))] == ["New AI model"]
    assert len(run_ops(events, Grep(patterns=["nobodywho.ai"]))) == 1


def test_grep_field_and_regex():
    events = [ev({"title": "x", "body": "security update"}), ev({"title": "security", "body": ""})]
    assert [
        e.data["title"] for e in run_ops(events, Grep(patterns=["security"], field=["title"]))
    ] == ["security"]
    assert len(run_ops(events, Grep(patterns=[r"secur\w+"], regex=True))) == 2


def test_dedupe_by_key_field_and_content():
    events = [
        ev({"url": "a", "v": 1}, key="k1"),
        ev({"url": "a", "v": 2}, key="k1"),
        ev({"url": "b", "v": 1}, key="k2"),
    ]
    assert len(run_ops(events, Dedupe())) == 2
    assert [e.data["url"] for e in run_ops(events, Dedupe(by=["url"]))] == ["a", "b"]
    assert len(run_ops(events, Dedupe(by=["content"]))) == 3


def test_dedupe_window_bounds_memory():
    events = [ev({"n": n}, key=str(n)) for n in [1, 2, 1]]
    assert len(run_ops(events, Dedupe(window=1))) == 3
    assert len(run_ops(events, Dedupe(window=2))) == 2


class Endless(Source):
    """Never ends; records how many events were pulled."""

    name = "endless"
    finite = False

    def __init__(self) -> None:  # type: ignore[no-redef]
        self.pulled = 0

    async def collect(self, ctx):
        while True:
            self.pulled += 1
            yield ev({"n": self.pulled})


def test_limit_stops_the_source():
    source = Endless()

    async def go():
        stream = build_stream([source], [Limit(count=3)], Context(quiet=True))
        return [event async for event in stream]

    assert [e.data["n"] for e in asyncio.run(go())] == [1, 2, 3]
    assert source.pulled == 3
    assert run_ops([ev(), ev()], Limit(count=0)) == []


def test_buffering_operator_refuses_endless_stream_unless_limited():
    with pytest.raises(ConfigError, match="never ends"):
        build_stream([Endless()], [Sort()], Context(quiet=True))
    build_stream([Endless()], [Limit(count=5), Sort()], Context(quiet=True))


def test_sort_numbers_text_and_missing_last():
    events = [ev({"p": "10"}), ev({"p": 9}), ev({}), ev({"p": 100.5})]
    assert [e.data.get("p") for e in run_ops(events, Sort(by=["p"]))] == [9, "10", 100.5, None]
    assert [e.data.get("p") for e in run_ops(events, Sort(by=["p"], reverse=True))] == [
        100.5,
        "10",
        9,
        None,
    ]


def test_sort_defaults_to_timestamp():
    events = [ev(timestamp="2026-01-02T00:00:00Z"), ev(timestamp="2026-01-01T00:00:00Z")]
    assert [e.timestamp for e in run_ops(events, Sort())] == [
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    ]
