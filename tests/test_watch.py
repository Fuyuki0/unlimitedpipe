import json
from pathlib import Path

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


def test_several_pipelines_run_side_by_side_and_write_a_live_catalog(tmp_path, monkeypatch):
    import subprocess

    from unlimitedpipe.watch import WatchMany

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setenv("UNLIMITEDPIPE_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "feeds").mkdir()
    for name in ("quakes", "storms"):
        data = tmp_path / f"{name}.json"
        data.write_text(
            json.dumps(
                [
                    {
                        "title": f"{name} one",
                        "link": f"https://x/{name}/1",
                        "date": "2026-09-28T10:00:00Z",
                    }
                ]
            )
        )
        (tmp_path / "feeds" / f"{name}.yml").write_text(
            f"""name: {name}
sources:
  - {{type: file, path: {data}}}
operators:
  - {{type: map, assign: ['published_at=date']}}
outputs:
  - {{type: feed, path: ../public/{name}.json, title: {name}}}
"""
        )
    paths = [tmp_path / "feeds" / "quakes.yml", tmp_path / "feeds" / "storms.yml"]
    WatchMany(paths, catalog=True, every=60, times=1, quiet=True, sleep=lambda s: None).run()
    document = json.loads((tmp_path / "public" / "feeds.json").read_text())
    assert sorted(f["name"] for f in document["feeds"]) == ["quakes", "storms"]
    assert sorted(i["title"] for i in document["items"]) == ["quakes one", "storms one"]
    assert not (tmp_path / "public" / "archive").exists()  # a live copy keeps no archive


def test_a_file_can_run_more_often_than_the_rest(monkeypatch):
    from types import SimpleNamespace

    import unlimitedpipe.watch as watch

    clock = [1000.0]
    monkeypatch.setattr(watch, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    ran = []

    async def fake_round(self, ready):
        ran.append(sorted(path.name for path, _ in ready))
        self.events = 0
        return {str(path): 0 for path, _ in ready}

    monkeypatch.setattr(watch.WatchMany, "_round", fake_round)
    monkeypatch.setattr(watch.WatchMany, "_pipelines", lambda self: [(p, None) for p in self.paths])
    slow, fast = Path("slow.yml"), Path("fast.yml")

    def sleep(seconds):
        clock[0] += seconds

    watch.WatchMany(
        [slow, fast], intervals={fast: 30}, every=60, jitter=0, times=4, quiet=True, sleep=sleep
    ).run()
    assert ran == [["fast.yml", "slow.yml"], ["fast.yml"], ["fast.yml", "slow.yml"], ["fast.yml"]]


def test_a_file_with_dates_is_loaded_again_each_round(tmp_path, monkeypatch):
    import unlimitedpipe.config as config
    from unlimitedpipe.watch import WatchMany

    dated, plain = tmp_path / "dated.yml", tmp_path / "plain.yml"
    for path, url in ((dated, "https://x/?until=${TODAY}"), (plain, "https://x/")):
        path.write_text(f"name: {path.stem}\nsources:\n  - {{type: web, url: '{url}'}}\n")
    loads = []
    real = config.load_pipeline
    monkeypatch.setattr(config, "load_pipeline", lambda p: loads.append(p.name) or real(p))
    many = WatchMany([dated, plain], every=60, quiet=True)
    many._pipelines()
    many._pipelines()  # neither file changed: only the one with ${TODAY} is loaded again
    assert loads == ["dated.yml", "plain.yml", "dated.yml"]
