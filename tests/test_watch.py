import json

import pytest

from unlimitedpipe.commands import STAGE_SEPARATOR, parse_inline, split_stages
from unlimitedpipe.config import Pipeline, load_pipeline
from unlimitedpipe.errors import UnlimitedError, UsageError
from unlimitedpipe.outputs.jsonl import Jsonl
from unlimitedpipe.sources.file import File
from unlimitedpipe.watch import Watch, format_duration, parse_duration


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("30s", 30), ("5m", 300), ("1h", 3600), ("1h30m", 5400), ("1d", 86400), ("1.5h", 5400)],
)
def test_parse_duration(text, seconds):
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "5", "5x", "soon", "1h 2", "m5"])
def test_parse_duration_rejects(text):
    with pytest.raises(UsageError, match="invalid duration"):
        parse_duration(text)


def test_format_duration():
    assert [format_duration(s) for s in (45, 300, 7200, 172800)] == ["45s", "5m", "2h", "2d"]


def test_split_stages_accepts_both_separators():
    tokens = ["web", "x", STAGE_SEPARATOR, "select", "a", "--", "json"]
    assert split_stages(tokens) == [["web", "x"], ["select", "a"], ["json"]]
    with pytest.raises(UsageError, match="empty stage"):
        split_stages(["web", "x", "--", "--", "json"])


def test_parse_inline_builds_components_like_the_cli():
    sources, operators, outputs = parse_inline(
        [
            "web",
            "https://a",
            "https://b",
            "--timeout",
            "5",
            "--",
            "filter",
            "price > 1",
            "--",
            "json",
            "out.json",
        ]
    )
    assert sources[0].url == ["https://a", "https://b"] and sources[0].timeout == 5.0
    assert operators[0].expr == "price > 1"
    assert outputs[0].path == "out.json"


@pytest.mark.parametrize(
    ("tokens", "message"),
    [
        (["select", "a"], "starts with a source"),
        (["web", "x", "--", "json", "--", "select", "a"], "comes after an output"),
        (["web", "x", "--", "sellect", "a"], "unknown pipeline stage"),
        (["web x | unlimited diff"], "not through a shell"),
        (["web", "x", "--", "filter", "a >"], "invalid expression"),
    ],
)
def test_parse_inline_errors(tokens, message):
    with pytest.raises(UnlimitedError, match=message):
        parse_inline(tokens)


def file_pipeline(data_path, out_path) -> Pipeline:
    return Pipeline(
        name="t",
        sources=[File(path=[str(data_path)])],
        operators=[],
        outputs=[Jsonl(path=str(out_path), append=True, data=True)],
    )


def test_watch_runs_on_schedule(tmp_path):
    data, out = tmp_path / "d.json", tmp_path / "out.jsonl"
    data.write_text(json.dumps([{"n": 1}]))
    sleeps = []
    watch = Watch(
        lambda: file_pipeline(data, out),
        every=60,
        jitter=0,
        times=3,
        quiet=True,
        sleep=sleeps.append,
    )
    watch.run()
    assert watch.runs == 3
    assert len(sleeps) == 2 and all(0 < s <= 60 for s in sleeps)
    assert out.read_text().splitlines() == ['{"n":1}'] * 3


def test_a_failed_run_does_not_stop_the_watch(tmp_path, capsys):
    data, out = tmp_path / "d.json", tmp_path / "out.jsonl"

    def next_round(_seconds):
        data.write_text(json.dumps([{"n": 2}]))  # the file appears before the second run

    watch = Watch(lambda: file_pipeline(data, out), every=60, times=2, quiet=True, sleep=next_round)
    watch.run()
    assert watch.runs == 2
    assert out.read_text().splitlines() == ['{"n":2}']
    assert "cannot read" in capsys.readouterr().err


def test_pipeline_file_is_reloaded_and_bad_edits_are_ignored(tmp_path, capsys):
    data, out = tmp_path / "d.json", tmp_path / "out.jsonl"
    data.write_text(json.dumps([{"n": 1, "keep": "yes"}, {"n": 2, "keep": "no"}]))
    pipeline_file = tmp_path / "p.yml"

    def write(expr: str) -> None:
        pipeline_file.write_text(
            f"sources: [{{type: file, path: d.json}}]\n"
            f"operators: [{{type: filter, expr: '{expr}'}}]\n"
            f"outputs: [{{type: jsonl, path: out.jsonl, append: true, data: true}}]\n"
        )

    write('keep == "yes"')
    edits = iter(['keep == "no"', "keep ==", 'keep == "yes"'])

    def edit(_seconds):
        import os

        write(next(edits))
        stat = pipeline_file.stat()
        os.utime(pipeline_file, (stat.st_atime, stat.st_mtime + 10))

    watch = Watch(
        lambda: load_pipeline(pipeline_file),
        every=60,
        times=4,
        reload_path=pipeline_file,
        sleep=edit,
    )
    watch.run()
    rows = [json.loads(line)["n"] for line in out.read_text().splitlines()]
    assert rows == [1, 2, 2, 1]  # the invalid third edit kept the second version running
    assert "still running the previous version" in capsys.readouterr().err
