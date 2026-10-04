import gzip
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
        {
            "month": "2026-09",
            "file": "2026-09.jsonl",
            "items": 2,
            "feeds": {"news": 1, "quakes": 1},
        },
        {"month": "2026-08", "file": "2026-08.jsonl", "items": 1, "feeds": {"quakes": 1}},
    ]
    # each month is also split by feed, for readers that want one feed's items
    assert (tmp_path / "archive" / "2026-08" / "quakes.jsonl").read_text().count("\n") == 1
    assert month_of({"date": "garbage"}, "2026-10-01T00:00:00Z") == "2026-10"


def test_a_title_with_a_unicode_line_separator_stays_one_record(tmp_path):
    item = {"feed": "uk", "title": "Speech\u2028by the minister", "link": "https://x/1",
            "date": "2026-09-01T00:00:00Z"}  # fmt: skip
    append(tmp_path, [item, {**item, "title": "Other", "link": "https://x/2"}], "2026-09-02")
    text = (tmp_path / "archive" / "2026-09.jsonl").read_text(encoding="utf-8")
    assert len(text.splitlines()) == 2  # escaped, so even splitlines() sees two records
    assert json.loads(text.splitlines()[0])["title"] == "Speech\u2028by the minister"
    assert append(tmp_path, [item], "2026-09-03") == {}  # and it is known again


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
    assert parse_since("2010") == "2010-01"  # a year: from its first month
    with pytest.raises(ValueError, match="like 2010, 2026-08"):
        parse_since("August")


def whole_words(archive: Path) -> dict:
    """The archive's whole word index, which is kept gzipped."""
    from unlimitedpipe.archive import WORDS, WORDS_GZ

    assert not (archive / WORDS).exists()  # only the gzipped copy is written
    return json.loads(gzip.decompress((archive / WORDS_GZ).read_bytes()))


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
    # the copy's index lists only the months it holds, so older ones are not looked for
    index = json.loads((copy / "archive" / "index.json").read_text())
    assert [m["month"] for m in index["months"]] == ["2026-09"] and "shards" not in index
    older = subprocess.run(
        [
            sys.executable,
            "-m",
            "unlimitedpipe",
            "search",
            "quakes",
            "--since",
            "2026-01",
            "--catalog",
            str(copy),
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "UNLIMITEDPIPE_FORMAT": "jsonl"},
    )
    assert older.returncode == 0, older.stderr


def test_a_month_missing_from_a_copy_is_left_out_with_a_warning(tmp_path):
    import asyncio

    from unlimitedpipe.sources.search import items_since

    site = local_catalog(tmp_path)
    for month in site.glob("archive/2026-08*"):
        if month.is_file():
            month.unlink()
    document = json.loads((site / "feeds.json").read_text())
    ctx = Context(quiet=True, state_dir=tmp_path / "s", cache_dir=tmp_path / "c")
    found = asyncio.run(items_since(ctx, str(site / "feeds.json"), document, "2026-01"))
    assert found  # the months still there, not an error


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


def test_search_looks_in_the_archive_when_no_latest_item_has_the_words(tmp_path):
    site = local_catalog(tmp_path)
    append(site, [{**ITEMS[1], "title": "Tonga news", "link": "https://t/2"}], "T")
    ctx = Context(quiet=True, state_dir=tmp_path / "s", cache_dir=tmp_path / "c")
    # quoted words are words, each of which must appear (here "quakes" as the feed's name)
    found = run_source(Search(words=["tonga quakes"], catalog=str(site), exact=True), ctx)
    assert sorted(e.data["title"] for e in found) == ["M6.1 Tonga", "Tonga news"]
    ctx = Context(quiet=True, state_dir=tmp_path / "s", cache_dir=tmp_path / "c")
    # an archive word is no typo, though no latest item has it
    found = run_source(Search(words=["tonga"], catalog=str(site), exact=True), ctx)
    assert [e.data["title"] for e in found] == ["M6.1 Tonga", "Tonga news"]


def test_the_word_index_leads_undated_questions_to_their_months(tmp_path):
    import asyncio

    from unlimitedpipe.archive import WORDS_GZ, write_words
    from unlimitedpipe.sources.search import items_by_words

    site = local_catalog(tmp_path)
    table = whole_words(site / "archive")["words"]
    assert table["tonga"] == ["2026-08"] and table["loyalt"] == ["2026-09"]  # stemmed
    append(site, [{**ITEMS[1], "title": "Tonga tsunami warning", "link": "https://t/1"}], "T")
    assert whole_words(site / "archive")["words"]["tonga"] == ["2026-08"]
    (site / "archive" / WORDS_GZ).unlink()
    write_words(site / "archive")  # rebuilt from every month
    assert whole_words(site / "archive")["words"]["tsunami"] == ["2026-08"]

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


