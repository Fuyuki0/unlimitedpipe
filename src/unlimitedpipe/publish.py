"""`unlimited publish`: host a pipeline's outputs for free with GitHub Actions and Pages.

The generated workflow runs the pipeline on a schedule, commits the diff state and outputs
(so `diff` and `feed` remember earlier runs), and deploys the output directory to GitHub
Pages. Nothing runs on UnlimitedPipe's side: it is your repository and your workflow.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from unlimitedpipe._version import __version__
from unlimitedpipe.config import Pipeline, env_references
from unlimitedpipe.errors import UsageError

STATE_DIR = ".unlimitedpipe/state"
CATALOG = "feeds.json"  # the feeds and their latest items, for `unlimited search`
CATALOG_SCHEMA = "unlimitedpipe.catalog/1"
ACTIONS = {
    "checkout": "actions/checkout@v7",
    "setup-python": "actions/setup-python@v7",
    "upload-pages-artifact": "actions/upload-pages-artifact@v5",
    "deploy-pages": "actions/deploy-pages@v5",
}
MIN_EVERY = 15 * 60


@dataclass
class Published:
    """One pipeline in a publish plan."""

    path: Path  # relative to the repository
    name: str
    description: str | None
    files: list[Path]  # relative to the site folder


@dataclass
class PublishPlan:
    root: Path  # the git repository
    name: str  # names the workflow
    pipelines: list[Published]
    site_dir: Path  # relative to root: what gets deployed
    workflow: Path  # relative to root
    cron: str
    site_url: str | None  # https://owner.github.io/repo/ when the remote is on GitHub
    secrets: list[str]  # ${NAME} references, passed from repository secrets

    @property
    def files(self) -> list[Path]:
        return [f for p in self.pipelines for f in p.files]


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


def plan(items: list[tuple[Path, Pipeline]], every: float, name: str | None = None) -> PublishPlan:
    """Plan one workflow that runs every given pipeline and publishes their outputs."""
    if not items:
        raise UsageError("give at least one pipeline file")
    root = git_root(items[0][0].resolve().parent)
    outputs: list[tuple[int, Path]] = []
    for index, (path, pipeline) in enumerate(items):
        files = [
            Path(p).resolve()
            for p in (getattr(o, "path", None) for o in pipeline.outputs)
            if p and p != "-"
        ]
        if not files:
            raise UsageError(
                f"{path}: the pipeline writes no files to publish",
                hint="add an output with a path, e.g.\n  - type: feed\n    path: public/feed.xml",
            )
        outputs.extend((index, f) for f in files)
    site_dir = outputs[0][1].parent
    for _, output in outputs[1:]:
        while site_dir not in output.parents:
            site_dir = site_dir.parent
    if site_dir == root or root not in site_dir.parents:
        raise UsageError(
            "outputs must be in a folder of their own inside the repository",
            hint="write them under a folder such as public/: path: public/feed.xml",
        )
    published = [
        Published(
            path=path.resolve().relative_to(root),
            name=pipeline.name,
            description=pipeline.description,
            files=[f.relative_to(site_dir) for i, f in outputs if i == index],
        )
        for index, (path, pipeline) in enumerate(items)
    ]
    name = name or (items[0][1].name if len(items) == 1 else "feeds")
    secrets: dict[str, None] = {}
    for path, _ in items:
        secrets.update(
            dict.fromkeys(n for n in env_references(path.read_text()) if n != "GITHUB_TOKEN")
        )
    return PublishPlan(
        root=root,
        name=name,
        pipelines=published,
        site_dir=site_dir.relative_to(root),
        workflow=Path(".github/workflows") / f"unlimitedpipe-{name}.yml",
        cron=cron_for(every, name),
        site_url=pages_url(root),
        secrets=list(secrets),
    )


def workflow(p: PublishPlan) -> str:
    secrets = "".join(f"\n          {secret}: ${{{{ secrets.{secret} }}}}" for secret in p.secrets)
    pipelines = " ".join(f'"{item.path.as_posix()}"' for item in p.pipelines)
    site = p.site_dir.as_posix()
    return f"""\
