import json

import pytest

from unlimitedpipe.errors import InputError
from unlimitedpipe.event import SCHEMA, Event, iso, parse_time
from unlimitedpipe.fields import MISSING, flatten, resolve


def test_round_trip_keeps_every_field():
    event = Event(
        source="web",
        type="product",
        data={"name": "Shoe", "price": 89.0},
        source_url="https://store.example/shoe",
        key="https://store.example/shoe#sku-1",
        timestamp="2026-09-01T00:00:00Z",
        metadata={"method": "json-ld"},
        provenance=[{"step": "web", "version": "0.1.0"}],
    )
    line = event.to_json()
    assert json.loads(line)["schema"] == SCHEMA
    assert Event.from_json(line) == event


def test_id_is_stable_for_same_content_and_changes_with_data():
    a = Event(source="web", key="k", data={"price": 1})
    b = Event(source="web", key="k", data={"price": 1}, observed_at="2030-01-01T00:00:00Z")
    c = Event(source="web", key="k", data={"price": 2})
    assert a.id == b.id
    assert a.id != c.id


def test_plain_json_is_wrapped_as_record():
    event = Event.from_dict({"title": "hello"})
    assert event.source == "stdin"
    assert event.type == "record"
    assert event.data == {"title": "hello"}
    assert Event.from_dict([1, 2]).data == {"value": [1, 2]}


def test_future_schema_is_rejected_with_a_hint():
    with pytest.raises(InputError) as info:
        Event.from_dict({"schema": "unlimitedpipe.event/9", "data": {}})
    assert "upgrade" in (info.value.hint or "")


def test_label_prefers_title_then_name_then_key():
    assert Event(source="t", data={"title": " Pro "}).label == "Pro"
    assert Event(source="t", data={"name": "Shoe"}).label == "Shoe"
    assert Event(source="t", key="k", data={}).label == "k"


def test_resolve_looks_in_data_then_envelope():
    event = Event(
        source="web",
        source_url="https://x",
        data={"title": "T", "offers": [{"price": 5}]},
        metadata={"status": 200},
    )
    assert resolve(event, "title") == "T"
    assert resolve(event, "offers.0.price") == 5
    assert resolve(event, "source_url") == "https://x"
    assert resolve(event, "metadata.status") == 200
    assert resolve(event, "data.source_url") is MISSING
    assert resolve(event, "nope") is MISSING


def test_flatten_uses_dotted_keys_and_json_lists():
    assert flatten({"a": {"b": 1}, "tags": ["x"], "empty": {}}) == {
        "a.b": 1,
        "tags": '["x"]',
        "empty": "{}",
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-09-20T09:17:35Z", "2026-09-20T09:17:35Z"),
        ("2026-09-20T16:17:35+07:00", "2026-09-20T09:17:35Z"),
        ("2026-09-20", "2026-09-20T00:00:00Z"),
        ("Sun, 20 Sep 2026 09:17:35 GMT", "2026-09-20T09:17:35Z"),
        (1790500655, "2026-09-27T09:17:35Z"),
        (1790500655624, "2026-09-27T09:17:35Z"),
        (1790500655624000, "2026-09-27T09:17:35Z"),
        ("1790500655624", "2026-09-27T09:17:35Z"),
        ("next week", None),
        (True, None),
        (None, None),
        ([2026], None),
        ("nan", None),
    ],
)
def test_parse_time(value, expected):
    assert iso(parse_time(value)) == expected


def test_parse_time_converts_offsets_to_utc():
    from unlimitedpipe.event import parse_time

    when = parse_time("2026-09-25T17:11:02-04:00")
    assert when is not None and when.strftime("%Y-%m-%dT%H:%M:%SZ") == "2026-09-25T21:11:02Z"
    rfc = parse_time("Fri, 25 Sep 2026 10:23:10 +0700")
    assert rfc is not None and rfc.strftime("%H:%M") == "03:23"
