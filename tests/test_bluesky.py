import asyncio
import json

import pytest

import unlimitedpipe.sources.bluesky as bluesky_module
from unlimitedpipe import Context
from unlimitedpipe.sources.bluesky import Bluesky


def message(
    text, *, time_us=1_790_000_000_000_000, langs=("en",), reply=False, facets=(), op="create"
):
    record = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "langs": list(langs),
        "createdAt": "2026-09-23T10:00:00Z",
    }
    if reply:
        record["reply"] = {"root": {}, "parent": {}}
    if facets:
        record["facets"] = list(facets)
    return {
        "did": "did:plc:abc",
        "time_us": time_us,
        "kind": "commit",
        "commit": {
            "operation": op,
            "collection": "app.bsky.feed.post",
            "rkey": "3k",
            "record": record,
        },
    }


TAG = {"features": [{"$type": "app.bsky.richtext.facet#tag", "tag": "AI"}]}
LINK = {"features": [{"$type": "app.bsky.richtext.facet#link", "uri": "https://x.example/a"}]}


def test_post_event_shape():
    event = Bluesky().post_event(message("New #AI model", facets=[TAG, LINK]))
    assert event is not None
    assert event.type == "post"
    assert event.key == "at://did:plc:abc/app.bsky.feed.post/3k"
    assert event.timestamp == "2026-09-21T14:13:20Z"
    assert event.data["tags"] == ["#ai"] and event.data["links"] == ["https://x.example/a"]
    assert event.data["url"] == "https://bsky.app/profile/did:plc:abc/post/3k"
    assert "did" not in event.data and "author" not in event.data


@pytest.mark.parametrize(
    ("source", "msg", "kept"),
    [
        (Bluesky(), message("hello", reply=True), False),
        (Bluesky(replies=True), message("hello", reply=True), True),
        (Bluesky(lang=["en"]), message("hola", langs=["es"]), False),
        (Bluesky(lang=["en"]), message("hi", langs=["en-US"]), True),
        (Bluesky(search=["ai"]), message("said hello"), False),
        (Bluesky(search=["ai"]), message("New AI model"), True),
        (Bluesky(), message("deleted", op="delete"), False),
        (Bluesky(), {"kind": "identity", "did": "x"}, False),
    ],
)
def test_filters(source, msg, kept):
    assert (source.post_event(msg) is not None) is kept


class FakeSocket:
    def __init__(self, messages, fail_after=None):
        self.messages = messages
        self.fail_after = fail_after

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for index, item in enumerate(self.messages):
            if self.fail_after is not None and index == self.fail_after:
                raise OSError("connection reset")
            yield json.dumps(item)


def test_reconnects_and_resumes_from_the_cursor(monkeypatch):
    urls = []
    sockets = iter(
        [
            FakeSocket([message("one", time_us=1), message("two", time_us=2)], fail_after=2),
            FakeSocket([message("three", time_us=3)]),
        ]
    )

    def fake_connect(url):
        urls.append(url)
        return next(sockets)

    monkeypatch.setattr(bluesky_module, "_connect", fake_connect)
    real_sleep = asyncio.sleep
    monkeypatch.setattr(bluesky_module.asyncio, "sleep", lambda _s: real_sleep(0))

    async def go():
        stream = Bluesky().collect(Context(quiet=True))
        texts = [(await anext(stream)).data["text"] for _ in range(3)]
        await stream.aclose()
        return texts

    assert asyncio.run(go()) == ["one", "two", "three"]
    assert urls[0].endswith("wantedCollections=app.bsky.feed.post")
    assert urls[1].endswith("&cursor=2")


def test_is_an_endless_source():
    assert Bluesky.finite is False
    with pytest.raises(ValueError, match="ws://"):
        Bluesky(endpoint="https://example.com")


def test_author_key_is_opaque():
    event = Bluesky().post_event(message("hello"))
    assert event is not None
    key = event.data["author_key"]
    assert len(key) == 16 and "did" not in key and "abc" not in key
    assert Bluesky().post_event(message("again")).data["author_key"] == key  # same run, same key