# Generated by `unlimited publish`: runs {len(p.pipelines)} pipeline(s) on a schedule, keeps
# their state in the repository, and publishes {site}/ with GitHub Pages.
name: "UnlimitedPipe: {p.name}"

on:
  schedule:
    - cron: "{p.cron}"
  workflow_dispatch:

permissions:
  contents: write
  pages: write
  id-token: write

concurrency:
  group: unlimitedpipe-{p.name}
  cancel-in-progress: false

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      # The branch as it is now, not the commit that queued this run: an earlier run may
      # have pushed new outputs and state while this one waited.
      - uses: {ACTIONS["checkout"]}
        with:
          ref: ${{{{ github.ref }}}}
      - uses: {ACTIONS["setup-python"]}
        with:
          python-version: "3.12"
      - run: pip install "unlimitedpipe=={__version__}"
      - name: Run the pipelines
        env:
          UNLIMITEDPIPE_STATE_DIR: {STATE_DIR}
          GITHUB_TOKEN: ${{{{ secrets.GITHUB_TOKEN }}}}{secrets}
        run: |
          ok=0
          for pipeline in {pipelines}; do
            set +e
            unlimited run "$pipeline"
            code=$?
            set -e
            if [ "$code" -eq 0 ]; then
              ok=$((ok + 1))
            elif [ "$code" -eq 1 ]; then
              ok=$((ok + 1))
              echo "::warning::$pipeline: some sources failed; publishing the rest"
            else
              echo "::error::$pipeline failed (exit $code); publishing the others"
            fi
          done
          [ "$ok" -gt 0 ]  # fail only when nothing could run
      - name: Index the feeds for search
        run: unlimited catalog {pipelines} || echo "::warning::could not update {site}/{CATALOG}"
      - name: Save outputs and state
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add "{site}"
          if [ -d "{STATE_DIR}" ]; then git add "{STATE_DIR}"; fi
          if git diff --cached --quiet; then exit 0; fi
          git commit -m "Update {p.name}"
          for attempt in 1 2 3; do
            git pull --rebase --autostash --quiet && git push --quiet && exit 0
            sleep $((attempt * 5))
          done
          exit 1
      - uses: {ACTIONS["upload-pages-artifact"]}
        with:
          path: "{site}"

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


