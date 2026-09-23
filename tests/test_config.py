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
