import asyncio
import csv
import io
import json
import xml.etree.ElementTree as ET

from tests.conftest import ev
from unlimitedpipe import Context
from unlimitedpipe.outputs.csv import Csv
from unlimitedpipe.outputs.feed import ATOM_NS, Feed, feed_item
from unlimitedpipe.outputs.json import Json
from unlimitedpipe.outputs.jsonl import Jsonl


def write(output, events):
    async def go():
        await output.open(Context(quiet=True))
        for event in events:
            await output.write(event)
        await output.close()

    asyncio.run(go())


EVENTS = [
    ev({"title": "A", "price": 1, "offer": {"currency": "USD"}}, key="a", source_url="https://s/a"),
    ev({"title": "B", "tags": ["x", "y"]}, key="b", source_url="https://s/b"),
]


def test_jsonl_full_and_data(tmp_path):
    path = tmp_path / "out.jsonl"
    write(Jsonl(path=str(path)), EVENTS)
    lines = path.read_text().splitlines()
    assert json.loads(lines[0])["key"] == "a"
    write(Jsonl(path=str(path), data=True, append=True), EVENTS[:1])
    assert json.loads(path.read_text().splitlines()[-1]) == EVENTS[0].data


def test_json_writes_data_or_full_events(tmp_path):
    path = tmp_path / "out.json"
    write(Json(path=str(path)), EVENTS)
    assert json.loads(path.read_text()) == [e.data for e in EVENTS]
    write(Json(path=str(path), full=True, indent=0), EVENTS)
    assert json.loads(path.read_text())[1]["source_url"] == "https://s/b"


def test_json_empty_stream_is_an_empty_array(tmp_path):
    path = tmp_path / "out.json"
    write(Json(path=str(path)), [])
    assert json.loads(path.read_text()) == []


def test_csv_flattens_and_unions_columns(tmp_path):
    path = tmp_path / "out.csv"
    write(Csv(path=str(path), source_url=True), EVENTS)
    rows = list(csv.DictReader(io.StringIO(path.read_text())))
    assert list(rows[0]) == ["title", "price", "offer.currency", "source_url", "tags"]
    assert rows[0]["offer.currency"] == "USD"
    assert rows[1]["tags"] == '["x", "y"]'


def test_csv_fixed_columns(tmp_path):
    path = tmp_path / "out.csv"
    write(Csv(path=str(path), columns=["title"]), EVENTS)
    assert path.read_text().splitlines() == ["title", "A", "B"]


def change_event(price_old, price_new):
    return ev(
        {
            "change": "modified",
            "label": "Pro",
            "summary": f"price: {price_old} → {price_new}",
            "fields": [{"path": "price", "old": price_old, "new": price_new}],
            "after": {"url": "https://s/pro"},
        },
        type="change",
        key="https://s#pro",
        source_url="https://s/pricing",
    )


def test_feed_item_for_changes_and_entries():
    item = feed_item(change_event(49, 59))
    assert item["title"] == "Pro: price: 49 → 59"
    assert item["link"] == "https://s/pro"
    entry = feed_item(
        ev({"title": "Post", "link": "https://b/1", "summary": "Hi there", "categories": ["ai"]})
    )
    assert (entry["title"], entry["link"], entry["summary"], entry["categories"]) == (
        "Post",
        "https://b/1",
        "Hi there",
        ["ai"],
    )


def test_added_items_read_like_the_item():
    added = ev(
        {
            "change": "added",
            "label": "Gemini 4",
            "summary": "added: Gemini 4",
            "after": {"title": "Gemini 4", "link": "https://n/1", "summary": "A new model."},
        },
        type="change",
    )
    item = feed_item(added)
    assert (item["title"], item["link"], item["summary"]) == (
        "Gemini 4",
        "https://n/1",
        "A new model.",
    )


def test_boilerplate_summaries_are_dropped():
    hn = (
        "Article URL: https://a.example/x\n"
        "Comments URL: https://news.ycombinator.com/item?id=1\n"
        "Points: 74\n# Comments: 45"
    )
    assert feed_item(ev({"title": "A", "summary": hn}))["summary"] is None
    assert feed_item(ev({"title": "B", "summary": "Comments"}))["summary"] is None
    assert (
        feed_item(ev({"title": "C", "summary": "Security update"}))["summary"] == "Security update"
    )


def test_new_records_show_their_values():
    added = ev(
        {
            "change": "added",
            "label": "Team",
            "item_type": "record",
            "after": {"name": "Team", "price": "$99"},
        },
        type="change",
    )
    assert feed_item(added)["summary"] == "price $99"


def test_feed_summaries_are_short():
    item = feed_item(ev({"title": "Long", "summary": "word " * 300}))
    assert len(item["summary"]) <= 501 and item["summary"].endswith("…")
    assert feed_item(ev({"title": "Page", "text": "Just text"}))["summary"] == "Just text"


def test_rss_feed_keeps_history_newest_first(tmp_path):
    path = tmp_path / "changes.xml"
    write(Feed(path=str(path), title="Changes"), [change_event(49, 59)])
    before = path.read_bytes()
    write(Feed(path=str(path), title="Changes"), [])
    assert path.read_bytes() == before  # an empty run leaves the file untouched
    write(
        Feed(path=str(path), title="Changes", max_items=2),
        [change_event(59, 69), change_event(69, 79)],
    )
    channel = ET.fromstring(path.read_text()).find("channel")
    assert channel is not None
    assert channel.findtext("title") == "Changes"
    assert channel.findtext("link") == "https://s/pricing"  # kept through the empty run
    assert [i.findtext("title") for i in channel.findall("item")] == [
        "Pro: price: 59 → 69",
        "Pro: price: 69 → 79",
    ]


def test_atom_and_json_feed(tmp_path):
    atom = tmp_path / "f.atom"
    write(Feed(path=str(atom)), EVENTS)
    root = ET.fromstring(atom.read_text())
    assert root.tag == f"{{{ATOM_NS}}}feed"
    assert len(root.findall(f"{{{ATOM_NS}}}entry")) == 2

    feed_json = tmp_path / "f.json"
    write(Feed(path=str(feed_json)), EVENTS)
    write(Feed(path=str(feed_json)), [ev({"title": "C"}, key="c")])
    document = json.loads(feed_json.read_text())
    assert document["version"] == "https://jsonfeed.org/version/1.1"
    assert [i["title"] for i in document["items"]] == ["C", "A", "B"]
    assert document["items"][1]["_unlimitedpipe"]["event"]["key"] == "a"
