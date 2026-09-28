import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from unlimitedpipe.config import load_pipeline
from unlimitedpipe.errors import UsageError
from unlimitedpipe.publish import cron_for, index_page, plan, workflow

PIPELINE = """
name: prices
sources:
  - type: file
    path: data.json
operators:
  - diff
outputs:
  - type: feed
    path: ../public/prices.xml
  - type: json
    path: ../public/data/prices.json
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "remote",
            "add",
            "origin",
            "git@github.com:Ana/price-feeds.git",
        ],
        check=True,
    )
    (tmp_path / "feeds").mkdir()
    (tmp_path / "feeds" / "prices.yml").write_text(PIPELINE)
    return tmp_path


@pytest.mark.parametrize(
    ("every", "pattern"),
    [
        (15 * 60, r"-59/15 \* \* \* \*"),
        (30 * 60, r"-59/30 \* \* \* \*"),
        (3600, r"^\d+ \* \* \* \*$"),
        (6 * 3600, r"^\d+ \*/6 \* \* \*$"),
        (86400, r"^\d+ \d+ \* \* \*$"),
    ],
)
def test_cron_for_intervals(every, pattern):
    import re

    assert re.search(pattern, cron_for(every, "prices"))
    assert cron_for(every, "prices") == cron_for(every, "prices")  # stable per name


@pytest.mark.parametrize("every", [60, 25 * 60, 5 * 3600, 2 * 86400])
def test_cron_rejects_unsupported_intervals(every):
    with pytest.raises(UsageError):
        cron_for(every, "prices")


def test_plan_finds_the_site_folder_and_pages_url(repo):
    path = repo / "feeds" / "prices.yml"
    p = plan([(path, load_pipeline(path))], 3600)
    assert p.pipelines[0].path == Path("feeds/prices.yml")
    assert p.site_dir == Path("public")
    assert p.files == [Path("prices.xml"), Path("data/prices.json")]
    assert p.workflow == Path(".github/workflows/unlimitedpipe-prices.yml")
    assert p.site_url == "https://ana.github.io/price-feeds/"


def test_generated_workflow_is_valid(repo):
    path = repo / "feeds" / "prices.yml"
    p = plan([(path, load_pipeline(path))], 3600)
    document = yaml.safe_load(workflow(p))
    triggers = document.get("on") or document[True]  # PyYAML reads the key `on` as True
    assert triggers["schedule"][0]["cron"] == p.cron
    steps = document["jobs"]["run"]["steps"]
    assert steps[0]["with"]["ref"] == "${{ github.ref }}"  # the latest outputs, not a stale commit
    run_step = next(s for s in steps if s.get("name") == "Run the pipelines")
    assert 'for pipeline in "feeds/prices.yml"' in run_step["run"]
    save_step = next(s for s in steps if s.get("name") == "Save outputs and state")
    assert "git pull --rebase" in save_step["run"]
    assert run_step["env"]["UNLIMITEDPIPE_STATE_DIR"] == ".unlimitedpipe/state"
    assert steps[-1]["with"]["path"] == "public"
    assert document["jobs"]["deploy"]["needs"] == "run"
    assert document["permissions"] == {"contents": "write", "pages": "write", "id-token": "write"}


def test_outputs_must_live_in_their_own_folder(repo):
    path = repo / "feeds" / "prices.yml"
    path.write_text(
        PIPELINE.replace("../public/prices.xml", "prices.xml").replace("../public/data/", "../")
    )
    with pytest.raises(UsageError, match="folder of their own"):
        plan([(path, load_pipeline(path))], 3600)
    path.write_text(PIPELINE.split("outputs:")[0])
    with pytest.raises(UsageError, match="no files to publish"):
        plan([(path, load_pipeline(path))], 3600)


def test_not_a_git_repository(tmp_path):
    path = tmp_path / "p.yml"
    path.write_text(PIPELINE)
    with pytest.raises(UsageError, match="not inside a git repository"):
        plan([(path, load_pipeline(path))], 3600)


def test_index_page_escapes_names(repo):
    path = repo / "feeds" / "prices.yml"
    p = plan([(path, load_pipeline(path))], 3600, name="<prices>")
    p.pipelines[0].description = "Prices & more"
    page = index_page(p, "1h")
    assert "&lt;prices&gt;" in page and "Prices &amp; more" in page and 'href="prices.xml"' in page


def test_publish_command_writes_files_and_refuses_to_overwrite(repo):
    env = {**os.environ, "UNLIMITEDPIPE_STATE_DIR": str(repo / "state")}
    command = [
        sys.executable,
        "-m",
        "unlimitedpipe",
        "publish",
        "feeds/prices.yml",
        "--every",
        "2h",
    ]
    first = subprocess.run(command, cwd=repo, capture_output=True, text=True, env=env)
    assert first.returncode == 0, first.stderr
    assert (repo / ".github/workflows/unlimitedpipe-prices.yml").exists()
    assert (repo / "public/index.html").exists()
    assert "Feed:  https://ana.github.io/price-feeds/prices.xml" in first.stderr
    assert "gh api -X POST repos/Ana/price-feeds/pages -f build_type=workflow" in first.stderr
    second = subprocess.run(command, cwd=repo, capture_output=True, text=True, env=env)
    assert second.returncode == 2 and "already exists" in second.stderr


def test_secrets_referenced_by_the_pipeline_reach_the_workflow(repo):
    path = repo / "feeds" / "prices.yml"
    path.write_text(PIPELINE + "  - type: webhook\n    url: ${DISCORD_HOOK}\n")
    pipeline = load_pipeline_with(path, DISCORD_HOOK="https://discord.com/api/webhooks/1/x")
    p = plan([(path, pipeline)], 3600)
    assert p.secrets == ["DISCORD_HOOK"]
    run_step = next(
        s
        for s in yaml.safe_load(workflow(p))["jobs"]["run"]["steps"]
        if s.get("name") == "Run the pipelines"
    )
    assert run_step["env"]["DISCORD_HOOK"] == "${{ secrets.DISCORD_HOOK }}"


def test_publish_does_not_need_secret_values(repo, monkeypatch):
    monkeypatch.delenv("DISCORD_HOOK", raising=False)
    (repo / "feeds" / "prices.yml").write_text(
        PIPELINE + "  - type: webhook\n    url: ${DISCORD_HOOK}\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "DISCORD_HOOK"}
    env["UNLIMITEDPIPE_STATE_DIR"] = str(repo / "state")
    result = subprocess.run(
        [sys.executable, "-m", "unlimitedpipe", "publish", "feeds/prices.yml"],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    text = (repo / ".github/workflows/unlimitedpipe-prices.yml").read_text()
    assert "${{ secrets.DISCORD_HOOK }}" in text and "secret.invalid" not in text


def load_pipeline_with(path, **env):
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        return load_pipeline(path)
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_catalog_publishes_several_pipelines_with_one_workflow(repo):
    second = repo / "feeds" / "news.yml"
    second.write_text(
        "name: news\ndescription: Headlines\nsources: [{type: file, path: data.json}]\n"
        "outputs: [{type: feed, path: ../public/news.xml}]\n"
    )
    first = repo / "feeds" / "prices.yml"
    items = [(first, load_pipeline(first)), (second, load_pipeline(second))]
    p = plan(items, 3600)
    assert p.name == "feeds" and p.workflow == Path(".github/workflows/unlimitedpipe-feeds.yml")
    assert [i.name for i in p.pipelines] == ["prices", "news"]
    assert p.files == [Path("prices.xml"), Path("data/prices.json"), Path("news.xml")]
    run = yaml.safe_load(workflow(p))["jobs"]["run"]["steps"][3]["run"]
    assert 'for pipeline in "feeds/prices.yml" "feeds/news.yml"' in run
    page = index_page(p, "1h")
    assert page.count("<section id=") == 2 and "<p>Headlines</p>" in page


def test_express_lane_runs_its_pipelines_every_time_and_the_rest_when_due(repo):
    second = repo / "feeds" / "quakes.yml"
    second.write_text(
        "name: quakes\nsources: [{type: file, path: data.json}]\n"
        "outputs: [{type: feed, path: ../public/quakes.xml}]\n"
    )
    first = repo / "feeds" / "prices.yml"
    items = [(first, load_pipeline(first)), (second, load_pipeline(second))]
    p = plan(items, 3600, express=["quakes"], express_every=15 * 60)
    assert p.express == ["feeds/quakes.yml"]
    assert p.cron.endswith("-59/15 * * * *")
    run = yaml.safe_load(workflow(p))["jobs"]["run"]["steps"][3]["run"]
    assert 'for pipeline in "feeds/quakes.yml"; do run "$pipeline"; done' in run
    assert 'for pipeline in "feeds/prices.yml"; do run "$pipeline"; done' in run
    assert '[ "$age" -ge 3300 ]' in run and "last-full-run" in run
    assert 'lane="${{ inputs.lane }}"' in run and '[ "$lane" != express ]' in run
    lane = yaml.safe_load(workflow(p))[True]["workflow_dispatch"]["inputs"]["lane"]
    assert lane["options"] == ["all", "express"] and lane["default"] == "all"
    assert "express lane (quakes) every 15m" in index_page(p, "1h")
    with pytest.raises(UsageError, match="names no pipeline"):
        plan(items, 3600, express=["volcanoes"])
    with pytest.raises(UsageError, match="shorter than --every"):
        plan(items, 3600, express=["quakes"], express_every=3600)


def test_only_runs_that_run_a_browser_pipeline_install_the_browser(repo):
    quakes = repo / "feeds" / "quakes.yml"
    quakes.write_text(
        "name: quakes\nsources: [{type: file, path: data.json}]\n"
        "outputs: [{type: feed, path: ../public/quakes.xml}]\n"
    )
    bank = repo / "feeds" / "bank.yml"
    bank.write_text(
        "name: bank\nsources: [{type: web, url: 'https://bank.example/news', browser: true}]\n"
        "outputs: [{type: feed, path: ../public/bank.xml}]\n"
    )
    items = [(quakes, load_pipeline(quakes)), (bank, load_pipeline(bank))]
    later = workflow(plan(items, 3600, express=["quakes"], express_every=15 * 60))
    steps = yaml.safe_load(later)["jobs"]["run"]["steps"]
    assert not any("playwright" in str(step.get("run", "")) for step in steps[:3])
    lanes = steps[3]["run"]
    assert lanes.index("playwright install") > lanes.index('[ "$age" -ge 3300 ]')
    first = yaml.safe_load(workflow(plan(items, 3600, express=["bank"], express_every=900)))
    assert "playwright install" in first["jobs"]["run"]["steps"][3]["run"]  # a step of its own