def catalog(p: PublishPlan, per_feed: int = 30, summary_chars: int = 300) -> dict:
    """The feeds of a publish plan and their latest items, as one small document.

    Items come from the JSON Feed files the pipelines wrote, so searching every feed takes one
    request. Paths are relative to the site, so the catalog works under any domain.
    """
    site = p.root / p.site_dir
    feeds, items = [], []
    for item in p.pipelines:
        feeds.append(
            {
                "name": item.name,
                "description": item.description,
                "files": [f.as_posix() for f in item.files],
            }
        )
        for file in item.files:
            if file.suffix != ".json":
                continue
            try:
                document = json.loads((site / file).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue  # not written yet, or not a feed
            if not str(document.get("version", "")).startswith("https://jsonfeed.org/"):
                continue
            for entry in document.get("items", [])[:per_feed]:
                summary = entry.get("summary") or entry.get("content_text") or ""
                if summary == entry.get("title"):
                    summary = ""
                items.append(
                    {
                        "feed": item.name,
                        "title": entry.get("title"),
                        "summary": summary[:summary_chars] or None,
                        "link": entry.get("url"),
                        "date": entry.get("date_published"),
                    }
                )
    items.sort(key=lambda i: i["date"] or "", reverse=True)
    return {"schema": CATALOG_SCHEMA, "title": p.name, "feeds": feeds, "items": items}


def write_catalog(p: PublishPlan) -> Path | None:
    """Write feeds.json into the site folder unless a pipeline writes a file of that name.
    Returns the path when the file changed."""
    if any(f.as_posix() == CATALOG for f in p.files):
        return None
    path = p.root / p.site_dir / CATALOG
    text = json.dumps(catalog(p), ensure_ascii=False, indent=1) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


SEARCH_SCRIPT = r"""    <script>
      // Searches feeds.json in the browser: no server, no tracking.
      const q = document.getElementById("q"), list = document.getElementById("results"),
        status = document.getElementById("status");
      let catalog = null;
      const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      // Words match at the start of a word; scripts without spaces (Thai) match anywhere.
      const word = (w) => /^[\x00-\x7f]+$/.test(w)
        ? new RegExp("(^|[^\\p{L}\\p{N}_])" + escape(w), "iu")
        : new RegExp(escape(w), "i");
      async function load() {
        if (!catalog) catalog = await (await fetch("feeds.json")).json();
      }
      function show() {
        const words = q.value.trim().split(/\s+/).filter(Boolean).map(word);
        list.replaceChildren();
        if (!words.length) { status.textContent = ""; return; }
        const about = Object.fromEntries(
          catalog.feeds.map((f) => [f.name, f.name.replaceAll("-", " ")]));
        const hits = catalog.items.filter((i) => words.every((w) => w.test(
          (i.title || "") + " " + (i.summary || "") + " " + (about[i.feed] || "")))).slice(0, 50);
        status.textContent = hits.length ? hits.length + " result(s)" : "Nothing matches.";
        for (const i of hits) {
          const li = document.createElement("li"), a = document.createElement("a");
          a.href = i.link || "#"; a.textContent = i.title || i.link; a.rel = "noopener";
          const meta = document.createElement("small");
          meta.textContent = "  " + i.feed + (i.date ? " · " + i.date.slice(0, 10) : "");
          li.append(a, meta);
          if (i.summary) {
            const p = document.createElement("div");
            p.className = "muted"; p.textContent = i.summary.slice(0, 200); li.append(p);
          }
          list.append(li);
        }
      }
      q.addEventListener("input", () => load().then(show).catch(() => {
        status.textContent = "Search starts working after the next run writes feeds.json.";
      }));
    </script>
"""


INDEX_MARKER = "<!-- generated by unlimited publish -->"


def index_page(p: PublishPlan, every: str) -> str:
    sections = []
    for item in p.pipelines:
        links = " · ".join(
            f'<a href="{html.escape(f.as_posix())}">'
            f"{html.escape(f.suffix.lstrip('.').upper() or f.name)}</a>"
            for f in item.files
        )
        about = f"<p>{html.escape(item.description)}</p>" if item.description else ""
        sections.append(
            f"    <section>\n      <h2>{html.escape(item.name)}</h2>\n"
            f"      {about}\n      <p>{links}</p>\n    </section>"
        )
    title = html.escape(p.name)
    body = "\n".join(sections)
    return f"""\
<!doctype html>
{INDEX_MARKER}
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <style>
      body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 44rem; margin: 3rem auto; }}
      body {{ padding: 0 1rem; color: #1a1a1a; }}
      section {{ border-top: 1px solid #ddd; padding-top: .5rem; }}
      h2 {{ font-size: 1.1rem; margin-bottom: .2rem; }}
      section p {{ margin: .2rem 0; }}
      code {{ background: #f3f3f3; padding: 0 .3rem; }}
      #q {{ width: 100%; font: inherit; padding: .5rem .7rem; border: 1px solid #bbb;
            border-radius: 6px; box-sizing: border-box; }}
      #results {{ list-style: none; padding: 0; }}
      #results li {{ margin: .6rem 0; }}
      #results small, .muted {{ color: #666; }}
    </style>
  </head>
  <body>
    <h1>{title}</h1>
    <p>Updated every {html.escape(every)} by a GitHub Actions workflow. Subscribe to any feed
    in a feed reader (XML), or read it as data (JSON).</p>
    <input id="q" type="search" placeholder="Search every feed, e.g. flood, bankruptcy, Bangkok"
      autocomplete="off" aria-label="Search every feed">
    <p id="status" class="muted"></p>
    <ul id="results"></ul>
{body}
    <p>Built with <a href="https://github.com/Fuyuki0/unlimitedpipe">UnlimitedPipe</a>.
    Make your own: <code>pip install unlimitedpipe</code>, then <code>unlimited publish</code>.</p>
{SEARCH_SCRIPT}  </body>
</html>
"""
