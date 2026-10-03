"""`unlimited publish`: host a pipeline's outputs for free with GitHub Actions and Pages.

The generated workflow runs the pipeline on a schedule, commits the diff state and outputs
(so `diff` and `feed` remember earlier runs), and deploys the output directory to GitHub
Pages. Nothing runs on UnlimitedPipe's side: it is your repository and your workflow.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    group: str | None = None  # the topic the index page lists it under
    title: str | None = None  # a readable name: its feed's title ("IPO filings (SEC S-1 and F-1)")
    archive: bool = True  # False: its items are listed but never archived


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
    install: str = f"unlimitedpipe=={__version__}"  # what the workflow installs with pip
    browser: bool = False  # a pipeline renders pages with --browser: install Chromium too
    # Those pipelines: when none is in the express lane, Chromium is installed only in the runs
    # that run the rest (it takes a fifth of an express run).
    browser_pipelines: list[str] = field(default_factory=list)
    title: str | None = None  # the site's title (default: the workflow name)
    about: str | None = None  # a sentence under the title on the index page
    groups: list[str] = field(default_factory=list)  # the order of the index page's topics
    links: list[tuple[str, str]] = field(default_factory=list)  # (label, url) in its header
    examples: list[str] = field(default_factory=list)  # searches to try, under the search box
    # A live copy of part of the catalog (`unlimited watch --catalog` on a server), newer than
    # this one: readers merge its items in when they can reach it.
    live: str | None = None
    # The express lane: pipelines run by every scheduled run (every `express_every`); the
    # others run when `every` seconds have passed since they last did.
    express: list[str] = field(default_factory=list)
    every: float = 3600
    express_every: float | None = None

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


def plan(
    items: list[tuple[Path, Pipeline]],
    every: float,
    name: str | None = None,
    express: list[str] | None = None,
    express_every: float = 15 * 60,
) -> PublishPlan:
    """Plan one workflow that runs every given pipeline and publishes their outputs; the
    pipelines named in `express` run more often, every `express_every`."""
    if not items:
        raise UsageError("give at least one pipeline file")
    names = {pipeline.name for _, pipeline in items} | {path.stem for path, _ in items}
    if unknown := sorted(set(express or []) - names):
        raise UsageError(
            f"--express names no pipeline being published: {', '.join(unknown)}",
            hint="use pipeline names, e.g. --express earthquakes",
        )
    if express and express_every >= every:
        raise UsageError("--express-every must be shorter than --every")
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
    for path, _ in items:
        if site_dir in path.resolve().parents:
            relative = os.path.relpath(root / "public", path.resolve().parent)
            raise UsageError(
                f"{path} is inside {site_dir.relative_to(root)}/, the folder that would be "
                "published, so the pipelines would be published with their outputs",
                hint=f"write the outputs to a folder of their own: path: {relative}/feed.xml",
            )
    published = [
        Published(
            path=path.resolve().relative_to(root),
            name=pipeline.name,
            description=pipeline.description,
            files=[f.relative_to(site_dir) for i, f in outputs if i == index],
            group=pipeline.group,
            archive=pipeline.archive,
            title=next(
                (str(title) for o in pipeline.outputs if (title := getattr(o, "title", None))),
                None,
            ),
        )
        for index, (path, pipeline) in enumerate(items)
    ]
    name = name or (items[0][1].name if len(items) == 1 else "feeds")
    secrets: dict[str, None] = {}
    for path, _ in items:
        secrets.update(
            dict.fromkeys(n for n in env_references(path.read_text()) if n != "GITHUB_TOKEN")
        )
    lane = set(express or [])
    return PublishPlan(
        root=root,
        name=name,
        pipelines=published,
        site_dir=site_dir.relative_to(root),
        workflow=Path(".github/workflows") / f"unlimitedpipe-{name}.yml",
        cron=cron_for(express_every if lane else every, name),
        express=[
            i.path.as_posix()
            for i, (path, pipeline) in zip(published, items, strict=True)
            if pipeline.name in lane or path.stem in lane
        ],
        every=every,
        express_every=express_every if lane else None,
        site_url=pages_url(root),
        secrets=list(secrets),
        browser=any(getattr(s, "browser", False) is True for _, pl in items for s in pl.sources),
        browser_pipelines=[
            i.path.as_posix()
            for i, (_, pipeline) in zip(published, items, strict=True)
            if any(getattr(s, "browser", False) is True for s in pipeline.sources)
        ],
    )


AT_ONCE = 6  # pipelines a workflow run runs side by side


def workflow(p: PublishPlan) -> str:
    install_browser = (
        'pip install "playwright>=1.45" && python -m playwright install --with-deps chromium'
    )
    # With an express lane that needs no browser, only the runs that run the rest install it.
    browser_later = bool(p.express) and not set(p.browser_pipelines) & set(p.express)
    browser_setup = f"\n      - run: {install_browser}" if p.browser and not browser_later else ""
    browser_in_lane = f"\n            {install_browser}" if p.browser and browser_later else ""
    secrets = "".join(f"\n          {secret}: ${{{{ secrets.{secret} }}}}" for secret in p.secrets)
    pipelines = " ".join(f'"{item.path.as_posix()}"' for item in p.pipelines)
    site = p.site_dir.as_posix()
    if p.express:
        express = " ".join(f'"{path}"' for path in p.express)
        rest = " ".join(
            f'"{i.path.as_posix()}"' for i in p.pipelines if i.path.as_posix() not in p.express
        )
        due = int(p.every) - 300  # a run a few minutes early still counts
        full_run = (
            f'if [ "$event" != schedule ] && [ "$lane" != express ] || [ "$age" -ge {due} ]; then'
        )
        lanes = f"""
          # The express lane runs every time; the rest when it last ran {int(p.every)}s ago or
          # more (GitHub starts scheduled runs late or not at all when busy), or when this run
          # was started by hand with lane "all". An outside timer starts it with lane "express".
          each {express}
          last=$(cat "{STATE_DIR}/last-full-run" 2>/dev/null || echo 0)
          age=$(( $(date +%s) - last ))
          event="${{{{ github.event_name }}}}" lane="${{{{ inputs.lane }}}}"
          {full_run}{browser_in_lane}
            each {rest}
            mkdir -p "{STATE_DIR}" && date +%s > "{STATE_DIR}/last-full-run"
          fi"""
    else:
        lanes = f"""
          each {pipelines}"""
    dispatch = "workflow_dispatch:"
    if p.express:
        dispatch = """workflow_dispatch:
    inputs:
      lane:
        description: "all: every pipeline; express: the express lane, the rest when due"
        type: choice
        options: [all, express]
        default: all"""
    return f"""\
