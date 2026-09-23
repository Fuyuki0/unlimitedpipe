"""Every example pipeline must stay valid (checked offline; the examples fetch live sites)."""

from pathlib import Path

import pytest

from unlimitedpipe.config import env_references, load_pipeline

EXAMPLES = sorted((Path(__file__).parent.parent / "examples").glob("*/pipeline.yml"))


def test_examples_exist():
    assert len(EXAMPLES) >= 6


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.parent.name)
def test_example_pipeline_is_valid(path, monkeypatch):
    for name in env_references(path.read_text()):
        monkeypatch.setenv(name, "https://example.com/placeholder")
    pipeline = load_pipeline(path)
    assert pipeline.sources and pipeline.outputs
    assert (path.parent / "README.md").exists()
