import asyncio

import pytest
import yaml

from tests.conftest import fixture
from unlimitedpipe.config import parse_pipeline
from unlimitedpipe.errors import UsageError
from unlimitedpipe.scaffold import pipeline_name, render, scaffold

URL = "https://www.store.example/products/trail-shoe"


def build(yaml_text: str):
    return parse_pipeline(yaml.safe_load(yaml_text), text=yaml_text)


def test_pipeline_name():
    assert pipeline_name(URL) == "store-example-products-trail-shoe"
    assert pipeline_name("https://blog.example/") == "blog-example"


def test_product_page_becomes_a_price_watch():
    result = render(
        URL,
        {
            "kind": "page",
            "title": 'Trail "Pro" Shoe',
            "product_method": "json-ld",
            "feeds": ["https://x/feed"],
        },
    )
    pipeline = build(result.yaml)
    assert result.name == "store-example-products-trail-shoe"
    assert [s.name for s in pipeline.sources] == ["web"]
    assert [o.name for o in pipeline.operators] == ["diff"]
    assert pipeline.outputs[0].title == 'Price and stock: Trail "Pro" Shoe'
    assert "json-ld" in result.description


def test_site_with_a_feed_becomes_a_new_items_watch():
    result = render(
        "https://blog.example",
        {"kind": "page", "title": "Blog", "feeds": ["https://blog.example/atom.xml"]},
    )
    pipeline = build(result.yaml)
    assert pipeline.sources[0].url == ["https://blog.example/atom.xml"]
    diff = pipeline.operators[0]
    assert diff.only == ["added"] and diff.emit_initial is True


def test_feed_url_json_api_and_plain_page():
    feed = build(render("https://blog.example/feed.xml", {"kind": "feed"}).yaml)
    assert feed.sources[0].name == "rss"
    api = build(render("https://api.example/items", {"kind": "json"}).yaml)
    assert api.outputs[0].name == "jsonl" and api.outputs[0].append is True
    page = render("https://example.com", {"kind": "page", "title": "Example", "js_required": True})
    assert "renders with JavaScript" in page.yaml
    assert build(page.yaml).operators[0].ignore == ["word_count"]


def test_blocked_page_is_refused():
    with pytest.raises(UsageError, match=r"robots\.txt"):
        render(URL, {"kind": "blocked"})


def test_scaffold_inspects_the_real_page(web, ctx):
    web.add("https://acme.example/shoe", fixture("product-jsonld.html"))
    result = asyncio.run(scaffold("https://acme.example/shoe", ctx))
    assert result.name == "acme-example-shoe"
    assert "product data (json-ld)" in result.yaml


def test_scaffold_respects_robots(web, ctx):
    web.add(
        "https://acme.example/robots.txt", "User-agent: *\nDisallow: /", content_type="text/plain"
    )
    with pytest.raises(UsageError, match=r"robots\.txt"):
        asyncio.run(scaffold("https://acme.example/shoe", ctx))