# Generated by `unlimited publish`: runs {len(p.pipelines)} pipeline(s) on a schedule, keeps
# their state in the repository, and publishes {site}/ with GitHub Pages.
name: "UnlimitedPipe: {p.name}"

on:
  schedule:
    - cron: "{p.cron}"
  {dispatch}

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
      - run: pip install "{p.install}"{browser_setup}
      - name: Run the pipelines
        env:
          UNLIMITEDPIPE_STATE_DIR: {STATE_DIR}
          GITHUB_TOKEN: ${{{{ secrets.GITHUB_TOKEN }}}}{secrets}
        run: |
          results="$RUNNER_TEMP/unlimitedpipe-results"
          run() {{
            log="$RUNNER_TEMP/$(basename "$1").log"
            set +e
            unlimited run "$1" > "$log" 2>&1
            code=$?
            set -e
            echo "$code $1" >> "$results"
            {{ echo "::group::$1 (exit $code)"; cat "$log"; echo "::endgroup::"; }}
            if [ "$code" -eq 1 ]; then
              echo "::warning::$1: some sources failed; publishing the rest"
            elif [ "$code" -gt 1 ]; then
              echo "::error::$1 failed (exit $code); publishing the others"
            fi
          }}
          # Pipelines read different sources, so they run side by side, {AT_ONCE} at a time:
          # a lane takes as long as its slowest source, not the sum of them all.
          each() {{
            for pipeline in "$@"; do
              run "$pipeline" &
              while [ "$(jobs -rp | wc -l)" -ge {AT_ONCE} ]; do wait -n; done
            done
            wait
          }}{lanes}
          # fail only when nothing could run
          [ "$(awk '$1 <= 1' "$results" 2>/dev/null | wc -l)" -gt 0 ]
      - name: Index the feeds for search
        run: >-
          unlimited catalog --results "$RUNNER_TEMP/unlimitedpipe-results" {pipelines}
          || echo "::warning::could not update {site}/{CATALOG}"
      - name: Save outputs and state
        id: save
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add "{site}"
          if [ -d "{STATE_DIR}" ]; then git add "{STATE_DIR}"; fi
          if git diff --cached --quiet -- "{site}"; then
            echo "changed=false" >> "$GITHUB_OUTPUT"  # nothing new to publish
          else
            echo "changed=true" >> "$GITHUB_OUTPUT"
          fi
          if git diff --cached --quiet; then exit 0; fi
          git commit -m "Update {p.name}"
          for attempt in 1 2 3; do
            git pull --rebase --autostash --quiet && git push --quiet && exit 0
            sleep $((attempt * 5))
          done
          exit 1
      - uses: {ACTIONS["upload-pages-artifact"]}
        if: steps.save.outputs.changed == 'true'
        with:
          path: "{site}"
    outputs:
      changed: ${{{{ steps.save.outputs.changed }}}}

  deploy:
    needs: run
    if: needs.run.outputs.changed == 'true'
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{{{ steps.deployment.outputs.page_url }}}}
    steps:
      - id: deployment
        uses: {ACTIONS["deploy-pages"]}
