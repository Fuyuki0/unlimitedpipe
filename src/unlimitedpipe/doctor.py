"""`unlimited doctor`: what works on this machine, what is missing, and how to fix it."""

from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

from unlimitedpipe._version import USER_AGENT, __version__


@dataclass
class Check:
    area: str
    name: str
    ok: bool
    detail: str
    fix: str | None = None
    optional: bool = False


KEYS = [
    (
        "GITHUB_TOKEN",
        "github: 5,000 requests an hour instead of 60",
        "a token from github.com/settings/tokens (no scopes needed)",
    ),
    (
        "SEC_CONTACT",
        "sec: the contact email the SEC asks for",
        "export SEC_CONTACT=you@example.com",
    ),
    (
        "YOUTUBE_API_KEY",
        "youtube",
        "a free key: console.cloud.google.com, enable YouTube Data API v3",
    ),
    (
        "REDDIT_CLIENT_ID",
        "reddit (with REDDIT_CLIENT_SECRET)",
        "a free 'script' app at reddit.com/prefs/apps",
    ),
    ("X_BEARER_TOKEN", "x: needs a paid X API plan", "developer.x.com"),
    ("ANTHROPIC_API_KEY", "ask: answers from Claude", "console.anthropic.com"),
]


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".doctor"
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False


def run_checks(catalog: str | None = None, timeout: float = 8.0) -> list[Check]:
    from unlimitedpipe.context import Context
    from unlimitedpipe.sources.ask import OLLAMA, PREFERRED
    from unlimitedpipe.sources.search import catalog_url

    checks = [
        Check("core", "UnlimitedPipe", True, f"{__version__} on Python {sys.version.split()[0]}"),
    ]
    ctx = Context(quiet=True)
    for name, path in (("state folder", ctx.state_dir), ("cache folder", ctx.cache_dir)):
        ok = _writable(path)
        checks.append(Check("core", name, ok, str(path), None if ok else f"make {path} writable"))

    url = catalog_url(catalog)
    try:
        response = httpx.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        document = response.json() if response.status_code == 200 else {}
        feeds = len(document.get("feeds", [])) if isinstance(document, dict) else 0
        failing = [
            f["name"]
            for f in document.get("feeds", [])
            if (f.get("health") or {}).get("status") in ("failing", "partial")
        ]
        detail = f"{url}: {feeds} feeds" + (f", {len(failing)} failing" if failing else "")
        checks.append(
            Check(
                "network",
                "feed catalog",
                feeds > 0,
                detail,
                None if feeds else "check your connection or --catalog URL",
            )
        )
    except (httpx.HTTPError, ValueError) as exc:
        checks.append(
            Check(
                "network",
                "feed catalog",
                False,
                f"{url}: {exc.__class__.__name__}",
                "check your internet connection",
            )
        )

    live = importlib.util.find_spec("websockets") is not None
    checks.append(
        Check(
            "extras",
            "live (bluesky)",
            live,
            "installed" if live else "not installed",
            None if live else 'pip install "unlimitedpipe[live]"',
            optional=True,
        )
    )
    browser = importlib.util.find_spec("playwright") is not None
    chromium = any(Path.home().glob(".cache/ms-playwright/chromium*")) or any(
        Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/nonexistent")).glob("chromium*")
    )
    detail = (
        "Playwright and Chromium"
        if browser and chromium
        else ("Playwright without Chromium" if browser else "not installed")
    )
    checks.append(
        Check(
            "extras",
            "browser (web --browser)",
            browser and chromium,
            detail,
            None
            if browser and chromium
            else 'pip install "unlimitedpipe[browser]" && playwright install chromium',
            optional=True,
        )
    )

    host = os.environ.get("OLLAMA_HOST", OLLAMA)
    host = host if host.startswith("http") else f"http://{host}"
    try:
        models = [m["name"] for m in httpx.get(f"{host}/api/tags", timeout=3).json()["models"]]
        best = next((m for m in PREFERRED if m in models), models[0] if models else None)
        checks.append(
            Check(
                "ai",
                "Ollama (ask, local)",
                bool(models),
                f"{len(models)} model(s), ask uses {best}" if models else "no models",
                None if models else "ollama pull qwen2.5:3b",
                optional=True,
            )
        )
    except (httpx.HTTPError, ValueError, KeyError):
        checks.append(
            Check(
                "ai",
                "Ollama (ask, local)",
                False,
                f"not running at {host}",
                "install from https://ollama.com, then: ollama pull qwen2.5:3b",
                optional=True,
            )
        )

    for variable, what, fix in KEYS:
        present = bool(os.environ.get(variable))
        checks.append(
            Check("keys", variable, present, what, None if present else fix, optional=True)
        )
    return checks
