import json
from pathlib import Path

from unlimitedpipe import Context
from unlimitedpipe.archive import append
from unlimitedpipe.publish import CATALOG_SCHEMA
from unlimitedpipe.validate import validate

ITEM = {
    "feed": "quakes",
    "title": "M7.0 Loyalty Islands",
    "summary": None,
    "link": "https://q.example/1",
    "date": "2026-09-25T21:44:05Z",
}


def site(tmp_path: Path, **changes) -> Path:
    folder = tmp_path / "site"
    folder.mkdir(parents=True, exist_ok=True)
    document = {
        "schema": CATALOG_SCHEMA,
        "title": "Test feeds",
        "archive": "archive/index.json",
        "feeds": [
            {
                "name": "quakes",
                "description": "Big earthquakes",
                "files": ["quakes.xml"],
                "health": {"status": "ok", "since": "2026-09-26T00:00:00Z"},
            }
        ],
        "items": [ITEM],
        **changes,
    }
    (folder / "feeds.json").write_text(json.dumps(document))
    (folder / "quakes.xml").write_text("<rss version='2.0'><channel></channel></rss>")
    append(folder, [ITEM], "2026-09-26T00:00:00Z")
    return folder


def run(folder: Path, tmp_path: Path, deep: bool = False):
    import asyncio

    async def go():
        ctx = Context(quiet=True, state_dir=tmp_path / "s", cache_dir=tmp_path / "c")
        try:
            return await validate(ctx, str(folder), deep=deep)
        finally:
            await ctx.aclose()

    return asyncio.run(go())


def test_a_good_catalog_is_valid(tmp_path):
    report = run(site(tmp_path), tmp_path, deep=True)
    assert report.findings == []
    assert {"quakes.xml", "archive/index.json", "2026-09.jsonl"} <= set(report.checked)


def test_feeds_that_never_had_an_item_or_went_quiet_are_warned_about(tmp_path):
    def feed(name, latest):
        health = {"status": "ok", "since": "2026-09-26T00:00:00Z", "latest": latest}
        return {"name": name, "description": "x", "files": ["quakes.xml"], "health": health}

    from datetime import UTC, datetime

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    feeds = [feed("quakes", now), feed("empty", None), feed("old", "2020-01-01")]
    report = run(site(tmp_path, feeds=feeds), tmp_path)
    messages = {f.where: f.message for f in report.findings if f.level == "warning"}
    assert messages["feed 'empty'"] == "has never had an item"
    assert messages["feed 'old'"].startswith("no new item for ")
    assert "feed 'quakes'" not in messages


def test_protocol_errors_are_reported(tmp_path):
    bad = dict(ITEM, feed="volcanoes", link="urn:uuid:1", date="yesterday")
    report = run(site(tmp_path, items=[bad, ITEM, ITEM]), tmp_path)
    messages = [f"{f.level}: {f.message}" for f in report.findings]
    assert "error: names a feed the catalog does not list: 'volcanoes'" in messages
    assert "error: link is not an absolute web address: 'urn:uuid:1'" in messages
    assert "error: date is not ISO 8601: 'yesterday'" in messages
    assert any(m.startswith("warning: repeats an item of quakes") for m in messages)


def test_unknown_versions_and_missing_files_are_errors(tmp_path):
    report = run(site(tmp_path, schema="unlimitedpipe.catalog/2"), tmp_path)
    assert report.errors == 1 and "does not know" in report.findings[0].message
    folder = site(tmp_path / "b")
    (folder / "quakes.xml").unlink()
    report = run(folder, tmp_path, deep=True)
    assert any("quakes.xml" in f.message for f in report.findings if f.level == "error")