"""


STATUS = {0: "ok", 1: "partial"}  # any other exit code: failing


def health(code: int | None, previous: dict | None, latest: str | None, now: str) -> dict | None:
    """A feed's health after a run: ok, partial (some sources failed) or failing, since when,
    and its newest item. The time only moves when the status changes, so a healthy catalog is
    not rewritten by every run."""
    if code is None:  # not run here (a local `unlimited catalog`): keep what was known
        return {**previous, "latest": latest} if previous else None
    status = STATUS.get(code, "failing")
    since = previous.get("since") if previous and previous.get("status") == status else now
    return {"status": status, "since": since, "latest": latest}


def catalog(
    p: PublishPlan,
    per_feed: int = 30,
    summary_chars: int = 300,
    *,
    results: dict[str, int] | None = None,
    previous: dict | None = None,
    now: str | None = None,
) -> dict:
    """The feeds of a publish plan and their latest items, as one small document.

    Items come from the JSON Feed files the pipelines wrote, so searching every feed takes one
    request. Paths are relative to the site, so the catalog works under any domain. With the
    exit codes of a run (`results`, by pipeline path), each feed also carries its health.
    """
    from unlimitedpipe import archive
    from unlimitedpipe.event import utcnow

    site = p.root / p.site_dir
    now = now or utcnow()
    seen: set[str] = set()
    before = {f.get("name"): f.get("health") for f in (previous or {}).get("feeds", [])}
    feeds, items = [], []
    for item in p.pipelines:
        latest = None
        for file in item.files:
            if file.suffix == ".json":
                latest = _newest(site / file) or latest
        entry = {
            "name": item.name,
            **({"title": item.title} if item.title else {}),
            "description": item.description,
            **({"group": item.group} if item.group else {}),
            **({"archive": False} if not item.archive else {}),
            "files": [f.as_posix() for f in item.files],
        }
        code = (results or {}).get(item.path.as_posix())
        if (state := health(code, before.get(item.name), latest, now)) is not None:
            entry["health"] = state
        feeds.append(entry)
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
                listed = listed_item(item.name, entry, summary_chars)
                if (key := archive.item_key(listed)) not in seen:  # one story, two sources
                    seen.add(key)
                    items.append(listed)
    items.sort(key=lambda i: i["date"] or "", reverse=True)
    return {
        "schema": CATALOG_SCHEMA,
        # A catalog keeps its title between runs: the hourly `unlimited catalog` has none.
        "title": p.title or (previous or {}).get("title") or p.name,
        "archive": "archive/index.json",  # every item ever listed, by month
        **({"live": live} if (live := p.live or (previous or {}).get("live")) else {}),
        "feeds": feeds,
        "items": items,
    }


def listed_item(feed: str, entry: dict[str, Any], summary_chars: int = 300) -> dict[str, Any]:
    """A JSON Feed item as the catalog and its archive list it."""
    summary = entry.get("summary") or entry.get("content_text") or ""
    if summary == entry.get("title"):
        summary = ""
    return {
        "feed": feed,
        "title": entry.get("title"),
        "summary": summary[:summary_chars] or None,
        "link": entry.get("url"),
        "date": entry.get("date_published"),
    }


def _newest(path: Path) -> str | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    dates = [i.get("date_published") for i in document.get("items", []) if isinstance(i, dict)]
    return max((d for d in dates if isinstance(d, str)), default=None)


def write_catalog(
    p: PublishPlan, results: dict[str, int] | None = None, archived: dict[str, int] | None = None
) -> Path | None:
    """Write feeds.json into the site folder unless a pipeline writes a file of that name, and
    add new items to the archive (their counts per month go into ``archived``). Returns the
    path when feeds.json changed."""
    from unlimitedpipe import archive
    from unlimitedpipe.event import utcnow

    if any(f.as_posix() == CATALOG for f in p.files):
        return None
    path = p.root / p.site_dir / CATALOG
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = None
    document = catalog(p, results=results, previous=previous)
    kept = {i.name for i in p.pipelines if i.archive}
    listed = [i for i in document["items"] if i.get("feed") in kept]
    added = archive.append(p.root / p.site_dir, listed, utcnow())
    if archived is not None:
        archived.update(added)
    text = json.dumps(document, ensure_ascii=False, indent=1) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


SEARCH_SCRIPT = r"""    <script>
      // Searches feeds.json in the browser: no server, no tracking.
      // The live data asks the server each time whether it changed (GitHub Pages lets browsers
      // keep it 10 minutes otherwise); an unchanged file costs a 304.
      const FRESH = { cache: "no-cache" };
      const q = document.getElementById("q"), list = document.getElementById("results"),
        status = document.getElementById("status");
      let catalog = null, response = null;
      const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      // Words match at the start of a word: five letters or more with any ending, four with
      // their own endings ("noto" is not "notorious"), three or fewer with plural and verb
      // endings ("ai" is not "aid"), as `unlimited search` does. Scripts without spaces (Thai)
      // match anywhere.
      const word = (w) => {
        if (!/^[\x00-\x7f]+$/.test(w)) return new RegExp(escape(w), "i");
        const end = w.length <= 3 ? "(?:s|es|'s|ed|ing)?(?![\\p{L}\\p{N}_])"
          : w.length === 4 ? "(?:s|es|'s|e?d|ing|ers?|i?ans?|ese|ish)?(?![\\p{L}\\p{N}_])" : "";
        return new RegExp("(^|[^\\p{L}\\p{N}_])" + escape(w) + end, "iu");
      };
      const day = (iso) => (iso || "").slice(0, 10);
      async function load() {
        if (!catalog) {
          response = await fetch("feeds.json", FRESH);
          catalog = await response.json();
          if (catalog.live) await withLive();
        }
      }
      // A live copy of the time-sensitive feeds, polled every minute on a server: its newer
      // items are merged in when it answers within 3 seconds.
      async function withLive() {
        try {
          const live = await fetch(catalog.live,
            { cache: "no-cache", signal: AbortSignal.timeout(3000) }).then((r) => r.json());
          const key = (i) => i.feed + "\n" + i.link + "\n" + (i.title || "").toLowerCase();
          const seen = new Set(catalog.items.map(key));
          const newer = (live.items || []).filter((i) => !seen.has(key(i)));
          catalog.items = newer.concat(catalog.items)
            .sort((a, b) => (b.date || "").localeCompare(a.date || ""));
        } catch (e) { /* the catalog as GitHub serves it */ }
      }
      const names = () => Object.fromEntries(catalog.feeds.map((f) => [f.name,
        f.title || f.name.replaceAll("-", " ")]));
      function show() {
        const words = q.value.trim().split(/\s+/).filter(Boolean).map(word);
        list.replaceChildren();
        if (!words.length) { status.textContent = ""; return; }
        const about = Object.fromEntries(
          catalog.feeds.map((f) => [f.name, f.name.replaceAll("-", " ")]));
        const hits = catalog.items.filter((i) => words.every((w) => w.test(
          (i.title || "") + " " + (i.summary || "") + " " + (about[i.feed] || "")))).slice(0, 50);
        status.textContent = hits.length ? hits.length + " result(s) among the latest items"
          : "Nothing among the latest items matches.";
        const title = names();
        for (const i of hits) {
          const li = document.createElement("li"), a = document.createElement("a");
          a.href = i.link || "#"; a.textContent = i.title || i.link; a.rel = "noopener";
          const meta = document.createElement("small");
          meta.textContent = (title[i.feed] || i.feed) + (i.date ? " · " + day(i.date) : "");
          li.append(a, meta);
          list.append(li);
        }
      }
      // Each feed's latest item and health, how fresh the catalog is, how far back it goes.
      load().then(() => {
        const seen = new Set();
        for (const i of catalog.items) {
          if (seen.has(i.feed)) continue;
          seen.add(i.feed);
          const slot = document.querySelector('[data-latest="' + i.feed + '"]');
          if (!slot) continue;
          const a = document.createElement("a");
          a.href = i.link || "#"; a.textContent = i.title || i.link; a.rel = "noopener";
          const when = document.createElement("span");
          when.textContent = " · " + day(i.date);
          slot.replaceChildren(a, when);
        }
        for (const f of catalog.feeds) {
          const note = document.querySelector('[data-health="' + f.name + '"]'), h = f.health;
          if (!note || !h || h.status === "ok") continue;
          note.textContent = (h.status === "partial" ? "some sources failing" : "failing")
            + " since " + day(h.since);
          note.classList.add("warn");
        }
        const modified = response && response.headers.get("last-modified");
        const updated = document.getElementById("stat-updated");
        if (modified && updated) {
          const minutes = Math.max(0, Math.round((Date.now() - Date.parse(modified)) / 60000));
          updated.textContent = minutes < 1 ? "just now" : minutes < 60 ? minutes + " min ago"
            : Math.round(minutes / 60) + " h ago";
        }
        if (!catalog.archive) return;
        return fetch(catalog.archive, FRESH).then((r) => r.json()).then((index) => {
          const total = index.months.reduce((n, m) => n + (m.items || 0), 0);
          const months = index.months.map((m) => m.month).sort();
          const stat = document.getElementById("stat-archive");
          if (stat && total) {
            stat.textContent = total.toLocaleString("en-US");
            document.getElementById("stat-since").textContent = " since " + months[0].slice(0, 4);
          }
        });
      }).catch(() => {});
      q.addEventListener("input", () => load().then(show).then(offer).catch(() => {
        status.textContent = "Search starts working after the next run writes feeds.json.";
      }));

      // The archive: every item the catalog ever listed, one file per month. Its word index
      // says which months hold a word, so a search reads a dozen months, not all of them.
      const deep = document.getElementById("deep");
      let months = null, entries = [], shards = null;
      const tables = {};
      // A word index's entries for words starting with some forms: from its small files by
      // first two letters ("words/ja.json") where the archive lists them, else the whole file.
      const shardOf = (w) => w.toLowerCase().slice(0, 2).replace(/[^a-z0-9]/g, "_")
        .padEnd(2, "_");
      async function wordTable(base, name, forms) {
        const get = (file) => tables[file] || (tables[file] = fetch(base + file)
          .then((r) => r.ok ? r.json() : {}).then((d) => d.words || {}).catch(() => ({})));
        if (!shards) return get(name + ".json");
        const wanted = [...new Set(forms.map(shardOf))].filter((s) => shards.has(s));
        const parts = await Promise.all(wanted.map((s) => get(name + "/" + s + ".json")));
        return Object.assign({}, ...parts);
      }
      const stem = (word) => {  // as UnlimitedPipe stems words (unlimitedpipe.sources.search)
        const w = word.toLowerCase();
        if (/(ss|us|is|ws)$/.test(w)) return w;
        if (w.endsWith("y") && w.length >= 5) return w.slice(0, -1);
        const endings = [["ies", ""], ["ing", ""], ["ed", ""], ["es", "e"], ["s", ""]];
        for (const [suffix, keep] of endings) {
          if (!w.endsWith(suffix)) continue;
          const base = w.slice(0, -suffix.length);
          const add = suffix === "es" && /(s|x|z|ch|sh)$/.test(base) ? "" : keep;
          if (base.length >= 4 || ((suffix === "s" || suffix === "es") && base.length >= 3)) {
            return base + add;
          }
        }
        return w;
      };
      const NAMES = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
        "nov", "dec"];
      function offer() {
        if (!deep || !catalog || !catalog.archive) return;
        deep.hidden = !q.value.trim();
      }
      async function searchArchive() {
        const base = catalog.archive.replace(/[^/]*$/, "");
        if (!months) {
          const index = await (await fetch(catalog.archive, FRESH)).json();
          entries = index.months;
          months = entries.map((m) => m.month);
          if (Array.isArray(index.shards)) shards = new Set(index.shards);
        }
        const asked = q.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
        let period = null;
        const terms = [];
        for (let n = 0; n < asked.length; n++) {
          const w = asked[n], month = NAMES.indexOf(w.slice(0, 3)), next = asked[n + 1];
          if (/^(19|20)\d\d$/.test(w)) period = (m) => m.startsWith(w);
          else if (month >= 0 && next && /^(19|20)\d\d$/.test(next) && w.length >= 3) {
            const key = next + "-" + String(month + 1).padStart(2, "0");
            period = (m) => m === key; n++;
          } else if (/^\d{4}-\d\d$/.test(w)) period = (m) => m === w;
          else terms.push(w);
        }
        let chosen = months.filter(period || (() => false)).sort().reverse();
        if (!period) {
          const words = await wordTable(base, "words",
            terms.filter((t) => t.length > 2).map(stem));
          const keys = Object.keys(words).filter((k) => !k.includes("@"));
          const sets = terms.filter((t) => t.length > 2).map((t) => {
            const s = stem(t), found = new Set();
            for (const k of keys) if (k.startsWith(s)) for (const m of words[k]) found.add(m);
            return found;
          }).filter((set) => set.size);
          // A word naming a feed ("ipo", "hack") narrows the others to that feed's months.
          const named = catalog.feeds.map((f) => f.name).filter((name) =>
            terms.some((t) => word(t).test(name.replaceAll("-", " "))));
          const inFeed = [];
          for (const t of terms) for (const name of named) {
            const months = words[stem(t) + "@" + name];
            if (months) inFeed.push(new Set(months));
          }
          const candidates = [...inFeed, ...sets.filter((set) => set.size <= 60)];
          if (!candidates.length) return [];
          const anchor = candidates.reduce((a, b) => (b.size < a.size ? b : a));
          chosen = [...anchor].sort((a, b) =>
            sets.filter((x) => x.has(b)).length - sets.filter((x) => x.has(a)).length
            || (a < b ? 1 : -1));
        }
        chosen = chosen.slice(0, 12);  // the months holding most of the words, then the newest
        const tests = terms.map(word);
        const about = Object.fromEntries(
          catalog.feeds.map((f) => [f.name, f.name.replaceAll("-", " ")]));
        // Read only the feeds that can hold the words, where the archive is split by feed.
        const wanted = {}, forms = terms.filter((t) => t.length > 2).map(stem);
        const byFeed = forms.length ? await wordTable(base, "words-by-feed", forms) : {};
        const byFeedKeys = Object.keys(byFeed);
        for (const k of byFeedKeys) {
          if (!forms.some((f) => k.startsWith(f))) continue;
          for (const [feed, ms] of Object.entries(byFeed[k])) {
            for (const m of ms) (wanted[m] = wanted[m] || new Set()).add(feed);
          }
        }
        const named = catalog.feeds.filter((f) => terms.some((t) => word(t).test(
          f.name.replaceAll("-", " ") + " " + (f.description || "")))).map((f) => f.name);
        // Months before the last two are compressed (2024-01.jsonl.gz), as the index names them.
        const whole = (m) => (entries.find((x) => x.month === m) || {}).file || m + ".jsonl";
        const files = (m) => {
          const e = entries.find((x) => x.month === m);
          const split = e && e.feeds;
          if (!split || !forms.length || !Object.keys(wanted).length
            || Object.values(split).reduce((a, b) => a + b, 0) !== e.items) return [whole(m)];
          const feeds = new Set([...(wanted[m] || []), ...named]);
          const ext = e.packed ? ".jsonl.gz" : ".jsonl";
          return Object.keys(split).filter((f) => feeds.has(f)).map((f) => m + "/" + f + ext);
        };
        const text = async (r) => {
          const bytes = new Uint8Array(await r.arrayBuffer());
          if (bytes[0] !== 0x1f || bytes[1] !== 0x8b) return new TextDecoder().decode(bytes);
          const opened = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
          return new Response(opened).text();
        };
        const found = [];
        const texts = await Promise.all(chosen.map(async (m) => {
          const parts = await Promise.all(files(m).map((file) => fetch(base + file)
            .then((r) => r.ok ? text(r) : null).catch(() => null)));
          return parts.includes(null) ? text(await fetch(base + whole(m))) : parts.join("");
        }));
        for (const text of texts) {
          for (const line of text.split("\n")) {
            if (!line) continue;
            const i = JSON.parse(line), hay = (i.title || "") + " " + (i.summary || "") + " "
              + (about[i.feed] || i.feed);
            if (tests.every((t) => t.test(hay))) found.push(i);
          }
        }
        return found.sort((a, b) => (b.date || "").localeCompare(a.date || "")).slice(0, 50);
      }
      // "Try" buttons: search for their words; one naming a year searches the archive too.
      for (const button of document.querySelectorAll(".try button")) {
        button.addEventListener("click", () => {
          q.value = button.dataset.q;
          q.dispatchEvent(new Event("input"));
          if (/\b(19|20)\d\d\b/.test(q.value) && deep) {
            load().then(() => deep.click());
          }
        });
      }
      if (deep) deep.addEventListener("click", () => {
        deep.hidden = true;
        status.textContent = "Searching the archive…";
        load().then(searchArchive).then((found) => {
          list.replaceChildren();
          status.textContent = found.length
            ? found.length + (found.length === 50 ? "+" : "") + " result(s) from the archive"
            : "Nothing in the archive matches.";
          const title = names();
          for (const i of found) {
            const li = document.createElement("li"), a = document.createElement("a");
            a.href = i.link || "#"; a.textContent = i.title || i.link; a.rel = "noopener";
            const meta = document.createElement("small");
            meta.textContent = (title[i.feed] || i.feed) + (i.date ? " · " + day(i.date) : "");
            li.append(a, meta);
            list.append(li);
          }
        }).catch(() => { status.textContent = "The archive could not be read."; });
      });
    </script>
