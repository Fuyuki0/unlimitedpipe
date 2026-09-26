import json
import subprocess
import sys
from pathlib import Path

import pytest

from unlimitedpipe.archive import append
from unlimitedpipe.onboard import Setup, model_for, skill_text, this_command
from unlimitedpipe.publish import CATALOG_SCHEMA


@pytest.mark.parametrize(
    ("memory", "model"),
    [
        (None, "qwen2.5:0.5b"),
        (1.9, "qwen2.5:0.5b"),
        (6, "qwen2.5:1.5b"),
        (12, "qwen2.5:3b"),
        (32, "qwen2.5:7b"),
    ],
)
def test_the_model_fits_the_machine(memory, model):
    assert model_for(memory) == model


def test_the_skill_ships_with_the_package():
    text = skill_text()
    assert text.startswith("---\nname: unlimitedpipe")
    assert text == (Path(__file__).parents[1] / "skills/unlimitedpipe/SKILL.md").read_text()


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("UNLIMITEDPIPE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("UNLIMITEDPIPE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("UNLIMITEDPIPE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return home


def catalog(tmp_path: Path) -> str:
    site = tmp_path / "site"
    site.mkdir()
    items = [
        {
            "feed": "quakes",
            "title": "M7.0 Loyalty Islands",
            "link": "https://q/1",
            "date": "2026-09-25T21:44:05Z",
        }
    ]
    (site / "feeds.json").write_text(
        json.dumps(
            {"schema": CATALOG_SCHEMA, "archive": "archive/index.json", "feeds": [], "items": items}
        )
    )
    append(site, items, "2026-09-26T00:00:00Z")
    return str(site)


def lines(setup_kwargs) -> list[str]:
    out: list[str] = []
    Setup(echo=out.append, **setup_kwargs)()
    return out


def test_without_a_terminal_it_only_checks(home, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")  # no claude
    out = lines({"yes": False, "skip": set(), "catalog": catalog(tmp_path), "interactive": False})
    assert "only checking" in out[0]
    assert not (tmp_path / "data").exists()
    assert (
        out[-1]
        .strip()
        .endswith("Skipped: browser, ai, offline (run unlimited setup again any time).")
    )


def test_yes_sets_up_claude_code_and_an_offline_copy(home, tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "claude.log"
    fake = bin_dir / "claude"
    fake.write_text(
        f'#!/bin/sh\nif grep -q "mcp add" {log} 2>/dev/null; then echo "unlimitedpipe: mcp"; '
        f'else echo "No MCP servers configured"; fi\necho "$@" >> {log}\n'
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    catalog_path = catalog(tmp_path)
    out = lines({"yes": True, "skip": {"browser", "ai"}, "catalog": catalog_path})
    calls = log.read_text().splitlines()
    assert calls[0] == "mcp list"
    assert calls[1] == f"mcp add --scope user unlimitedpipe -- {this_command()} mcp"
    assert Path(this_command()).parent == Path(sys.executable).parent  # the running copy
    assert (home / ".claude/skills/unlimitedpipe/SKILL.md").read_text() == skill_text()
    copy = tmp_path / "data" / "catalog"
    assert (copy / "feeds.json").is_file() and (copy / "archive" / "2026-09.jsonl").is_file()
    assert out[-1].strip().startswith("Set up: agents, offline. Skipped: browser, ai")
    again = lines({"yes": True, "skip": {"browser", "ai", "offline"}, "catalog": catalog_path})
    assert any("Claude Code has the unlimitedpipe tools and skill" in line for line in again)
    assert sum(call.startswith("mcp add") for call in log.read_text().splitlines()) == 1


def test_the_browser_step_installs_playwright_and_chromium(home, tmp_path, monkeypatch):
    import unlimitedpipe.onboard as onboard

    monkeypatch.setattr(onboard, "pip_install", lambda *r: ["pip", "install", *r])
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    setup = Setup(yes=True, skip=set(), catalog=catalog(tmp_path), echo=lambda _: None, run=run)
    setup.browser()
    assert ["pip", "install", "playwright>=1.45"] in commands
    assert [sys.executable, "-m", "playwright", "install", "chromium"] in commands
    assert setup.done == ["browser"]


def test_skip_takes_steps_with_commas(home, monkeypatch):
    from click.testing import CliRunner

    import unlimitedpipe.onboard as onboard
    from unlimitedpipe.cli import cli

    seen = []
    monkeypatch.setattr(onboard.Setup, "__call__", lambda self: seen.append(self.skip))
    result = CliRunner().invoke(
        cli, ["setup", "--yes", "--skip", "browser,ai", "--skip", "offline"]
    )
    assert result.exit_code == 0 and seen == [{"browser", "ai", "offline"}]
    result = CliRunner().invoke(cli, ["setup", "--skip", "browsers"])
    assert result.exit_code != 0 and "unknown step 'browsers'" in str(result.exception)
