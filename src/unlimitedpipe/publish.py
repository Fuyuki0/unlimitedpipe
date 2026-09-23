"""`unlimited publish`: host a pipeline's outputs for free with GitHub Actions and Pages.

The generated workflow runs the pipeline on a schedule, commits the diff state and outputs
(so `diff` and `feed` remember earlier runs), and deploys the output directory to GitHub
Pages. Nothing runs on UnlimitedPipe's side: it is your repository and your workflow.
"""

from __future__ import annotations

import hashlib
import html
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from unlimitedpipe._version import __version__
from unlimitedpipe.config import Pipeline, env_references
from unlimitedpipe.errors import UsageError

STATE_DIR = ".unlimitedpipe/state"
ACTIONS = {
    "checkout": "actions/checkout@v7",
    "setup-python": "actions/setup-python@v7",
    "upload-pages-artifact": "actions/upload-pages-artifact@v5",
    "deploy-pages": "actions/deploy-pages@v5",
}
MIN_EVERY = 15 * 60


@dataclass
class PublishPlan:
    root: Path  # the git repository
    pipeline: Path  # relative to root
    site_dir: Path  # relative to root: what gets deployed
    files: list[Path]  # published outputs, relative to site_dir
    workflow: Path  # relative to root
    cron: str
    site_url: str | None  # https://owner.github.io/repo/ when the remote is on GitHub
    secrets: list[str]  # ${NAME} references, passed from repository secrets


def git_root(path: Path) -> Path:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        raise UsageError(
            f"{path} is not inside a git repository",
            hint="publish needs a GitHub repository: git init, then push it to GitHub",
        ) from None
    return Path(out.stdout.strip())


def github_repo(root: Path) -> tuple[str, str] | None:
    """(owner, repo) of the ``origin`` remote, if it is on GitHub."""
    try:
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    match = re.search(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?$", remote)
    return (match.group(1), match.group(2)) if match else None


def pages_url(root: Path) -> str | None:
    """``https://owner.github.io/repo/`` for the ``origin`` remote, if it is on GitHub."""
    found = github_repo(root)
    if found is None:
        return None
    owner, repo = found
    if repo.lower() == f"{owner.lower()}.github.io":
        return f"https://{owner.lower()}.github.io/"
    return f"https://{owner.lower()}.github.io/{repo}/"


def cron_for(seconds: float, name: str) -> str:
    """A cron schedule for an interval, at a minute derived from the name to spread load."""
    if seconds < MIN_EVERY:
        raise UsageError(
            "--every must be at least 15m for GitHub Actions",
            hint="scheduled workflows are best effort; hourly or slower is typical",
        )
    minute = int(hashlib.sha256(name.encode()).hexdigest(), 16) % 60
    minutes = int(seconds // 60)
    if minutes < 60:
        if 60 % minutes:
            raise UsageError("--every below 1h must divide an hour: 15m, 20m or 30m")
        return f"{minute % minutes}-59/{minutes} * * * *"
    hours = minutes // 60
    if minutes % 60 == 0 and hours < 24 and 24 % hours == 0:
        return f"{minute} */{hours} * * *" if hours > 1 else f"{minute} * * * *"
    if minutes == 24 * 60:
        return f"{minute} {int(hashlib.sha256(name.encode()).hexdigest(), 16) % 24} * * *"
    raise UsageError(
        "--every must be 15m, 20m, 30m, a divisor of 24h (1h, 2h, 3h, 4h, 6h, 8h, 12h) or 1d"
    )


def plan(pipeline_path: Path, pipeline: Pipeline, every: float) -> PublishPlan:
    pipeline_path = pipeline_path.resolve()
    root = git_root(pipeline_path.parent)
    outputs = [
        Path(p).resolve()
        for p in (getattr(o, "path", None) for o in pipeline.outputs)
        if p and p != "-"
    ]
    if not outputs:
        raise UsageError(
            "the pipeline writes no files to publish",
            hint="add an output with a path, e.g.\n  - type: feed\n    path: public/feed.xml",
        )
    site_dir = outputs[0].parent
    for output in outputs[1:]:
        while site_dir not in output.parents:
            site_dir = site_dir.parent
    if site_dir == root or root not in site_dir.parents:
        raise UsageError(
            "outputs must be in a folder of their own inside the repository",
            hint="write them under a folder such as public/: path: public/feed.xml",
        )
    return PublishPlan(
        root=root,
        pipeline=pipeline_path.relative_to(root),
        site_dir=site_dir.relative_to(root),
        files=[o.relative_to(site_dir) for o in outputs],
        workflow=Path(".github/workflows") / f"unlimitedpipe-{pipeline.name}.yml",
        cron=cron_for(every, pipeline.name),
        site_url=pages_url(root),
        secrets=[n for n in env_references(pipeline_path.read_text()) if n != "GITHUB_TOKEN"],
    )


def workflow(p: PublishPlan, name: str) -> str:
    secrets = "".join(f"\n          {secret}: ${{{{ secrets.{secret} }}}}" for secret in p.secrets)
    return f"""\
# Generated by `unlimited publish`: runs the {name} pipeline on a schedule, keeps its state in
# the repository, and publishes {p.site_dir}/ with GitHub Pages.
name: "UnlimitedPipe: {name}"

on:
  schedule:
    - cron: "{p.cron}"
  workflow_dispatch:

permissions:
  contents: write
  pages: write
  id-token: write

concurrency:
  group: unlimitedpipe-{name}
  cancel-in-progress: false

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: {ACTIONS["checkout"]}
      - uses: {ACTIONS["setup-python"]}
        with:
          python-version: "3.12"
      - run: pip install "unlimitedpipe=={__version__}"
      - name: Run the pipeline
        env:
          UNLIMITEDPIPE_STATE_DIR: {STATE_DIR}
          GITHUB_TOKEN: ${{{{ secrets.GITHUB_TOKEN }}}}{secrets}
        run: |
          set +e
          unlimited run "{p.pipeline.as_posix()}"
          code=$?
          set -e
          if [ "$code" -eq 1 ]; then
            echo "::warning::some sources failed; publishing the rest"
          elif [ "$code" -ne 0 ]; then
            exit "$code"
          fi
      - name: Save outputs and state
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add "{p.site_dir.as_posix()}"
          if [ -d "{STATE_DIR}" ]; then git add "{STATE_DIR}"; fi
          git diff --cached --quiet || git commit -m "Update {name}"
          git push
      - uses: {ACTIONS["upload-pages-artifact"]}
        with:
          path: "{p.site_dir.as_posix()}"

  deploy:
    needs: run
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{{{ steps.deployment.outputs.page_url }}}}
    steps:
      - id: deployment
        uses: {ACTIONS["deploy-pages"]}
"""


def index_page(name: str, files: list[Path], every: str) -> str:
    items = "\n".join(
        f'      <li><a href="{html.escape(f.as_posix())}">{html.escape(f.as_posix())}</a></li>'
        for f in files
    )
    title = html.escape(name)
    return f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <style>
      body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 40rem; margin: 3rem auto; }}
      body {{ padding: 0 1rem; }}
      code {{ background: #f3f3f3; padding: 0 .3rem; }}
    </style>
  </head>
  <body>
    <h1>{title}</h1>
    <p>Updated every {html.escape(every)} by a GitHub Actions workflow.
    Subscribe in any feed reader:</p>
    <ul>
{items}
    </ul>
    <p>Built with <a href="https://pypi.org/project/unlimitedpipe/">UnlimitedPipe</a>.
    Make your own: <code>pip install unlimitedpipe</code>, then <code>unlimited publish</code>.</p>
  </body>
</html>
"""
