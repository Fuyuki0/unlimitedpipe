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


def test_a_feed_with_archive_false_is_listed_but_never_archived(repo):
    quakes = repo / "feeds" / "quakes.yml"
    quakes.write_text("archive: false\n" + quakes.read_text())
    p = repo_plan(repo)
    write_catalog(p)
    document = json.loads((repo / "public" / "feeds.json").read_text())
    assert [f.get("archive") for f in document["feeds"] if f["name"] == "quakes"] == [False]
    assert any(i["feed"] == "quakes" for i in document["items"])  # the latest value is shown
    archived = (repo / "public" / "archive").rglob("*.jsonl")
    assert not any("quakes" in path.read_text() for path in archived)  # its history is not kept


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
    assert 'fetch("feeds.json", FRESH)' in page
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
    assert 'echo "$code $1" >> "$results"' in text
    assert 'unlimited catalog --results "$RUNNER_TEMP/unlimitedpipe-results"' in text
    assert 'pip install "git+https://github.com/Fuyuki0/unlimitedpipe@v0.5.0"' in text


def test_a_site_title_shows_and_survives_the_hourly_rebuild(repo):
    from unlimitedpipe.publish import index_page

    p = repo_plan(repo)
    p.title, p.about = "City alerts", "Floods & roads"
    page = index_page(p, "1h")
    assert "<title>City alerts</title>" in page and '<p class="lede">Floods &amp; roads</p>' in page
    assert "<span>Feeds</span><b>2</b>" in page and "Runs every 1h." in page
    assert catalog(p)["title"] == "City alerts"
    hourly = repo_plan(repo)  # `unlimited catalog` in the workflow has no title
    assert catalog(hourly, previous={"title": "City alerts"})["title"] == "City alerts"
    assert catalog(hourly)["title"] == hourly.name


def test_short_words_match_whole_words_only():
    from unlimitedpipe.sources.search import word_pattern

    assert word_pattern("sec").search("SEC charges a trader")
    assert word_pattern("sec").search("the SEC's new rule")
    assert not word_pattern("sec").search("security news")
    assert not word_pattern("ai").search("aid package")
    assert not word_pattern("us").search("user data leaked")
    assert word_pattern("eth").search("Ethereum (ETH) price")
    assert word_pattern("hack").search("hackers stole $5M")  # its own endings
    # four-letter words keep only their own endings; longer words any ending
    assert word_pattern("noto").search("M 7.5 - 2024 Noto Peninsula, Japan Earthquake")
    assert not word_pattern("noto").search("notoriously hard to train")
    assert not word_pattern("gold").search("Goldman Sachs")
    assert word_pattern("iran").search("Iranian oil exports")
    assert word_pattern("tech").search("Dell Technologies")  # named as a synonym
    assert word_pattern("vulnerability").search("vulnerabilities")


def test_search_shows_two_updates_of_a_story_unless_asked(web, make_ctx):
    items = [
        {"feed": "prices", "title": f"Bitcoin (BTC) price: ${p},000", "link": f"b{p}"}
        for p in (84, 83, 82)
    ]
    catalog = {"schema": "unlimitedpipe.catalog/1", "feeds": [{"name": "prices"}], "items": items}
    web.add("https://c.example/feeds.json", json.dumps(catalog), content_type="application/json")
    newest = run_source(
        Search(words=["bitcoin"], catalog="https://c.example/feeds.json"), make_ctx()
    )
    assert [e.data["link"] for e in newest] == ["b84", "b83"]
    every = Search(words=["bitcoin"], catalog="https://c.example/feeds.json", every_update=True)
    assert len(run_source(every, make_ctx())) == 3


def test_words_people_use_match_the_words_sources_use():
    from unlimitedpipe.sources.search import word_pattern

    assert word_pattern("fed").search("Federal Reserve issues FOMC statement")
    assert word_pattern("gdp").search("Gross Domestic Product, 2nd Quarter 2026")
    assert word_pattern("jobless").search("Unemployment Insurance Weekly Claims Report")
    assert word_pattern("purchase").search("a director bought 10,000 shares")
    assert word_pattern("ipos").search("TCGX Acquisition Corp. filed to go public")
    assert not word_pattern("fed").search("fedora")
    assert word_pattern("epa").search("Environmental Protection Agency: Carbon Tetrachloride")
    assert word_pattern("pentagon").search("Defense Department: Acquisition Regulation")


