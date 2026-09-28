import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import run_source
from unlimitedpipe import Context
from unlimitedpipe.archive import append, item_key, month_of, named_period, parse_since
from unlimitedpipe.publish import CATALOG_SCHEMA
from unlimitedpipe.sources.search import Search, catalog_url

ITEMS = [
    {
        "feed": "quakes",
        "title": "M7.0 Loyalty Islands",
        "link": "https://q/1",
        "date": "2026-09-25T21:44:05Z",
    },
    {
        "feed": "quakes",
        "title": "M6.1 Tonga",
        "link": "https://q/0",
        "date": "2026-08-02T01:00:00Z",
    },
    {"feed": "news", "title": "Undated story", "link": "https://n/1", "date": None},
]


def test_append_adds_each_item_once_into_its_month(tmp_path):
    added = append(tmp_path, ITEMS, "2026-09-26T00:00:00Z")
    assert added == {"2026-08": 1, "2026-09": 2}  # the undated item goes to the month it was seen
    assert append(tmp_path, ITEMS, "2026-09-26T01:00:00Z") == {}  # nothing new
    lines = (tmp_path / "archive" / "2026-09.jsonl").read_text().splitlines()
    first = json.loads(lines[0])
    assert first["key"] == item_key(ITEMS[0]) and first["seen"] == "2026-09-26T00:00:00Z"
    index = json.loads((tmp_path / "archive" / "index.json").read_text())
    assert index["months"] == [
        {"month": "2026-09", "file": "2026-09.jsonl", "items": 2},
        {"month": "2026-08", "file": "2026-08.jsonl", "items": 1},
    ]
    assert month_of({"date": "garbage"}, "2026-10-01T00:00:00Z") == "2026-10"


def test_items_sharing_one_page_are_all_kept(tmp_path):
    # A list of hacks links every item to the same page; the same story from two sources
    # differs only in case.
    hacks = [
        {"feed": "hacks", "title": t, "link": "https://h/list", "date": "2026-09-24T00:00:00Z"}
        for t in ("Bitget: $387M lost", "Duelbits: $7M lost", "BITGET:  $387M LOST")
    ]
    assert append(tmp_path, hacks, "2026-09-26T00:00:00Z") == {"2026-09": 2}


def test_archives_keyed_by_link_alone_are_rekeyed_not_duplicated(tmp_path):
    folder = tmp_path / "archive"
    folder.mkdir()
    old = {**ITEMS[0], "key": "0123456789abcdef", "seen": "2026-09-25T00:00:00Z"}
    (folder / "2026-09.jsonl").write_text(json.dumps(old) + "\n")
    assert append(tmp_path, ITEMS[:1], "2026-09-26T00:00:00Z") == {}


def test_parse_since():
    assert parse_since(" 2026-08 ") == "2026-08" and parse_since("2026-08-15") == "2026-08-15"
    with pytest.raises(ValueError, match="like 2026-08"):
        parse_since("August")


def local_catalog(folder: Path) -> Path:
    site = folder / "site"
    latest = [ITEMS[0]]
    (site).mkdir(parents=True)
    (site / "feeds.json").write_text(
        json.dumps(
            {
                "schema": CATALOG_SCHEMA,
                "archive": "archive/index.json",
                "feeds": [{"name": "quakes", "files": ["quakes.xml"]}],
                "items": latest,
            }
        )
    )
    append(site, ITEMS, "2026-09-26T00:00:00Z")
    return site


def test_search_reads_local_catalogs_and_their_archive(tmp_path):
    site = local_catalog(tmp_path)
    assert catalog_url(str(site)) == str(site / "feeds.json")
    ctx = Context(quiet=True, state_dir=tmp_path / "s", cache_dir=tmp_path / "c")
    latest = run_source(Search(words=["quakes"], catalog=str(site)), ctx)
    assert [e.data["title"] for e in latest] == ["M7.0 Loyalty Islands"]
    ctx = Context(quiet=True, state_dir=tmp_path / "s", cache_dir=tmp_path / "c")
    history = run_source(Search(words=["quakes"], catalog=str(site), since="2026-08"), ctx)
    assert [e.data["title"] for e in history] == ["M7.0 Loyalty Islands", "M6.1 Tonga"]
    ctx = Context(quiet=True, state_dir=tmp_path / "s", cache_dir=tmp_path / "c")
    recent = run_source(Search(words=["quakes"], catalog=str(site), since="2026-09-01"), ctx)
    assert [e.data["title"] for e in recent] == ["M7.0 Loyalty Islands"]


