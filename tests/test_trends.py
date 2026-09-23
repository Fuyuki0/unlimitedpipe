import asyncio

import pytest

from tests.conftest import ListSource, ev, run_ops
from unlimitedpipe import Context, Source
from unlimitedpipe.engine import build_stream
from unlimitedpipe.errors import ConfigError, UsageError
from unlimitedpipe.operators.count import Count
from unlimitedpipe.operators.extract import Extract
from unlimitedpipe.operators.trend import Trend


def at(minute: int, **data) -> object:
    hour, minute = divmod(minute, 60)
    return ev(data, timestamp=f"2026-09-23T{10 + hour:02d}:{minute:02d}:00Z")


def test_extract_presets():
    event = ev(
        {
            "title": "Big #AI news: $tsla and $NVDA up, see https://x.ai/p#frag",
            "summary": "#ai again",
        }
    )
    [out] = run_ops(
        [event], Extract(what="hashtags"), Extract(what="cashtags"), Extract(what="domains")
    )
    assert out.data["hashtags"] == ["#ai"]
    assert out.data["cashtags"] == ["$TSLA", "$NVDA"]
    assert out.data["domains"] == ["x.ai"]


def test_extract_words_skips_stopwords_and_links_but_keeps_short_terms():
    event = ev({"title": "The AI model for C++ and ML https://example.com/page is out"})
    [out] = run_ops([event], Extract(what="words", field=["title"]))
    assert out.data["words"] == ["ai", "model", "c++", "ml"]


def test_extract_regex_into_field():
    event = ev({"text": "Fixes CVE-2026-1234 and CVE-2026-99"})
    [out] = run_ops([event], Extract(what=r"CVE-\d{4}-\d+", into="cves"))
    assert out.data["cves"] == ["CVE-2026-1234", "CVE-2026-99"]
    with pytest.raises(ValueError, match="invalid regular expression"):
        Extract(what="(")


def test_count_whole_stream_counts_list_elements():
    events = [ev({"tags": ["#a", "#b"]}), ev({"tags": ["#a"]}), ev({"tags": []}), ev({})]
    out = run_ops(events, Count(by="tags"))
    assert [(e.data["value"], e.data["count"]) for e in out] == [("#a", 2), ("#b", 1)]
    assert out[0].data["events"] == 4 and out[0].type == "count"
    assert run_ops(events, Count(by="tags", top=1))[0].data["value"] == "#a"


def test_count_windows_follow_event_time():
    events = [at(5, t="x"), at(50, t="x"), at(20, t="y"), at(65, t="x"), at(70, t="z")]
    out = run_ops(events, Count(by="t", every="1h"))
    windows = [(e.data["window_start"][11:16], e.data["value"], e.data["count"]) for e in out]
    assert windows == [("10:00", "x", 2), ("10:00", "y", 1), ("11:00", "x", 1), ("11:00", "z", 1)]


def test_windowed_count_can_follow_an_endless_stream_and_whole_count_cannot():
    class Endless(Source):
        name = "endless"
        finite = False

        async def collect(self, ctx):
            while True:
                yield ev()

    build_stream([Endless()], [Count(by="t", every="10m")], Context(quiet=True))
    with pytest.raises(ConfigError, match="never ends"):
        build_stream([Endless()], [Count(by="t")], Context(quiet=True))
    with pytest.raises(UsageError):
        Count(by="t", every="soon")


def spike_events():
    quiet = [at(m, t="rust") for m in (1, 2, 61, 62, 121, 122)] + [
        at(m, t="ai") for m in (3, 63, 123)
    ]
    burst = [at(181 + i, t="ai") for i in range(9)] + [at(185, t="rust"), at(186, t="rust")]
    burst += [at(190 + i, t="mcp") for i in range(4)]
    return quiet + burst


def test_trend_reports_spikes_against_earlier_windows(tmp_path):
    ctx = Context(quiet=True, state_dir=tmp_path)
    out = run_ops(spike_events(), Count(by="t", every="1h"), Trend(namespace="t"), ctx=ctx)
    assert [(e.data["value"], e.data["count"], e.data["baseline"]) for e in out] == [
        ("ai", 9, 1.0),
        ("mcp", 4, 0.0),
    ]
    assert out[0].data["change_pct"] == 800.0
    assert out[0].data["title"] == "ai +800%: 9 in the window, usually 1"
    assert out[1].data["title"].startswith("mcp new")
    assert (tmp_path / "trend" / "t.json").exists()


def test_trend_history_carries_across_runs(tmp_path):
    ctx = lambda: Context(quiet=True, state_dir=tmp_path)  # noqa: E731
    events = spike_events()
    first_hours = [e for e in events if e.timestamp < "2026-09-23T13:00:00Z"]
    last_hour = [e for e in events if e.timestamp >= "2026-09-23T13:00:00Z"]
    assert run_ops(first_hours, Count(by="t", every="1h"), Trend(namespace="t"), ctx=ctx()) == []
    out = run_ops(last_hour, Count(by="t", every="1h"), Trend(namespace="t"), ctx=ctx())
    assert [e.data["value"] for e in out] == ["ai", "mcp"]


def test_trend_thresholds(tmp_path):
    ctx = Context(quiet=True, state_dir=tmp_path)
    out = run_ops(
        spike_events(), Count(by="t", every="1h"), Trend(namespace="x", min_count=5), ctx=ctx
    )
    assert [e.data["value"] for e in out] == ["ai"]


def test_trend_in_one_process_pipeline(tmp_path):
    async def go():
        stream = build_stream(
            [ListSource(spike_events())],
            [Count(by="t", every="1h"), Trend(namespace="p")],
            Context(quiet=True, state_dir=tmp_path),
        )
        return [e async for e in stream]

    out = asyncio.run(go())
    assert [step["step"] for step in out[0].provenance] == ["count", "trend"]


def test_count_handles_newest_first_feeds():
    events = [at(5, t="x"), at(50, t="x"), at(20, t="y"), at(65, t="x"), at(70, t="z")]
    forward = run_ops(list(events), Count(by="t", every="1h"))
    backward = run_ops(list(reversed(events)), Count(by="t", every="1h"))
    assert sorted((e.key, e.data["count"]) for e in forward) == sorted(
        (e.key, e.data["count"]) for e in backward
    )


def test_live_stream_windows_close_as_they_go(monkeypatch):
    import unlimitedpipe.operators.count as count_module

    clock = iter(range(0, 10_000, 100))  # each event arrives 100 s of real time later
    monkeypatch.setattr(count_module.time, "monotonic", lambda: next(clock))
    emitted_before_end = []

    async def go():
        stream = build_stream(
            [ListSource([at(5, t="x"), at(50, t="x"), at(65, t="y"), at(10, t="late")])],
            [Count(by="t", every="1h")],
            Context(quiet=True),
        )
        return [e async for e in stream]

    out = asyncio.run(go())
    emitted_before_end = [e.data["value"] for e in out]
    assert emitted_before_end == ["x", "y"]  # the 10:00 window closed before "late" arrived
