import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from tests.conftest import run_source
from unlimitedpipe import Context
from unlimitedpipe.config import load_pipeline
from unlimitedpipe.errors import UsageError
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


def test_the_same_story_from_two_sources_is_listed_once(repo):
    story = {"url": "https://bbc.example/snow", "date_published": "2026-09-25T22:12:48Z"}
    (repo / "public" / "recalls.json").write_text(
        json.dumps(
            json_feed(
                {**story, "id": "from-science", "title": "The treasured 'eternal snow'"},
                {**story, "id": "from-world", "title": "The Treasured 'Eternal Snow'"},
            )
        )
    )
    document = catalog(repo_plan(repo))
    assert [i["title"] for i in document["items"] if i["feed"] == "recalls"] == [
        "The treasured 'eternal snow'"
    ]


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


def test_without_the_internet_search_uses_the_offline_copy(web, make_ctx, tmp_path, monkeypatch):
    monkeypatch.setenv("UNLIMITEDPIPE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("UNLIMITEDPIPE_CATALOG", raising=False)
    # The default catalog is not served: it cannot be reached.
    ctx = make_ctx(errors_as_events=True)
    [error] = run_source(Search(words=["hack"]), ctx)
    assert error.type == "error"
    copy = tmp_path / "catalog"
    copy.mkdir(parents=True)
    serve_catalog(web)
    document = json.loads(web.pages["https://feeds.example/feeds.json"][1])
    (copy / "feeds.json").write_text(json.dumps(document))
    results = run_source(Search(words=["hack"]), make_ctx())
    assert [e.data["title"] for e in results] == ["Hacks by AI agents"]
    on_purpose = run_source(Search(words=["hack"], catalog="offline"), make_ctx())
    assert len(on_purpose) == 1
    # A catalog chosen on purpose never falls back to something else.
    ctx = make_ctx(errors_as_events=True)
    [error] = run_source(Search(words=["hack"], catalog="https://other.example/"), ctx)
    assert error.type == "error"


def test_unknown_feeds_and_empty_results_are_explained(web, make_ctx, capsys):
    serve_catalog(web)
    with pytest.raises(UsageError, match="no feed named 'quake'") as error:
        run_source(Search(feed=["quake"], catalog="https://feeds.example/"), make_ctx())
    assert error.value.hint == "did you mean 'quakes'?"
    ctx = make_ctx()
    ctx.quiet = False
    assert run_source(Search(words=["volcano"], catalog="https://feeds.example/"), ctx) == []
    assert "Nothing matches 'volcano'. Every word must appear" in capsys.readouterr().err


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


def test_feed_health_follows_runs_and_only_moves_on_change(repo):
    p = repo_plan(repo)
    first = catalog(p, results={"feeds/quakes.yml": 0, "feeds/recalls.yml": 2}, now="T1")
    quakes, recalls = first["feeds"]
    assert quakes["health"] == {"status": "ok", "since": "T1", "latest": "2026-09-25T21:44:05Z"}
    assert recalls["health"] == {"status": "failing", "since": "T1", "latest": None}
    second = catalog(
        p, results={"feeds/quakes.yml": 0, "feeds/recalls.yml": 1}, previous=first, now="T2"
    )
    assert second["feeds"][0]["health"]["since"] == "T1"  # still ok: unchanged
    assert second["feeds"][1]["health"] == {"status": "partial", "since": "T2", "latest": None}
    local = catalog(p, previous=second, now="T3")  # no results: keep what was known
    assert local["feeds"][1]["health"]["status"] == "partial"


def test_catalog_command_reads_a_runs_results(repo):
    results = repo / "results.txt"
    results.write_text(f"0 {repo}/feeds/quakes.yml\n2 {repo}/feeds/recalls.yml\n")
    command = [sys.executable, "-m", "unlimitedpipe", "catalog", "--results", str(results)]
    run = subprocess.run(
        [*command, "feeds/quakes.yml", "feeds/recalls.yml"],
        cwd=repo,
        capture_output=True,
        text=True,
        env={**os.environ, "GITHUB_ACTIONS": "true"},
    )
    assert run.returncode == 0, run.stderr
    assert "::warning::recalls: failing since" in run.stderr
    document = json.loads((repo / "public" / "feeds.json").read_text())
    assert [f["health"]["status"] for f in document["feeds"]] == ["ok", "failing"]


def test_workflow_records_results_and_installs_what_it_is_told(repo):
    p = repo_plan(repo)
    p.install = "git+https://github.com/Fuyuki0/unlimitedpipe@v0.5.0"
    text = workflow(p)
    assert 'echo "$code $pipeline" >> "$RUNNER_TEMP/unlimitedpipe-results"' in text
    assert 'unlimited catalog --results "$RUNNER_TEMP/unlimitedpipe-results"' in text
    assert 'pip install "git+https://github.com/Fuyuki0/unlimitedpipe@v0.5.0"' in text
