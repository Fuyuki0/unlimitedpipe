import asyncio
import json
import subprocess
from pathlib import Path

import httpx
import pytest

from tests.conftest import run_source
from unlimitedpipe import Context
from unlimitedpipe.config import load_pipeline
from unlimitedpipe.mcp import Server, builtin_tools
from unlimitedpipe.publish import CATALOG_SCHEMA, catalog, plan, workflow, write_catalog
from unlimitedpipe.sources.search import Search, catalog_url, matches

PIPELINE = """
name: {name}
description: {description}
sources: [{{type: file, path: data.json}}]
outputs:
  - {{type: feed, path: ../public/{name}.xml}}
  - {{type: feed, path: ../public/{name}.json}}
"""


def json_feed(*items):
    return {"version": "https://jsonfeed.org/version/1.1", "title": "t", "items": list(items)}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "remote", "add", "origin", "git@github.com:Ana/feeds.git"],
        check=True,
    )
    (tmp_path / "feeds").mkdir()
    (tmp_path / "public").mkdir()
    for name, description in [("quakes", "Big earthquakes"), ("recalls", "Food recalls")]:
        (tmp_path / "feeds" / f"{name}.yml").write_text(
            PIPELINE.format(name=name, description=description)
        )
    (tmp_path / "public" / "quakes.json").write_text(
        json.dumps(
            json_feed(
                {
                    "title": "M6.4 Papua New Guinea",
                    "content_text": "M6.4 Papua New Guinea",
                    "url": "https://usgs.example/1",
                    "date_published": "2026-09-20T09:17:35Z",
                },
                {
                    "title": "M7.0 Loyalty Islands",
                    "summary": "Tsunami information bulletin issued",
                    "url": "https://usgs.example/2",
                    "date_published": "2026-09-25T21:44:05Z",
                },
            )
        )
    )
    return tmp_path


def repo_plan(repo: Path):
    paths = sorted((repo / "feeds").glob("*.yml"))
    return plan([(p, load_pipeline(p)) for p in paths], 3600)


def test_catalog_lists_feeds_and_their_latest_items_newest_first(repo):
    document = catalog(repo_plan(repo))
    assert document["schema"] == CATALOG_SCHEMA
    assert document["feeds"] == [
        {
            "name": "quakes",
            "description": "Big earthquakes",
            "files": ["quakes.xml", "quakes.json"],
        },
        {
            "name": "recalls",
            "description": "Food recalls",
            "files": ["recalls.xml", "recalls.json"],
        },
    ]  # recalls.json is not written yet: listed, without items
    assert [i["title"] for i in document["items"]] == [
        "M7.0 Loyalty Islands",
        "M6.4 Papua New Guinea",
    ]
    assert document["items"][1]["summary"] is None  # a summary that repeats the title is dropped
    assert document["items"][0]["feed"] == "quakes"


def test_write_catalog_only_rewrites_on_change(repo):
    p = repo_plan(repo)
    assert write_catalog(p) == repo / "public" / "feeds.json"
    assert write_catalog(p) is None
    assert "unlimited catalog " in workflow(p)


def serve_catalog(web, url="https://feeds.example/feeds.json", document=None):
    web.add(
        url,
        json.dumps(
            document
            or {
                "schema": CATALOG_SCHEMA,
                "feeds": [{"name": "quakes", "description": "Big earthquakes", "files": ["q.xml"]}],
                "items": [
                    {"feed": "news", "title": "Hacks by AI agents", "link": "https://n/1"},
                    {"feed": "news", "title": "Thackeray speaks", "link": "https://n/2"},
                    {"feed": "quakes", "title": "M7.0 Loyalty Islands", "summary": "Tsunami"},
                    {"feed": "thai", "title": "น้ำท่วมกรุงเทพ", "link": "https://t/1"},
                ],
            }
        ),
        content_type="application/json",
    )


def test_search_finds_items_across_feeds(web, make_ctx):
    serve_catalog(web)
    results = run_source(Search(words=["hack"], catalog="https://feeds.example/"), make_ctx())
    assert [e.data["title"] for e in results] == ["Hacks by AI agents"]
    assert results[0].data["feed"] == "news" and results[0].source_url == "https://n/1"
    thai = run_source(Search(words=["ท่วม"], catalog="https://feeds.example/"), make_ctx())
    assert [e.data["link"] for e in thai] == ["https://t/1"]
    both = run_source(
        Search(words=["tsunami", "loyalty"], feed=["quakes"], catalog="https://feeds.example/"),
        make_ctx(),
    )
    assert len(both) == 1


def test_search_lists_feeds_with_absolute_urls(web, make_ctx):
    serve_catalog(web)
    [feed] = run_source(Search(list_feeds=True, catalog="https://feeds.example/"), make_ctx())
    assert feed.type == "feed" and feed.data["files"] == ["https://feeds.example/q.xml"]


def test_search_refuses_what_is_not_a_catalog(web, make_ctx):
    web.add("https://feeds.example/feeds.json", "{}", content_type="application/json")
    ctx = make_ctx(errors_as_events=True)
    [error] = run_source(Search(words=["x"], catalog="https://feeds.example/"), ctx)
    assert error.type == "error" and "not a feed catalog" in error.data["error"]
    with pytest.raises(ValueError, match="needs words"):
        Search()


def test_catalog_url(monkeypatch):
    monkeypatch.delenv("UNLIMITEDPIPE_CATALOG", raising=False)
    assert catalog_url(None) == "https://feeds.daemonfill.dev/feeds.json"
    assert catalog_url("https://x.example/sub") == "https://x.example/sub/feeds.json"
    assert catalog_url("https://x.example/c.json") == "https://x.example/c.json"
    monkeypatch.setenv("UNLIMITEDPIPE_CATALOG", "https://mine.example/")
    assert catalog_url(None) == "https://mine.example/feeds.json"


def test_word_matching():
    assert matches({"title": "Green flood alert in Thailand"}, ["thailand", "FLOOD"])
    assert not matches({"title": "Raj Thackeray"}, ["hack"])


def test_ai_agents_can_search_the_catalog(web, tmp_path, monkeypatch):
    monkeypatch.setenv("UNLIMITEDPIPE_CATALOG", "https://feeds.example/")
    serve_catalog(web)
    server = Server(
        builtin_tools(),
        context=lambda **o: Context(
            transport=httpx.MockTransport(web.handler),
            state_dir=tmp_path / "state",
            cache_dir=tmp_path / "cache",
            host_interval=0,
            **o,
        ),
    )
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "search_feeds", "arguments": {"query": "loyalty islands"}},
    }
    result = asyncio.run(server.handle(message))["result"]
    [event] = result["structuredContent"]["events"]
    assert event["data"]["title"] == "M7.0 Loyalty Islands"


def test_the_index_page_searches_the_catalog_in_the_browser(repo):
    from unlimitedpipe.publish import index_page

    page = index_page(repo_plan(repo), "1h")
    assert '<input id="q" type="search"' in page
    assert 'fetch("feeds.json")' in page
    assert "textContent" in page and "innerHTML" not in page  # feed text is never parsed as HTML