"""


INDEX_MARKER = "<!-- generated by unlimited publish -->"


def _format_label(file: Path) -> str:
    return "RSS" if file.suffix == ".xml" else file.suffix.lstrip(".").upper() or file.name


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-") or "feeds"


def _readable(name: str) -> str:
    small = {"ai": "AI", "sec": "SEC", "us": "US", "eu": "EU", "un": "UN", "hn": "HN"}
    words = [small.get(w, w) for w in name.split("-")]
    return " ".join([words[0][:1].upper() + words[0][1:], *words[1:]])


INDEX_STYLE = """
      :root { --bg: #f6f7f9; --card: #ffffff; --ink: #15181d; --muted: #5a6270;
        --line: #e2e5ea; --accent: #0f766e; --accent-ink: #ffffff; --live: #b42318;
        --pill: #eef1f4; color-scheme: light; }
      @media (prefers-color-scheme: dark) {
        :root:not([data-theme="light"]) { --bg: #0e1116; --card: #161a21; --ink: #e7e9ee;
          --muted: #9aa3b2; --line: #262c36; --accent: #2dd4bf; --accent-ink: #062521;
          --live: #f97066; --pill: #1f2530; color-scheme: dark; }
      }
      :root[data-theme="dark"] { --bg: #0e1116; --card: #161a21; --ink: #e7e9ee;
        --muted: #9aa3b2; --line: #262c36; --accent: #2dd4bf; --accent-ink: #062521;
        --live: #f97066; --pill: #1f2530; color-scheme: dark; }
      * { box-sizing: border-box; }
      body { margin: 0; background: var(--bg); color: var(--ink);
        font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
        padding-inline: 16px; }
      a { color: var(--accent); }
      .wrap { max-width: 72rem; margin: 0 auto; }
      .top { display: flex; flex-wrap: wrap; gap: .5rem 1.5rem; align-items: center;
        justify-content: space-between; padding-block: 1rem;
        border-bottom: 1px solid var(--line); }
      .brand { font-weight: 700; letter-spacing: -.01em; color: var(--ink); text-decoration: none; }
      .top nav { display: flex; flex-wrap: wrap; gap: .25rem 1rem; font-size: .95rem; }
      .top nav a { color: var(--muted); text-decoration: none; }
      .top nav a:hover { color: var(--ink); }
      .hero { padding-block: 2.5rem 1.5rem; max-width: 46rem; }
      h1 { font-size: clamp(1.9rem, 4vw, 2.6rem); line-height: 1.15; margin: 0 0 .75rem;
        letter-spacing: -.02em; text-wrap: balance; }
      .lede { color: var(--muted); font-size: 1.1rem; margin: 0 0 1.25rem; }
      .stats { display: flex; flex-wrap: wrap; gap: .5rem 1.75rem; list-style: none;
        padding: 0; margin: 0 0 1.5rem; color: var(--muted); font-variant-numeric: tabular-nums; }
      .stats b { color: var(--ink); font-size: 1.15rem; }
      #q { width: 100%; font: inherit; font-size: 1.05rem; padding: .8rem 1rem;
        border: 1px solid var(--line); border-radius: 10px; background: var(--card);
        color: var(--ink); }
      #q:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
      #status { color: var(--muted); font-size: .9rem; margin: .5rem 0 0; }
      #status:empty, #results:empty { display: none; }
      #deep { margin-top: .6rem; font: inherit; font-size: .9rem; font-weight: 600;
        color: var(--accent-ink); background: var(--accent); border: 0; border-radius: 8px;
        padding: .45rem .9rem; cursor: pointer; }
      #deep[hidden] { display: none; }
      #results { list-style: none; padding: 0; margin: .5rem 0 0; }
      #results li { padding: .55rem 0; border-bottom: 1px solid var(--line); }
      #results small { display: block; color: var(--muted); }
      .toc { display: flex; flex-wrap: wrap; gap: .5rem; padding-block: .5rem 0; }
      .toc a { background: var(--pill); color: var(--ink); text-decoration: none;
        padding: .3rem .75rem; border-radius: 999px; font-size: .9rem; }
      .group { padding-block: 2rem .5rem; }
      .group h2 { font-size: 1.25rem; margin: 0 0 1rem; letter-spacing: -.01em; }
      .grid { display: grid; gap: 1rem;
        grid-template-columns: repeat(auto-fill, minmax(min(19rem, 100%), 1fr)); }
      .card { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
        padding: 1rem 1.1rem; display: flex; flex-direction: column; gap: .5rem; min-width: 0; }
      .card h3 { font-size: 1.02rem; margin: 0; display: flex; gap: .5rem; align-items: baseline;
        justify-content: space-between; }
      .live { color: var(--live); font-size: .72rem; font-weight: 700; letter-spacing: .06em;
        text-transform: uppercase; white-space: nowrap; }
      .desc { color: var(--muted); font-size: .93rem; margin: 0; }
      .latest { font-size: .9rem; margin: 0; overflow-wrap: anywhere; }
      .latest:empty { display: none; }
      .latest::before { content: "Latest"; display: block; color: var(--muted); font-size: .7rem;
        font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }
      .latest a { color: var(--ink); text-decoration: none; }
      .latest a:hover { text-decoration: underline; }
      .latest span { color: var(--muted); }
      .card footer { margin-top: auto; display: flex; flex-wrap: wrap; gap: .4rem;
        align-items: center; font-size: .85rem; }
      .pill { background: var(--pill); color: var(--ink); text-decoration: none;
        padding: .15rem .6rem; border-radius: 6px; font-weight: 600; font-size: .8rem; }
      .warn { color: var(--live); }
      .try { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem;
        margin: .6rem 0 0; color: var(--muted); font-size: .88rem; }
      .try button { font: inherit; font-size: .85rem; color: var(--ink); background: var(--pill);
        border: 0; border-radius: 999px; padding: .25rem .7rem; cursor: pointer; }
      .try button:hover { outline: 1px solid var(--accent); }
      .use { display: grid; gap: 1rem 2rem;
        grid-template-columns: repeat(auto-fit, minmax(min(16rem, 100%), 1fr));
        padding-block: 2.5rem; border-top: 1px solid var(--line); margin-top: 2rem; }
      .use h2 { font-size: 1rem; margin: 0 0 .4rem; }
      .use p { margin: 0; color: var(--muted); font-size: .93rem; }
      code { background: var(--pill); padding: .05rem .35rem; border-radius: 4px;
        font-size: .88em; }
      .foot { color: var(--muted); font-size: .85rem; padding-block: 1.5rem 3rem;
        border-top: 1px solid var(--line); }
"""


def index_page(p: PublishPlan, every: str) -> str:
    esc = html.escape
    order = list(dict.fromkeys([*p.groups, *sorted({i.group for i in p.pipelines if i.group})]))
    grouped: dict[str, list[Published]] = {g: [] for g in order}
    for item in p.pipelines:
        grouped.setdefault(item.group or "More feeds", []).append(item)
    lanes = {Path(path).as_posix() for path in p.express}
    sections, toc = [], []
    for group, items in grouped.items():
        if not items:
            continue
        cards = []
        for item in items:
            pills = "".join(
                f'<a class="pill" href="{esc(f.as_posix())}">{esc(_format_label(f))}</a>'
                for f in item.files
            )
            live = (
                '<span class="live" title="Refreshed in the express lane">Live</span>'
                if item.path.as_posix() in lanes
                else ""
            )
            about = f'<p class="desc">{esc(item.description)}</p>' if item.description else ""
            cards.append(
                f'        <article class="card" id="feed-{esc(item.name)}">\n'
                f"          <h3>{esc(item.title or _readable(item.name))}{live}</h3>\n"
                f"          {about}\n"
                f'          <p class="latest" data-latest="{esc(item.name)}"></p>\n'
                f'          <footer>{pills}<span data-health="{esc(item.name)}"></span></footer>\n'
                "        </article>"
            )
        slug = _slug(group)
        toc.append(f'<a href="#{slug}">{esc(group)}</a>')
        sections.append(
            f'    <section class="group" id="{slug}">\n      <h2>{esc(group)}</h2>\n'
            f'      <div class="grid">\n' + "\n".join(cards) + "\n      </div>\n    </section>"
        )
    title = esc(p.title or p.name)
    about = f'\n      <p class="lede">{esc(p.about)}</p>' if p.about else ""
    links = "".join(f'<a href="{esc(url)}">{esc(label)}</a>' for label, url in p.links)
    tries = ""
    if p.examples:
        buttons = "".join(
            f'<button type="button" data-q="{esc(text)}">{esc(text)}</button>'
            for text in p.examples
        )
        tries = f'      <p class="try">Try {buttons}</p>\n'
    fast = ""
    if p.express and p.express_every:
        from unlimitedpipe.watch import format_duration

        fast = f"<li><b>{len(p.express)}</b> live feeds</li>"
        every = f"{every} (live feeds: {format_duration(p.express_every)})"
    return f"""\
<!doctype html>
{INDEX_MARKER}
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <title>{title}</title>
    <meta name="description" content="{esc(p.about or title)}">
    <link rel="alternate" type="application/json" href="feeds.json" title="Feed catalog">
    <style>{INDEX_STYLE}    </style>
  </head>
  <body>
    <div class="wrap">
    <header class="top"><a class="brand" href="./">{title}</a><nav>{links}</nav></header>
    <section class="hero">
      <h1>{title}</h1>{about}
      <ul class="stats">
        <li><b>{len(p.pipelines)}</b> feeds</li>{fast}
        <li><b id="stat-archive">…</b> records<span id="stat-since"></span></li>
        <li>updated <b id="stat-updated">…</b></li>
      </ul>
      <input id="q" type="search" placeholder="Search the latest items: flood, bankruptcy, Bangkok…"
        autocomplete="off" aria-label="Search every feed">
{tries}      <p id="status"></p>
      <button id="deep" type="button" hidden>Search every past record, not only the latest</button>
      <ul id="results"></ul>
    </section>
    <nav class="toc" aria-label="Topics">{"".join(toc)}</nav>
{chr(10).join(sections)}
    <section class="use">
      <div><h2>Subscribe</h2><p>Every feed is RSS for any feed reader and JSON for code.
        Each item links to the record it comes from.</p></div>
      <div><h2>Search and ask</h2><p><code>pip install unlimitedpipe</code>, then
        <code>unlimited search WORDS</code> or <code>unlimited ask "QUESTION"</code>, with a
        local model and every answer cited.</p></div>
      <div><h2>Follow</h2><p><code>unlimited follow earthquake japan --to ntfy:TOPIC</code>
        sends each new match to your phone (the free ntfy app, no account), or to Telegram,
        Discord, Slack or any webhook.</p></div>
      <div><h2>History</h2><p>Every item goes into a monthly archive,
        <a href="{esc("archive/index.json")}">archive/index.json</a>, so questions about a year or a
        month reach back. Runs every {esc(every)}.</p></div>
    </section>
    <footer class="foot">Built with <a href="https://github.com/Fuyuki0/unlimitedpipe">UnlimitedPipe</a>,
      open source: no server, no account, no tracking. Items come from public records and news,
      each with a link to its source; nothing here is investment, legal or medical advice.</footer>
    </div>
{SEARCH_SCRIPT}  </body>
</html>
"""
