"""`unlimited setup`: everything UnlimitedPipe can use, set up in one command.

Each step says what it will do and asks first (``--yes`` accepts them all); steps that are
already done are skipped, so running it again is safe. Nothing is installed system-wide without
asking, and keys are never written anywhere.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import click

STEPS = ("browser", "ai", "agents", "offline")
SKILL_TARGET = Path("~/.claude/skills/unlimitedpipe/SKILL.md")
OFFLINE_DIR = Path("~/unlimited/catalog")


def memory_gb() -> float | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3
    except (ValueError, OSError, AttributeError):
        return None


def model_for(memory: float | None) -> str:
    """The best small model that fits the machine: it has to run next to everything else."""
    if memory is None or memory < 4:
        return "qwen2.5:0.5b"
    if memory < 8:
        return "qwen2.5:1.5b"
    if memory < 16:
        return "qwen2.5:3b"
    return "qwen2.5:7b"


def skill_text() -> str:
    """The agent skill: packaged with the wheel, or read from the repository in a checkout."""
    from importlib.resources import files

    packaged = files("unlimitedpipe").joinpath("SKILL.md")
    if packaged.is_file():
        return packaged.read_text(encoding="utf-8")
    return (Path(__file__).parents[2] / "skills" / "unlimitedpipe" / "SKILL.md").read_text(
        encoding="utf-8"
    )


def pip_install(*requirements: str) -> list[str] | None:
    """The command that installs packages next to this UnlimitedPipe, whatever installed it."""
    probe = subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True)
    if probe.returncode == 0:
        return [sys.executable, "-m", "pip", "install", "--quiet", *requirements]
    if uv := shutil.which("uv"):  # uv tool environments have no pip
        return [uv, "pip", "install", "--quiet", "--python", sys.executable, *requirements]
    return None


def this_command() -> str:
    """The `unlimited` that is running now: the one just installed, even if an older one comes
    first on the PATH."""
    beside = Path(sys.executable).parent / (
        "unlimited.exe" if sys.platform == "win32" else "unlimited"
    )
    return str(beside) if beside.is_file() else shutil.which("unlimited") or "unlimited"


class Setup:
    def __init__(
        self,
        *,
        yes: bool,
        skip: set[str],
        catalog: str | None,
        echo: Callable[[str], None] = lambda text: click.echo(text, err=True),
        confirm: Callable[[str], bool] | None = None,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        interactive: bool | None = None,
    ) -> None:
        self.yes = yes
        self.skip = skip
        self.catalog = catalog
        self.echo = echo
        self._confirm = confirm or (lambda question: click.confirm(question, default=True))
        self.run = run
        self.interactive = sys.stdin.isatty() if interactive is None else interactive
        self.done: list[str] = []
        self.skipped: list[str] = []

    def ask(self, question: str) -> bool:
        if self.yes:
            return True
        if not self.interactive:
            return False  # no one to ask: only --yes installs anything
        return self._confirm(question)

    def title(self, number: int, text: str) -> None:
        self.echo(click.style(f"\n{number}/6  {text}", bold=True))

    def ok(self, text: str) -> None:
        self.echo(f"  {click.style('✓', fg='green')} {text}")

    def note(self, text: str) -> None:
        self.echo(f"  {click.style('·', fg='yellow')} {text}")

    def sh(self, command: list[str], *, quiet: bool = False) -> bool:
        self.echo(click.style(f"  $ {' '.join(command)}", dim=True))
        result = self.run(command, capture_output=quiet)
        return result.returncode == 0

    # -- steps ---------------------------------------------------------------------------

    def check(self) -> None:
        from unlimitedpipe.doctor import run_checks

        self.title(1, "Checking this machine")
        for check in run_checks(self.catalog):
            if check.area in ("core", "network"):
                (self.ok if check.ok else self.note)(f"{check.name}: {check.detail}")

    def browser(self) -> None:
        self.title(2, "Browser, for pages that need JavaScript")
        from unlimitedpipe.doctor import run_checks

        state = next(c for c in run_checks(self.catalog) if c.name.startswith("browser"))
        if state.ok:
            return self.ok("Playwright and Chromium are installed")
        if "browser" in self.skip or not self.ask(
            "Install Playwright and Chromium (about 150 MB)?"
        ):
            self.skipped.append("browser")
            return self.note(
                'later: pip install "unlimitedpipe[browser]" && playwright install chromium'
            )
        command = pip_install("playwright>=1.45")
        if command is None:
            self.skipped.append("browser")
            return self.note(
                "no pip or uv found next to UnlimitedPipe; install playwright yourself"
            )
        if self.sh(command) and self.sh(
            [sys.executable, "-m", "playwright", "install", "chromium"]
        ):
            self.done.append("browser")
            return self.ok("browser ready: unlimited web URL --browser")
        self.note(
            "Chromium needs system libraries on this Linux: "
            "sudo python -m playwright install-deps chromium"
        )

    def ai(self) -> None:
        self.title(3, "Local AI, for unlimited ask")
        import httpx

        from unlimitedpipe.sources.ask import OLLAMA

        host = os.environ.get("OLLAMA_HOST", OLLAMA)
        host = host if host.startswith("http") else f"http://{host}"
        model = model_for(memory_gb())
        try:
            models = [m["name"] for m in httpx.get(f"{host}/api/tags", timeout=3).json()["models"]]
        except (httpx.HTTPError, ValueError, KeyError):
            models = None
        if models is None:
            if os.environ.get("ANTHROPIC_API_KEY"):
                return self.ok("ANTHROPIC_API_KEY is set: ask will use Claude")
            if (
                "ai" in self.skip
                or shutil.which("curl") is None
                or sys.platform == "win32"
                or not self.ask(
                    "Ollama is not running. Install it with its official installer (needs sudo)?"
                )
            ):
                self.skipped.append("ai")
                return self.note(
                    "later: install Ollama from https://ollama.com, or set ANTHROPIC_API_KEY"
                )
            if not self.sh(["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"]):
                self.skipped.append("ai")
                return self.note("the Ollama installer failed; see https://ollama.com/download")
            models = []
        if model in models or f"{model}:latest" in models:
            return self.ok(f"{model} is ready (fits {memory_gb() or 0:.0f} GB of memory)")
        if models and "ai" in self.skip:
            return self.ok(f"Ollama has {', '.join(models)}")
        size = {"qwen2.5:0.5b": "0.4", "qwen2.5:1.5b": "1", "qwen2.5:3b": "2", "qwen2.5:7b": "4.7"}
        if "ai" in self.skip or not self.ask(
            f"Download {model} (about {size.get(model, '?')} GB), the best fit for this machine?"
        ):
            self.skipped.append("ai")
            return self.note(f"later: ollama pull {model}")
        if self.sh(["ollama", "pull", model]):
            self.done.append("ai")
            return self.ok('ask ready: unlimited ask "what is happening in Bangkok?"')
        self.note(f"the download failed; try: ollama pull {model}")

    def agents(self) -> None:
        self.title(4, "AI agents (Claude Code)")
        claude = shutil.which("claude")
        target = SKILL_TARGET.expanduser()
        if claude is None:
            self.note(
                "Claude Code not found. Other agents: add `unlimited mcp` as an MCP server, "
                "or tell them: Install UnlimitedPipe: "
                "https://raw.githubusercontent.com/Fuyuki0/unlimitedpipe/main/docs/install-for-agents.md"
            )
            return
        listed = self.run([claude, "mcp", "list"], capture_output=True, text=True)
        has_mcp = "unlimitedpipe" in (listed.stdout or "")
        has_skill = target.is_file() and target.read_text(encoding="utf-8") == skill_text()
        if has_mcp and has_skill:
            return self.ok("Claude Code has the unlimitedpipe tools and skill")
        if "agents" in self.skip or not self.ask(
            "Give Claude Code the UnlimitedPipe tools (MCP) and skill?"
        ):
            self.skipped.append("agents")
            return self.note("later: claude mcp add unlimitedpipe -- unlimited mcp")
        if not has_mcp:
            unlimited = this_command()
            self.sh(
                [claude, "mcp", "add", "--scope", "user", "unlimitedpipe", "--", unlimited, "mcp"]
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(skill_text(), encoding="utf-8")
        self.done.append("agents")
        self.ok(f'skill saved to {target}; ask Claude: "any big insider trades this week?"')

    def offline(self) -> None:
        self.title(5, "Offline copy of the feed catalog")
        import asyncio
        from datetime import UTC, datetime, timedelta

        from unlimitedpipe.context import Context
        from unlimitedpipe.offline import mirror

        folder = OFFLINE_DIR.expanduser()
        if "offline" in self.skip or not self.ask(
            f"Download the catalog and 3 months of its archive into {folder} (a few MB)?"
        ):
            self.skipped.append("offline")
            return self.note(f"later: unlimited mirror {folder}")
        since = (datetime.now(UTC) - timedelta(days=90)).strftime("%Y-%m")

        async def go() -> dict:
            ctx = Context(quiet=True)
            try:
                return await mirror(ctx, self.catalog, folder, since=since, feeds=False)
            finally:
                await ctx.aclose()

        try:
            copied = asyncio.run(go())
        except Exception as exc:  # a network problem must not end the setup
            self.skipped.append("offline")
            return self.note(f"could not download it now ({exc}); later: unlimited mirror {folder}")
        self.done.append("offline")
        self.ok(f"{copied['items']} items and {copied['months']} archive month(s) in {folder}")

    def finish(self) -> None:
        self.title(6, "Try it")
        for line in (
            "unlimited search flood thailand",
            'unlimited ask "what are the latest big insider trades?"',
            "unlimited search --list-feeds",
            f"unlimited search sanctions --catalog {OFFLINE_DIR}    # offline",
            "unlimited doctor                                     # check again any time",
        ):
            self.echo(f"  {line}")
        summary = f"Set up: {', '.join(self.done) or 'nothing new'}"
        if self.skipped:
            summary += f". Skipped: {', '.join(self.skipped)} (run unlimited setup again any time)"
        self.echo("\n" + summary + ".")

    def __call__(self) -> None:
        if not self.yes and not self.interactive:
            self.echo("No terminal to ask in: only checking. Pass --yes to set everything up.")
        self.check()
        self.browser()
        self.ai()
        self.agents()
        self.offline()
        self.finish()
