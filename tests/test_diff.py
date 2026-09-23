import asyncio
import json

import pytest

from tests.conftest import ev, run_ops
from unlimitedpipe import Context
from unlimitedpipe.engine import build_stream
from unlimitedpipe.errors import ConfigError
from unlimitedpipe.operators.diff import Diff, compare, summarize

PAGE = "https://store.example/pricing"


def plans(**prices):
    return [
        ev({"name": name, "price": price}, source="web", source_url=PAGE, key=f"{PAGE}#{name}")
        for name, price in prices.items()
    ]


@pytest.fixture
def diff_ctx(tmp_path):
    return lambda: Context(quiet=True, state_dir=tmp_path)


def test_first_run_is_a_baseline_then_only_changes(diff_ctx):
    assert run_ops(plans(basic=9, pro=49), Diff(), ctx=diff_ctx()) == []
    assert run_ops(plans(basic=9, pro=49), Diff(), ctx=diff_ctx()) == []

    changes = run_ops(plans(basic=9, pro=59, team=99), Diff(), ctx=diff_ctx())
    by_kind = {c.data["change"]: c for c in changes}
    assert set(by_kind) == {"modified", "added"}
    modified = by_kind["modified"]
    assert modified.type == "change"
    assert modified.key == f"{PAGE}#pro"
    assert modified.data["fields"] == [{"path": "price", "old": 49, "new": 59}]
    assert modified.data["summary"] == "price: 49 → 59"
    assert modified.data["label"] == "pro"
    assert modified.data["after"] == {"name": "pro", "price": 59}
    assert modified.source_url == PAGE
    assert modified.provenance[-1]["step"] == "diff"


def test_removed_only_when_the_source_was_fetched(diff_ctx):
    other = ev({"name": "x"}, source="web", source_url="https://other.example", key="other")
    run_ops([*plans(basic=9, pro=49), other], Diff(namespace="w"), ctx=diff_ctx())

    # other.example failed this time: its item must not be reported as removed.
    changes = run_ops(plans(basic=9), Diff(namespace="w"), ctx=diff_ctx())
    assert [(c.data["change"], c.data["label"]) for c in changes] == [("removed", "pro")]
    assert changes[0].data["before"] == {"name": "pro", "price": 49}


def test_empty_input_leaves_state_alone(diff_ctx):
    run_ops(plans(pro=49), Diff(namespace="w"), ctx=diff_ctx())
    assert run_ops([], Diff(namespace="w"), ctx=diff_ctx()) == []
    assert run_ops(plans(pro=49), Diff(namespace="w"), ctx=diff_ctx()) == []


def test_only_and_emit_initial(diff_ctx):
    initial = run_ops(plans(basic=9), Diff(emit_initial=True), ctx=diff_ctx())
    assert [c.data["change"] for c in initial] == ["added"]
    changes = run_ops(plans(basic=10, pro=1), Diff(only=["added"]), ctx=diff_ctx())
    assert [c.data["change"] for c in changes] == ["added"]


def test_key_field_ignore_and_reset(diff_ctx):
    events = [ev({"name": "pro", "price": 1, "seen": "mon"}, source_url=PAGE)]
    run_ops(events, Diff(key="name", ignore=["seen"]), ctx=diff_ctx())
    later = [ev({"name": "pro", "price": 1, "seen": "tue"}, source_url=PAGE)]
    assert run_ops(later, Diff(key="name", ignore=["seen"]), ctx=diff_ctx()) == []
    changed = [ev({"name": "pro", "price": 2, "seen": "wed"}, source_url=PAGE)]
    [change] = run_ops(changed, Diff(key="name", ignore=["seen"]), ctx=diff_ctx())
    assert change.key == f"{PAGE}#pro"
    assert run_ops(changed, Diff(key="name", reset=True), ctx=diff_ctx()) == []


def test_error_events_pass_through(diff_ctx):
    error = ev({"error": "boom"}, type="error")
    assert run_ops([error], Diff(), ctx=diff_ctx()) == [error]


def test_interrupted_run_saves_what_it_saw_without_removals(tmp_path):
    ctx = Context(quiet=True, state_dir=tmp_path)
    run_ops(plans(basic=9, pro=49), Diff(namespace="w"), ctx=ctx)

    async def partial():
        stream = build_stream([_List(plans(basic=10, pro=49))], [Diff(namespace="w")], ctx)
        async for _ in stream:
            break
        await stream.aclose()

    asyncio.run(partial())
    state = json.loads((tmp_path / "diff" / "w.json").read_text())
    assert state["items"][f"{PAGE}#basic"]["data"]["price"] == 10
    assert f"{PAGE}#pro" in state["items"]


def test_corrupt_state_suggests_reset(tmp_path):
    (tmp_path / "diff").mkdir()
    (tmp_path / "diff" / "w.json").write_text("{not json")
    with pytest.raises(ConfigError) as info:
        run_ops(plans(pro=1), Diff(namespace="w"), ctx=Context(quiet=True, state_dir=tmp_path))
    assert "--reset" in (info.value.hint or "")


def test_explicit_state_file(tmp_path):
    state = tmp_path / "custom.json"
    run_ops(
        plans(pro=1), Diff(state=str(state)), ctx=Context(quiet=True, state_dir=tmp_path / "unused")
    )
    assert json.loads(state.read_text())["version"] == 1


def test_compare_nested_and_lists():
    old = {"a": {"b": 1}, "offers": [{"price": 1}, {"price": 2}], "tags": ["x"]}
    new = {"a": {"b": 2}, "offers": [{"price": 1}, {"price": 3}], "tags": ["x", "y"], "c": 1}
    assert compare(old, new) == [
        {"path": "a.b", "old": 1, "new": 2},
        {"path": "offers.1.price", "old": 2, "new": 3},
        {"path": "tags", "old": ["x"], "new": ["x", "y"]},
        {"path": "c", "old": None, "new": 1},
    ]


def test_summary_hides_long_values():
    fields = [{"path": "text", "old": "a" * 100, "new": "b"}, {"path": "price", "old": 1, "new": 2}]
    assert summarize("modified", "x", fields) == "text changed; price: 1 → 2"


class _List:
    """Minimal source for the interruption test."""

    name = "list"
    finite = True

    def __init__(self, events):
        self.events = events

    def provenance_step(self):
        return None

    async def collect(self, ctx):
        for event in self.events:
            yield event