def test_a_word_naming_a_feed_narrows_the_others_to_that_feed(tmp_path):
    import asyncio

    from unlimitedpipe.sources.search import items_by_words

    site = tmp_path / "site"
    trades = [
        {
            "feed": "insider-trades",
            "title": f"Acme Corp: a director sold shares {n}",
            "link": f"https://t/{n}",
            "date": f"2025-{n:02d}-03T00:00:00Z",
        }
        for n in range(1, 13)
    ] + [
        {
            "feed": "insider-trades",
            "title": "Acme Corp: the CEO sold shares",
            "link": "https://t/13",
            "date": "2024-12-03T00:00:00Z",
        }
    ]
    ipo = {
        "feed": "ipo-filings",
        "title": "Acme Corp filed to go public (S-1)",
        "link": "https://i/1",
        "date": "2024-06-10T00:00:00Z",
    }
    append(site, [*trades, ipo], "2026-01-01T00:00:00Z")
    table = whole_words(site / "archive")["words"]
    assert table["acme@ipo-filings"] == ["2024-06"] and len(table["acme"]) == 14
    document = {
        "archive": "archive/index.json",
        "feeds": [{"name": "insider-trades"}, {"name": "ipo-filings"}],
        "items": [],
    }
    (site / "feeds.json").write_text(json.dumps(document))

    async def find(words):
        ctx = Context(quiet=True, state_dir=tmp_path / "s", cache_dir=tmp_path / "c")
        try:
            return await items_by_words(ctx, str(site / "feeds.json"), document, words)
        finally:
            await ctx.aclose()

    assert [i["title"] for i in asyncio.run(find(["acme", "ipo"]))] == [ipo["title"]]


def test_a_period_reads_only_the_feeds_that_can_hold_the_words(tmp_path):
    import asyncio

    from unlimitedpipe.archive import BY_FEED
    from unlimitedpipe.sources.search import items_since

    site = tmp_path / "site"
    items = [
        {
            "feed": "quakes",
            "title": "M 7.5 - Noto Peninsula, Japan",
            "link": "https://q/1",
            "date": "2024-01-01T07:10:00Z",
        },
        {
            "feed": "trades",
            "title": "Acme Corp: a director sold shares",
            "link": "https://t/1",
            "date": "2024-01-02T00:00:00Z",
        },
    ]
    append(site, items, "2026-01-01T00:00:00Z")
    shard = json.loads((site / "archive" / BY_FEED / "ja.json").read_text())
    assert shard["words"] == {"japan": {"quakes": ["2024-01"]}}
    assert "ja" in json.loads((site / "archive" / "index.json").read_text())["shards"]
    document = {
        "archive": "archive/index.json",
        "feeds": [{"name": "quakes", "description": "Earthquakes"}, {"name": "trades"}],
        "items": [],
    }
    (site / "feeds.json").write_text(json.dumps(document))
    ctx = Context(quiet=True, state_dir=tmp_path / "s", cache_dir=tmp_path / "c")
    feeds_json = str(site / "feeds.json")
    found = asyncio.run(items_since(ctx, feeds_json, document, "2024-01", "2024-12", ["japan"]))
    assert [i["feed"] for i in found] == ["quakes"]  # the trades file was not read
    everything = asyncio.run(items_since(ctx, feeds_json, document, "2024-01", "2024-12"))
    assert sorted(i["feed"] for i in everything) == ["quakes", "trades"]
    # 2024-01 is long closed, so it is compressed, its files by feed too
    assert (site / "archive" / "2024-01.jsonl.gz").exists()
    assert json.loads((site / "archive" / "index.json").read_text())["months"][0]["packed"]
    (site / "archive" / "2024-01" / "quakes.jsonl.gz").unlink()  # a split that does not add up
    from unlimitedpipe.archive import write_index

    write_index(site / "archive")
    found = asyncio.run(items_since(ctx, feeds_json, document, "2024-01", "2024-12", ["japan"]))
    assert sorted(i["feed"] for i in found) == ["quakes", "trades"]  # read the whole month


def test_a_question_reads_only_the_word_files_it_needs(tmp_path):
    import asyncio

    from unlimitedpipe.archive import shard_of
    from unlimitedpipe.sources import search

    site = tmp_path / "site"
    items = [
        {
            "feed": "hacks",
            "title": f"Ronin bridge drained {n}",
            "link": f"https://h/{n}",
            "date": f"20{20 + n}-03-01T00:00:00Z",
        }
        for n in range(3)
    ] + [
        {
            "feed": "news",
            "title": "Zebra crossing",
            "link": "https://n/1",
            "date": "2024-05-01T00:00:00Z",
        }
    ]
    append(site, items, "2026-01-01T00:00:00Z")
    assert shard_of("ronin") == "ro" and shard_of("x-ray") == "x_" and shard_of("é") == "__"
    document = {"archive": "archive/index.json", "feeds": [{"name": "hacks"}], "items": []}
    (site / "feeds.json").write_text(json.dumps(document))
    read_files = []
    real_read = search.read

    async def spy(ctx, location):
        read_files.append(location.rsplit("archive/", 1)[-1])
        return await real_read(ctx, location)

    ctx = Context(quiet=True, state_dir=tmp_path / "s", cache_dir=tmp_path / "c")
    search.read = spy
    try:
        found = asyncio.run(
            search.items_by_words(ctx, str(site / "feeds.json"), document, ["ronin"])
        )
        known = asyncio.run(
            search.archive_words(
                ctx, str(site / "feeds.json"), document, ["ronin", "zebras", "roninn"]
            )
        )
    finally:
        search.read = real_read
    assert len(found) == 3
    assert known == {"ronin", "zebra"}
    assert "words.json" not in read_files and "words/ro.json" in read_files
    assert "words/ze.json" in read_files


