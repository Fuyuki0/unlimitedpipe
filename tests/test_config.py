from pathlib import Path

import pytest

from unlimitedpipe.config import load_pipeline
from unlimitedpipe.errors import ConfigError


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "watch.yml"
    path.write_text(text)
    return path


def test_valid_pipeline(tmp_path):
    pipeline = load_pipeline(
        write(
            tmp_path,
            """
name: competitor-watch
sources:
  - type: web
    url: https://example.com/pricing
    each: .plan
    field: [name=.name, price=.price]
operators:
  - type: filter
    expr: price > 10
  - diff
  - type: diff
    key: name
outputs:
  - type: feed
    path: out/changes.xml
settings:
  errors_as_events: true
""",
        )
    )
    assert pipeline.name == "competitor-watch"
    web = pipeline.sources[0]
    assert web.url == ["https://example.com/pricing"]  # a single value becomes a list
    assert [op.name for op in pipeline.operators] == ["filter", "diff", "diff"]
    assert pipeline.operators[1].namespace == "competitor-watch"
    assert pipeline.operators[2].namespace == "competitor-watch-2"
    assert pipeline.outputs[0].path == str((tmp_path / "out/changes.xml").resolve())
    assert pipeline.errors_as_events is True


def test_name_defaults_to_file_stem(tmp_path):
    assert (
        load_pipeline(write(tmp_path, "sources: [{type: rss, url: https://e.com/f}]")).name
        == "watch"
    )


@pytest.mark.parametrize(
    ("text", "message", "hint"),
    [
        (
            "sources:\n  - type: web\n    url: x\nopertors: []\n",
            "watch.yml:4: unknown key 'opertors'",
            "did you mean 'operators'?",
        ),
        (
            "sources:\n  - type: webb\n    url: x\n",
            "watch.yml:2: sources[0]: unknown source type 'webb'",
            "did you mean 'web'?",
        ),
        (
            "sources:\n  - type: diff\n",
            "watch.yml:2: sources[0] (diff): 'diff' is an operator, not a source",
            None,
        ),
        (
            "sources:\n  - type: web\n    url: x\n    timeout: soon\n",
            "watch.yml:4: sources[0] (web): option 'timeout' of web: expected a number",
            None,
        ),
        (
            "sources:\n  - type: web\n    urls: x\n",
            "watch.yml:3: sources[0] (web): unknown option 'urls' for web",
            "did you mean 'url'?",
        ),
        ("sources:\n  - type: file\n", "watch.yml:2: sources[0] (file): file needs a path", None),
        (
            "sources:\n  - type: rss\n    url: x\noperators:\n  - type: filter\n    expr: 'a >'\n",
            "watch.yml:5: operators[0] (filter): invalid expression",
            None,
        ),
        ("operators: []\n", "a pipeline needs at least one source", None),
        ("sources: [\n", "watch.yml:2: invalid YAML", None),
        ("- just a list\n", "a pipeline must be a mapping", None),
    ],
)
def test_errors_point_at_the_line(tmp_path, text, message, hint):
    with pytest.raises(ConfigError) as info:
        load_pipeline(write(tmp_path, text))
    assert message in info.value.message
    if hint:
        assert info.value.hint == hint


def test_missing_file():
    with pytest.raises(ConfigError, match="cannot read"):
        load_pipeline(Path("/nonexistent/pipeline.yml"))


def test_date_variables_fill_in_today_and_days_ago(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from unlimitedpipe.config import env_references

    monkeypatch.delenv("TODAY", raising=False)
    text = """
name: recent
sources:
  - type: web
    url: https://example.com/search?from=${DAYS_AGO_30}&to=${TODAY}
"""
    pipeline = load_pipeline(write(tmp_path, text))
    today = datetime.now(UTC).date()
    assert pipeline.sources[0].url == [
        f"https://example.com/search?from={today - timedelta(days=30)}&to={today}"
    ]
    assert env_references(text) == []  # dates are not secrets to set


def test_a_backfill_window_sets_the_dates(tmp_path):
    from datetime import date

    from unlimitedpipe.config import WINDOW

    text = """
name: recent
sources:
  - type: web
    url: https://example.com/${YEAR}?from=${DAYS_AGO_30}&to=${TODAY}&before=${TOMORROW}
"""
    token = WINDOW.set((date(2019, 3, 1), date(2019, 3, 31)))
    try:
        pipeline = load_pipeline(write(tmp_path, text))
    finally:
        WINDOW.reset(token)
    assert pipeline.sources[0].url == [
        "https://example.com/2019?from=2019-03-01&to=2019-03-31&before=2019-04-01"
    ]


def test_moments_for_older_than_checks():
    import re
    from datetime import UTC, datetime, timedelta

    from unlimitedpipe.config import _date, uses_time

    moment = _date("HOURS_AGO_2")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", moment)
    then = datetime.strptime(moment, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert abs((datetime.now(UTC) - then) - timedelta(hours=2)) < timedelta(minutes=1)
    assert _date("MINUTES_AGO_30") > moment
    assert uses_time("url: https://x?since=${DAYS_AGO_7}") and uses_time("${MINUTES_AGO_5}")
    assert not uses_time("header: ${NTFY_TOKEN}")


def test_a_variable_can_have_a_fallback(monkeypatch):
    from unlimitedpipe.config import _interpolate, env_references

    monkeypatch.delenv("QUAKE_LISTEN", raising=False)
    assert _interpolate("${QUAKE_LISTEN:-0}") == "0"
    monkeypatch.setenv("QUAKE_LISTEN", "25")
    assert _interpolate("${QUAKE_LISTEN:-0}") == "25"
    assert env_references("${A} ${B:-1}") == ["A"]  # B need not be set