def test_typos_are_searched_as_the_catalog_word_one_letter_away():
    from unlimitedpipe.sources.search import corrected

    document = {
        "feeds": [{"name": "crypto-prices"}],
        "items": [{"title": "Bitcoin (BTC) price: $84,292"}, {"title": "Ethereum price"}],
    }
    assert corrected(["bitcion", "price"], document) == (
        ["bitcoin", "price"],
        {"bitcion": "bitcoin"},
    )
    assert corrected(["zebra"], document) == (["zebra"], {})  # nothing close: left alone
    assert corrected(["crypto"], document) == (["crypto"], {})  # found as typed


def test_flaws_and_bugs_find_vulnerabilities():
    from unlimitedpipe.sources.search import word_pattern

    assert word_pattern("flaws").search("A vulnerability in Cisco Secure Firewall")
    assert word_pattern("bug").search("Critical vulnerabilities in Fortinet")


def test_a_word_the_archive_knows_is_no_typo():
    from unlimitedpipe.sources.search import corrected

    document = {"feeds": [], "items": [{"title": "Reddio raises funds", "summary": ""}]}
    assert corrected(["reddit"], document) == (["reddio"], {"reddit": "reddio"})
    assert corrected(["reddit"], document, {"reddit"}) == (["reddit"], {})


def test_a_catalog_merges_the_newer_items_of_its_live_copy(web, make_ctx):
    import asyncio

    from unlimitedpipe.sources.search import load_catalog

    old = {"feed": "quakes", "title": "M 5.0 - old", "link": "q/1", "date": "2026-09-28T10:00:00Z"}
    new = {"feed": "quakes", "title": "M 6.1 - new", "link": "q/2", "date": "2026-09-28T10:05:00Z"}
    catalog = {
        "schema": "unlimitedpipe.catalog/1",
        "live": "https://live.example/feeds.json",
        "feeds": [{"name": "quakes"}],
        "items": [old],
    }
    web.add("https://c.example/feeds.json", json.dumps(catalog), content_type="application/json")
    web.add(
        "https://live.example/feeds.json",
        json.dumps({"items": [new, old]}),
        content_type="application/json",
    )
    ctx = make_ctx()
    document = asyncio.run(load_catalog(ctx, "https://c.example/feeds.json"))
    assert [i["title"] for i in document["items"]] == ["M 6.1 - new", "M 5.0 - old"]
    # a live copy that cannot be reached leaves the catalog as it is
    catalog["live"] = "https://down.example/feeds.json"
    web.add("https://c2.example/feeds.json", json.dumps(catalog), content_type="application/json")
    document = asyncio.run(load_catalog(make_ctx(), "https://c2.example/feeds.json"))
    assert [i["title"] for i in document["items"]] == ["M 5.0 - old"]


def test_follow_reports_each_new_match_once(tmp_path):
    import subprocess
    import sys

    site = tmp_path / "site"
    site.mkdir()
    item = {"feed": "quakes", "title": "M 5.0 - Japan", "link": "q/1", "date": "2026-09-01"}
    document = {"schema": CATALOG_SCHEMA, "feeds": [{"name": "quakes"}], "items": [item]}
    (site / "feeds.json").write_text(json.dumps(document))
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "UNLIMITEDPIPE_FORMAT": "jsonl",
        "UNLIMITEDPIPE_STATE_DIR": str(tmp_path / "state"),
    }

    def follow():
        run = subprocess.run(
            [
                sys.executable,
                "-m",
                "unlimitedpipe",
                "-q",
                "follow",
                "japan",
                "--catalog",
                str(site),
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        assert run.returncode == 0, run.stderr
        found = [json.loads(line)["data"] for line in run.stdout.splitlines()]
        return [d.get("after", d)["title"] for d in found]  # a change: the item as it is now

    assert follow() == []  # the first run notes what matches now
    new = {"feed": "quakes", "title": "M 6.1 - Japan", "link": "q/2", "date": "2026-09-02"}
    document["items"] = [new, item]
    (site / "feeds.json").write_text(json.dumps(document))
    assert follow() == ["M 6.1 - Japan"]
    assert follow() == []  # sent once