def test_closed_months_are_compressed_and_open_again_for_a_late_item(tmp_path):
    import gzip

    from unlimitedpipe.archive import pack_old

    late = {"feed": "quakes", "title": "M 6.0 late", "link": "https://q/9", "date": "2026-06-01"}
    append(tmp_path, ITEMS, "2026-09-26T00:00:00Z")
    folder = tmp_path / "archive"
    assert (folder / "2026-08.jsonl").exists()  # last month stays open
    assert pack_old(folder, "2026-10-01T00:00:00Z") == 1  # in October, August closes
    assert not (folder / "2026-08.jsonl").exists()
    packed = folder / "2026-08.jsonl.gz"
    assert gzip.decompress(packed.read_bytes()).decode().count("\n") == 1
    assert (folder / "2026-08" / "quakes.jsonl.gz").exists()
    # an item for a closed month opens it, and the same run closes it again
    assert append(tmp_path, [ITEMS[1], late], "2026-10-02T00:00:00Z") == {"2026-06": 1}
    assert not (folder / "2026-06.jsonl").exists() and (folder / "2026-06.jsonl.gz").exists()
    assert append(tmp_path, [ITEMS[1]], "2026-10-03T00:00:00Z") == {}  # still known
    index = json.loads((folder / "index.json").read_text())
    august = next(m for m in index["months"] if m["month"] == "2026-08")
    assert august == {
        "month": "2026-08",
        "file": "2026-08.jsonl.gz",
        "items": 1,
        "packed": True,
        "bytes": (folder / "2026-08.jsonl.gz")
        .stat()
        .st_size,  # its counts are kept until it changes
        "feeds": {"quakes": 1},
    }
    # and search reads them
    document = {
        "schema": CATALOG_SCHEMA,
        "archive": "archive/index.json",
        "feeds": [{"name": "quakes"}],
        "items": [],
    }
    (tmp_path / "feeds.json").write_text(json.dumps(document))
    ctx = Context(quiet=True, state_dir=tmp_path / "s", cache_dir=tmp_path / "c")
    found = run_source(Search(words=["late"], catalog=str(tmp_path), since="2026-01"), ctx)
    assert [e.data["title"] for e in found] == ["M 6.0 late"]


def test_word_index_updated_in_place_matches_a_full_rebuild(tmp_path):
    from unlimitedpipe.archive import write_words

    folder = tmp_path / "archive"
    append(tmp_path, ITEMS, "2026-09-26T00:00:00Z")
    later = [
        {
            "feed": "news",
            "title": "Quake damages homes",
            "link": "https://a/9",
            "date": "2026-09-27",
        },
        {"feed": "quakes", "title": "M 6.0 - Chile", "link": "https://a/10", "date": "2026-08-05"},
    ]
    append(tmp_path, later, "2026-09-28T00:00:00Z")  # updates the index with the two items

    def index() -> dict[str, str]:
        return {
            p.relative_to(folder).as_posix(): gzip.decompress(p.read_bytes())
            if p.suffix == ".gz"
            else p.read_text()
            for p in [folder / "words.json.gz", *folder.glob("words*/*.json")]
        }

    updated = index()
    assert json.loads((folder / "words-by-feed" / "qu.json").read_text())["complete"] is True
    write_words(folder)  # every month read again
    assert index() == updated


def test_titles_are_cleaned_as_they_are_added(tmp_path):
    from unlimitedpipe.archive import clean_title

    assert (
        clean_title("Colombia: EQUIPOS DE CROMATOGRAFÃ\x8dA")
        == "Colombia: EQUIPOS DE CROMATOGRAFÍA"
    )
    assert clean_title("Mexico: INSTALACIÃ“N and itâ€™s") == "Mexico: INSTALACIÓN and it’s"
    assert clean_title("Hunga Tonga-Hunga Ha&#039;apai") == "Hunga Tonga-Hunga Ha'apai"
    assert clean_title("Roasted &amp;amp; Salted") == "Roasted & Salted"
    for kept in ("SÃO PAULO", "Âge", "Größe", "naïve café", "Rock & Roll"):
        assert clean_title(kept) == kept
    item = {"feed": "f", "title": "Ha&#039;apai", "link": "https://a/1", "date": "2026-09-01"}
    append(tmp_path, [item], "2026-09-02T00:00:00Z")
    append(tmp_path, [{**item, "title": "Ha'apai"}], "2026-09-03T00:00:00Z")  # the same item
    lines = (tmp_path / "archive" / "2026-09.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["title"] == "Ha'apai"
