import json

from tests.conftest import fixture, run_source
from unlimitedpipe.event import Event
from unlimitedpipe.sources.file import File
from unlimitedpipe.sources.rss import Rss

BLOG = "https://acme.example/blog/feed.xml"


def test_rss_items_are_normalized(web, ctx):
    web.add(BLOG, fixture("feed.rss"), content_type="application/rss+xml")
    first, second = run_source(Rss(url=[BLOG]), ctx)
    assert first.type == "entry"
    assert first.key == "https://acme.example/blog/post-2"  # feedparser resolves relative GUIDs
    assert first.timestamp == "2026-09-22T08:00:00Z"
    assert first.data["title"] == "Launching AI search"
    assert first.data["link"] == "https://acme.example/blog/ai"
    assert first.data["summary"] == "We built AI search."
    assert first.data["categories"] == ["ai", "product"]
    assert first.data["feed"] == {
        "title": "Acme Blog",
        "url": "https://acme.example/blog",
        "feed_url": BLOG,
    }
    assert second.data["published_at"] == "2026-09-21T08:00:00Z"
    assert first.metadata["method"] == "rss20"


def test_atom_entries(web, ctx):
    url = "https://releases.example/tool.atom"
    web.add(url, fixture("feed.atom"), content_type="application/atom+xml")
    [release] = run_source(Rss(url=[url], content=True), ctx)
    assert release.data["title"] == "v2.0.0"
    assert release.data["link"] == "https://github.com/acme/tool/releases/tag/v2.0.0"
    assert release.data["author"] == "octo"
    assert release.data["content"] == "Breaking changes"


def test_an_atom_id_listed_before_the_links_is_not_the_link(web, ctx):
    # The US Tsunami Warning Centers' feeds put <id>urn:uuid:...</id> before <link>.
    url = "https://tsunami.example/PHEB.xml"
    web.add(
        url,
        """<feed xmlns="http://www.w3.org/2005/Atom"><title>t</title><entry>
        <title>LOYALTY ISLANDS</title><updated>2026-09-25T21:32:45Z</updated>
        <id>urn:uuid:5577a45b</id>
        <link rel="related" href="https://tsunami.example/1/PHEBCAP.xml"/>
        <link rel="alternate" href="https://tsunami.example/1/WEGM42.txt"/>
        </entry></feed>""",
        content_type="application/atom+xml",
    )
    [entry] = run_source(Rss(url=[url]), ctx)
    assert entry.data["link"] == "https://tsunami.example/1/WEGM42.txt"
    assert entry.key == "urn:uuid:5577a45b"


def test_map_data_feedparser_cannot_read_is_dropped_not_fatal(web, ctx):
    # NASA's EONET puts a GML srsName URL where feedparser expects "EPSG:4326".
    url = "https://eonet.example/rss"
    web.add(
        url,
        """<rss version="2.0" xmlns:georss="http://www.georss.org/georss"
        xmlns:gml="http://www.opengis.net/gml"><channel><title>t</title><item>
        <title>Tropical Storm Gonzalo</title><link>https://eonet.example/1</link>
        <georss:where><gml:Point srsName="http://www.opengis.net/def/crs/EPSG/0/4326">
        <gml:pos>13.5 -45.2</gml:pos></gml:Point></georss:where></item></channel></rss>""",
        content_type="application/rss+xml",
    )
    [entry] = run_source(Rss(url=[url]), ctx)
    assert entry.data["title"] == "Tropical Storm Gonzalo"


def test_feed_discovery_from_a_page(web, ctx):
    web.add("https://acme.example/pricing", fixture("article.html"))
    web.add(BLOG, fixture("feed.rss"), content_type="application/rss+xml")
    events = run_source(Rss(url=["https://acme.example/pricing"]), ctx)
    assert len(events) == 2 and events[0].source_url == BLOG


def test_not_a_feed_is_a_clear_failure(web, ctx):
    web.add("https://acme.example/plain", "<html><body>nothing</body></html>")
    assert run_source(Rss(url=["https://acme.example/plain"]), ctx) == []
    assert ctx.failures == 1


def test_json_feed_returns_original_unlimitedpipe_events(web, ctx):
    original = Event(
        source="web",
        type="product",
        key="k",
        data={"price": 1},
        provenance=[{"step": "web", "version": "0.1.0"}],
    )
    document = {
        "version": "https://jsonfeed.org/version/1.1",
        "title": "Prices",
        "items": [
            {"id": "1", "title": "x", "_unlimitedpipe": {"event": original.to_dict()}},
            {
                "id": "2",
                "title": "Plain item",
                "url": "https://p.example/2",
                "tags": ["t"],
                "date_published": "2026-09-01T00:00:00Z",
                "content_html": "<p>Hi <b>there</b></p>",
            },
        ],
    }
    url = "https://alice.example/feed.json"
    web.add(url, json.dumps(document), content_type="application/feed+json")
    network_event, plain = run_source(Rss(url=[url]), ctx)
    assert network_event.id == original.id
    assert network_event.provenance == original.provenance
    assert network_event.metadata["via_feed"] == url
    assert plain.data["title"] == "Plain item" and plain.data["summary"] == "Hi there"
    assert plain.data["categories"] == ["t"] and plain.key == "2"


def test_file_json_with_records_path(tmp_path, ctx):
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"data": {"items": [{"a": 1}, {"a": 2}]}}))
    events = run_source(File(path=[str(path)], records="data.items"), ctx)
    assert [e.data for e in events] == [{"a": 1}, {"a": 2}]
    assert events[0].source == "file" and events[0].source_url == path.resolve().as_uri()


def test_file_jsonl_replays_events_with_provenance(tmp_path, ctx):
    event = Event(
        source="rss", key="k", data={"x": 1}, provenance=[{"step": "rss", "version": "0.1.0"}]
    )
    path = tmp_path / "saved.jsonl"
    path.write_text(event.to_json() + "\n\n" + json.dumps({"plain": True}) + "\n")
    replayed, plain = run_source(File(path=[str(path)]), ctx)
    assert replayed == event
    assert plain.data == {"plain": True} and plain.source == "file"


def test_file_csv_tsv_and_sniffing(tmp_path, ctx):
    (tmp_path / "a.csv").write_text("﻿name,price\nShoe,89\nMug,12\n")
    (tmp_path / "b.tsv").write_text("name\tprice\nHat\t5\n")
    (tmp_path / "c.data").write_text('{"a": 1}\n{"a": 2}\n')
    events = run_source(File(path=[str(tmp_path / n) for n in ("a.csv", "b.tsv", "c.data")]), ctx)
    assert [e.data for e in events] == [
        {"name": "Shoe", "price": "89"},
        {"name": "Mug", "price": "12"},
        {"name": "Hat", "price": "5"},
        {"a": 1},
        {"a": 2},
    ]


def test_file_errors(tmp_path, make_ctx):
    ctx = make_ctx()
    assert run_source(File(path=[str(tmp_path / "missing.json")]), ctx) == []
    assert ctx.failures == 1
