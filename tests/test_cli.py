"""End-to-end: the real `unlimited` command in real pipes (no network)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

DATA = [
    {"title": "Pro", "price": 49, "country": "Thailand"},
    {"title": "Basic", "price": 9, "country": "Laos"},
    {"title": "Team", "price": 199, "country": "Thailand"},
]


@pytest.fixture
def env(tmp_path):
    return {
        **os.environ,
        "UNLIMITEDPIPE_STATE_DIR": str(tmp_path / "state"),
        "UNLIMITEDPIPE_CACHE_DIR": str(tmp_path / "cache"),
    }


@pytest.fixture
def data_file(tmp_path):
    path = tmp_path / "plans.json"
    path.write_text(json.dumps(DATA))
    return path


def sh(command: str, env, cwd=None) -> subprocess.CompletedProcess:
    unlimited = f"{sys.executable} -m unlimitedpipe"
    return subprocess.run(
        command.replace("unlimited ", unlimited + " "),
        shell=True,
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=60,
    )


def jsonl(stdout: str) -> list[dict]:
    return [json.loads(line) for line in stdout.splitlines()]


def test_help_lists_components_by_kind(env):
    result = sh("unlimited --help", env)
    assert result.returncode == 0
    for section in ("Sources:", "Operators:", "Outputs:", "Pipelines:"):
        assert section in result.stdout
    assert "diff" in result.stdout and "web" in result.stdout


def test_pipe_filter_select_json(env, data_file):
    result = sh(
        f"unlimited file {data_file} | unlimited filter 'price > 20' "
        "| unlimited select title price | unlimited json",
        env,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        {"title": "Pro", "price": 49},
        {"title": "Team", "price": 199},
    ]


def test_events_carry_provenance_through_the_pipe(env, data_file):
    result = sh(
        f"unlimited file {data_file} | unlimited filter --field country --eq Thailand "
        "| unlimited sort --by price -r",
        env,
    )
    events = jsonl(result.stdout)
    assert [e["data"]["title"] for e in events] == ["Team", "Pro"]
    assert [step["step"] for step in events[0]["provenance"]] == ["file", "filter", "sort"]


def test_works_with_plain_json_from_other_tools(env):
    result = sh(
        """printf '{"a": 1}\\n{"a": 5}\\n' | unlimited filter 'a > 2' | unlimited jsonl --data""",
        env,
    )
    assert result.stdout.strip() == '{"a":5}'


def test_diff_across_runs(env, tmp_path):
    plans = tmp_path / "plans.json"
    plans.write_text(json.dumps([{"name": "Pro", "price": 49}]))
    baseline = sh(f"unlimited file {plans} | unlimited diff --key name --namespace plans", env)
    assert baseline.stdout == ""
    assert "baseline created for 1 item" in baseline.stderr

    plans.write_text(json.dumps([{"name": "Pro", "price": 59}]))
    changed = sh(f"unlimited file {plans} | unlimited diff --key name --namespace plans", env)
    [change] = jsonl(changed.stdout)
    assert change["type"] == "change"
    assert change["data"]["fields"] == [{"path": "price", "old": 49, "new": 59}]
    assert "1 modified" in changed.stderr


def test_run_yaml_pipeline(env, tmp_path, data_file):
    pipeline = tmp_path / "p.yml"
    pipeline.write_text(f"""
sources:
  - type: file
    path: {data_file.name}
operators:
  - type: grep
    patterns: [thailand]
  - type: limit
    count: 1
outputs:
  - type: jsonl
    path: out/result.jsonl
    data: true
""")
    result = sh(f"unlimited run {pipeline}", env, cwd="/")
    assert result.returncode == 0, result.stderr
    assert jsonl((tmp_path / "out/result.jsonl").read_text()) == [DATA[0]]
    assert sh(f"unlimited run {pipeline} --validate", env).returncode == 0


def test_usage_errors_are_readable(env, data_file):
    result = sh(f"unlimited file {data_file} | unlimited filter 'price >'", env)
    assert result.returncode == 2
    assert "invalid expression" in result.stderr and "^" in result.stderr

    result = sh("unlimited webb https://example.com", env)
    assert result.returncode == 2
    assert "Did you mean `web`?" in result.stderr

    result = sh(f"unlimited file {data_file} | unlimited select", env)
    assert result.returncode == 2 and "at least one field" in result.stderr


def test_invalid_jsonl_input(env):
    result = sh("echo 'not json' | unlimited select a", env)
    assert result.returncode == 1
    assert "stdin line 1 is not valid JSON" in result.stderr


def test_invalid_pipeline_reports_line(env, tmp_path):
    pipeline = tmp_path / "bad.yml"
    pipeline.write_text("sources:\n  - type: web\n    url: x\n    timout: 3\n")
    result = sh(f"unlimited run {pipeline}", env)
    assert result.returncode == 2
    assert "bad.yml:4" in result.stderr and "did you mean 'timeout'?" in result.stderr


def test_limit_closes_the_pipe_quietly(env, data_file):
    result = sh(
        f"unlimited file {data_file} {data_file} {data_file} "
        "| unlimited limit 1 | unlimited select title",
        env,
    )
    assert result.returncode == 0
    assert len(jsonl(result.stdout)) == 1
    assert "Traceback" not in result.stderr and "Fatal" not in result.stderr


def test_missing_file_fails_with_exit_1(env, tmp_path):
    result = sh(f"unlimited file {tmp_path / 'nope.json'}", env)
    assert result.returncode == 1
    assert "cannot read" in result.stderr


def test_python_api_runs_the_same_components(tmp_path, data_file):
    import asyncio

    from unlimitedpipe import Context
    from unlimitedpipe.engine import run_pipeline
    from unlimitedpipe.operators.filter import Filter
    from unlimitedpipe.outputs.json import Json
    from unlimitedpipe.sources.file import File

    out = tmp_path / "out.json"
    asyncio.run(
        run_pipeline(
            [File(path=[str(data_file)])],
            [Filter(expr="price < 10")],
            [Json(path=str(out))],
            Context(quiet=True),
        )
    )
    assert json.loads(Path(out).read_text()) == [DATA[1]]


def test_endless_input_stops_when_the_reader_goes_away(env):
    result = sh("yes '{\"a\": 1}' | unlimited select a | head -3", env)
    assert len(result.stdout.splitlines()) == 3
    assert "Traceback" not in result.stderr


def test_inline_pipeline_runs_in_one_process(env, data_file):
    result = sh(
        f"unlimited run file {data_file} -- filter 'price > 20' -- select title -- json", env
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [{"title": "Pro"}, {"title": "Team"}]


def test_watch_runs_and_stops_after_times(env, data_file):
    result = sh(
        f"unlimited watch --every 30s --times 1 file {data_file} -- limit 1 -- jsonl --data", env
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == DATA[0]
    assert "run 1: 1 event(s)" in result.stderr


def test_watch_refuses_shell_strings_and_tiny_intervals(env):
    result = sh(
        "unlimited watch --every 1h 'unlimited web https://example.com | unlimited diff'", env
    )
    assert result.returncode == 2 and "not through a shell" in result.stderr
    result = sh("unlimited watch --every 5s web https://example.com", env)
    assert result.returncode == 2 and "too frequent" in result.stderr