def test_mirror_copies_a_catalog_for_offline_use(tmp_path):
    site = local_catalog(tmp_path)
    (site / "index.html").write_text("<html>search</html>")
    copy = tmp_path / "offline"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "unlimitedpipe",
            "mirror",
            str(copy),
            "--catalog",
            str(site),
            "--since",
            "2026-09",
        ],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    assert sorted(p.relative_to(copy).as_posix() for p in copy.rglob("*") if p.is_file()) == [
        "archive/2026-09.jsonl",
        "archive/index.json",
        "archive/words.json",
        "feeds.json",
        "index.html",
    ]
    search = subprocess.run(
        [sys.executable, "-m", "unlimitedpipe", "search", "loyalty", "--catalog", str(copy)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "UNLIMITEDPIPE_FORMAT": "jsonl"},
    )
    assert json.loads(search.stdout)["data"]["title"] == "M7.0 Loyalty Islands"


def test_mirror_refuses_paths_that_leave_the_folder(tmp_path):
    import asyncio

    from unlimitedpipe.errors import FetchError
    from unlimitedpipe.offline import mirror

    site = tmp_path / "site"
    site.mkdir()
    (site / "feeds.json").write_text(
        json.dumps(
            {"schema": CATALOG_SCHEMA, "archive": "../../etc/index.json", "feeds": [], "items": []}
        )
    )
    ctx = Context(quiet=True, state_dir=tmp_path / "s", cache_dir=tmp_path / "c")
    with pytest.raises(FetchError, match="refusing the path"):
        asyncio.run(mirror(ctx, str(site), tmp_path / "out", since=None, feeds=False))


def test_serve_needs_a_catalog_folder(tmp_path):
    run = subprocess.run(
        [sys.executable, "-m", "unlimitedpipe", "serve", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 2 and "has no feeds.json" in run.stderr


def test_named_period_finds_the_months_a_question_names():
    today = "2026-09-27T00:00:00Z"
    assert named_period("earthquakes in 2023", today) == ("2023-01", "2023-12", ["2023"])
    assert named_period("Rules in March 2025?", today) == ("2025-03", "2025-03", ["march", "2025"])
    assert named_period("cves 2025-03", today) == ("2025-03", "2025-03", ["2025-03"])
    assert named_period("what happened last year", today)[:2] == ("2025-01", "2025-12")
    assert named_period("python 3.15 release", today) is None
    assert named_period("python 2027 roadmap", today) is None  # not in the past


def test_search_and_ask_use_the_archive_for_a_period_they_name(tmp_path):
    from unlimitedpipe.sources.ask import Ask

    site = local_catalog(tmp_path)
    ctx = Context(quiet=True, state_dir=tmp_path / "s", cache_dir=tmp_path / "c")
    found = run_source(Search(words=["quakes", "August", "2026"], catalog=str(site)), ctx)
    assert [e.data["title"] for e in found] == ["M6.1 Tonga"]
    ctx = Context(quiet=True, state_dir=tmp_path / "s", cache_dir=tmp_path / "c")
    ask = Ask(question=["loyalty", "islands", "quake", "in", "2025?"], catalog=str(site))
    ask.provider = "anthropic"  # no meaning search: that needs Ollama
    [answer] = run_source(ask, ctx)
    assert answer.data["answer"].startswith("Nothing in the catalog from 2025 matches")


def test_the_word_index_leads_undated_questions_to_their_months(tmp_path):
    import asyncio

    from unlimitedpipe.archive import WORDS, write_words
    from unlimitedpipe.sources.search import items_by_words

    site = local_catalog(tmp_path)
    table = json.loads((site / "archive" / WORDS).read_text())["words"]
    assert table["tonga"] == ["2026-08"] and table["loyalt"] == ["2026-09"]  # stemmed
    append(site, [{**ITEMS[1], "title": "Tonga tsunami warning", "link": "https://t/1"}], "T")
    assert json.loads((site / "archive" / WORDS).read_text())["words"]["tonga"] == ["2026-08"]
    (site / "archive" / WORDS).unlink()
    write_words(site / "archive")  # rebuilt from every month
    assert json.loads((site / "archive" / WORDS).read_text())["words"]["tsunami"] == ["2026-08"]

    async def find(words):
        ctx = Context(quiet=True, state_dir=tmp_path / "s", cache_dir=tmp_path / "c")
        try:
            document = json.loads((site / "feeds.json").read_text())
            return await items_by_words(ctx, str(site / "feeds.json"), document, words)
        finally:
            await ctx.aclose()

    assert sorted(i["title"] for i in asyncio.run(find(["tonga"]))) == [
        "M6.1 Tonga",
        "Tonga tsunami warning",
    ]
    assert asyncio.run(find(["mars"])) == []
