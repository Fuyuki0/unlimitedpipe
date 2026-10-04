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
    headline: str | None = None  # the index page's big line (default: the title)
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
      let catalog = null, response = null, pastTimer = null;
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
        // nothing recent ("hurricane katrina"): the archive, once the typing stops
        clearTimeout(pastTimer);
        if (!hits.length && deep && catalog.archive) {
          const asked = q.value;
          status.textContent += " Searching the archive…";
          pastTimer = setTimeout(() => { if (q.value === asked) deep.click(); }, 700);
        }
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
      // "/" goes to the search box, as on many sites.
      document.addEventListener("keydown", (e) => {
        if (e.key === "/" && document.activeElement !== q
          && !/^(input|textarea|select)$/i.test(document.activeElement.tagName)) {
          e.preventDefault(); q.focus();
        }
      });
      // The newest items across every feed, for the "Just in" desk.
      function wire() {
        const box = document.getElementById("wire");
        if (!box) return;
        const title = names(), now = Date.now();
        const ago = (iso) => {
          const minutes = Math.round((now - Date.parse(iso)) / 60000);
          if (!(minutes >= 0)) return day(iso);
          return minutes < 60 ? minutes + " min ago" : minutes < 1440
            ? Math.round(minutes / 60) + " h ago" : day(iso);
        };
        const titles = new Set();  // one story once, though a live copy sends it again
        const newest = catalog.items.filter((i) => i.date && Date.parse(i.date) <= now + 6e4
          && !titles.has(i.title) && titles.add(i.title)).slice(0, 6);
        box.replaceChildren(...newest.map((i) => {
          const li = document.createElement("li"), a = document.createElement("a");
          a.href = i.link || "#"; a.textContent = i.title || i.link; a.rel = "noopener";
          const meta = document.createElement("small");
          meta.textContent = ago(i.date) + " · " + (title[i.feed] || i.feed);
          li.append(a, meta);
          if (typeof PAGE !== "undefined") li.style.setProperty("--c", colorOf(topicOf(i.feed)));
          return li;
        }));
      }
      // Each feed's latest item and health, how fresh the catalog is, how far back it goes.
      load().then(() => {
        wire();
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
          // a feed of rare events (big liquidations, fee spikes) can run fine and list nothing
          const empty = document.querySelector('[data-latest="' + f.name + '"]');
          if (empty && !seen.has(f.name) && (!f.health || f.health.status === "ok")) {
            const quiet = document.createElement("span");
            quiet.textContent = "Quiet: nothing over its bar yet";
            empty.replaceChildren(quiet);
          }
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


DASH_SCRIPT = r"""    <script>
      // The dashboard: charts from the archive's own counts (archive/days.json for the last
      // weeks, archive/index.json for every year), topic tiles, and the feed browser.
      const PAGE = JSON.parse(document.getElementById("page-data").textContent);
      const topicOf = (feed) => PAGE.feeds[feed] || "";
      const colorOf = (slug) => (PAGE.topics.find((t) => t.slug === slug) || {}).color
        || "var(--c9)";
      const nameOf = (slug) => (PAGE.topics.find((t) => t.slug === slug) || {}).name || "Other";
      const SVG = "http://www.w3.org/2000/svg";
      const el = (tag, attrs) => {
        const node = document.createElementNS(SVG, tag);
        for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
        return node;
      };
      const fmt = (n) => Math.round(n).toLocaleString("en-US");
      const nice = (max) => {  // a round top for an axis: 1, 2 or 5 times a power of ten
        if (max <= 0) return 1;
        const p = 10 ** Math.floor(Math.log10(max)), f = max / p;
        return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
      };
      // Stacked bars: one bar per label, one segment per topic; hovering a bar says its numbers.
      function stacked(svg, labels, stacks, { tick, readout, log }) {
        // drawn at the width it is shown at, so its text stays readable on a phone
        const H = +svg.getAttribute("viewBox").split(" ")[3];
        const W = Math.max(300, Math.round(svg.getBoundingClientRect().width) || 640);
        svg.setAttribute("viewBox", "0 0 " + W + " " + H);
        const left = 44, bottom = 18, top = 6, plot = H - bottom - top, wide = W - left;
        const totals = stacks.map((s) => Object.values(s).reduce((a, b) => a + b, 0));
        const step = wide / labels.length;
        // a log scale shows 7 records in 1860 beside 200,000 in 2025: each bar is as tall as
        // its total on that scale, split among its topics in proportion
        const decades = Math.max(1, Math.ceil(Math.log10(Math.max(10, ...totals))));
        const max = log ? 10 ** decades : nice(Math.max(1, ...totals));
        const height = (v) => log ? (v > 0 ? plot * Math.log10(1 + v) / decades : 0)
          : (plot * v) / max;
        const marks = log ? Array.from({ length: decades + 1 }, (_, g) => 10 ** g)
          : [0, 1, 2, 3, 4].map((g) => (max * g) / 4);
        svg.replaceChildren();
        for (const m of marks) {
          const y = top + plot - (log ? (plot * Math.log10(m)) / decades : (plot * m) / max);
          svg.append(el("line", { x1: left, x2: W, y1: y, y2: y, class: "gridline" }));
          const t = el("text", { x: left - 6, y: y + 3, "text-anchor": "end" });
          t.textContent = m >= 1e6 ? +(m / 1e6).toFixed(1) + "M"
            : m >= 1000 ? +(m / 1000).toFixed(2) + "k" : fmt(m);
          svg.append(t);
        }
        const order = PAGE.topics.map((t) => t.slug).concat([""]);
        labels.forEach((label, n) => {
          let y = top + plot;
          const bar = el("g"), whole = height(totals[n]);
          for (const slug of order) {
            const v = stacks[n][slug] || 0;
            if (!v) continue;
            const h = (whole * v) / totals[n];
            y -= h;
            bar.append(el("rect", { x: left + n * step + step * .12, y, width: step * .76,
              height: Math.max(h, .5), fill: colorOf(slug), rx: Math.min(2, step / 4) }));
          }
          const hit = el("rect", { x: left + n * step, y: top, width: step, height: plot,
            fill: "transparent" });
          const say = () => {
            const parts = order.filter((slug) => stacks[n][slug])
              .sort((a, b) => stacks[n][b] - stacks[n][a]).slice(0, 4)
              .map((slug) => nameOf(slug) + " " + fmt(stacks[n][slug]));
            readout.textContent = label + ": " + fmt(totals[n]) + (parts.length
              ? " — " + parts.join(", ") : "");
          };
          hit.addEventListener("mouseenter", say);
          hit.addEventListener("click", say);
          bar.append(hit);
          svg.append(bar);
          if (tick(label, n)) {
            const t = el("text", { x: left + n * step + step / 2, y: H - 4,
              "text-anchor": "middle" });
            t.textContent = tick(label, n);
            svg.append(t);
          }
        });
      }
      const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
        "Nov", "Dec"];
      const isoDay = (d) => d.toISOString().slice(0, 10);
      function lastDays(count) {
        const out = [], now = new Date();
        for (let n = count - 1; n >= 0; n--) out.push(isoDay(new Date(now - n * 864e5)));
        return out;
      }
      function legend() {
        const box = document.getElementById("legend");
        if (!box) return;
        box.replaceChildren(...PAGE.topics.map((t) => {
          const span = document.createElement("span"), i = document.createElement("i");
          span.style.setProperty("--c", t.color);
          span.append(i, t.name);
          return span;
        }));
      }
      async function dashboard() {
        await load();
        if (!catalog.archive) return;
        const base = catalog.archive.replace(/[^/]*$/, "");
        const [days, index] = await Promise.all([
          fetch(base + "days.json", FRESH).then((r) => r.ok ? r.json() : { days: {} })
            .then((d) => d.days || {}).catch(() => ({})),
          fetch(catalog.archive, FRESH).then((r) => r.json()).catch(() => ({ months: [] })),
        ]);
        const byTopic = (feeds) => {
          const out = {};
          for (const [feed, n] of Object.entries(feeds || {})) {
            const slug = topicOf(feed);
            out[slug] = (out[slug] || 0) + n;
          }
          return out;
        };
        // the last 30 days
        const span = lastDays(30), dayStacks = span.map((d) => byTopic(days[d]));
        stacked(document.getElementById("chart-days"), span, dayStacks, {
          readout: document.getElementById("days-readout"),
          tick: (d, n) => n % 5 === 0 || n === span.length - 1
            ? MONTHS[+d.slice(5, 7) - 1] + " " + +d.slice(8) : "",
        });
        legend();
        const recent = lastDays(2).map((d) => byTopic(days[d]));
        const sum = (s) => Object.values(s).reduce((x, y) => x + y, 0);
        const newCount = recent.reduce((a, s) => a + sum(s), 0);
        const stat = document.getElementById("stat-new");
        if (stat) stat.textContent = fmt(newCount);
        // each topic's tile: new in 24 hours and a line of its last 14 days
        const two = lastDays(14);
        for (const t of PAGE.topics) {
          const slot = document.querySelector('[data-new="' + t.slug + '"]');
          if (slot) slot.textContent = fmt(recent.reduce((a, s) => a + (s[t.slug] || 0), 0));
          const svg = document.querySelector('[data-spark="' + t.slug + '"]');
          if (!svg) continue;
          const values = two.map((d) => byTopic(days[d])[t.slug] || 0);
          const top = Math.max(1, ...values);
          const pts = values.map((v, n) => [(n * 140) / (values.length - 1), 26 - (v / top) * 24]);
          const line = pts.map(([x, y], n) => (n ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1))
            .join(" ");
          svg.replaceChildren(
            el("path", { d: line + " L140 28 L0 28 Z", fill: t.color, opacity: ".12" }),
            el("path", { d: line, fill: "none", stroke: t.color, "stroke-width": "2",
              "vector-effect": "non-scaling-stroke" }));
        }
        // every year in the archive
        const years = {};
        for (const m of index.months || []) {
          const y = String(m.month).slice(0, 4), add = m.feeds ? byTopic(m.feeds)
            : { "": m.items || 0 };
          const into = (years[y] = years[y] || {});
          for (const [k, v] of Object.entries(add)) into[k] = (into[k] || 0) + v;
        }
        const keys = Object.keys(years).sort();
        if (keys.length) {
          const all = [];
          for (let y = +keys[0]; y <= +keys[keys.length - 1]; y++) all.push(String(y));
          stacked(document.getElementById("chart-years"), all, all.map((y) => years[y] || {}), {
            readout: document.getElementById("years-readout"), log: true,
            tick: (y, n) => (+y % 25 === 0 && n < all.length - 8) || n === all.length - 1 ? y : "",
          });
          const note = document.getElementById("years-note");
          if (note) note.textContent = keys[0] + " to " + keys[keys.length - 1]
            + ", on a log scale; hover a bar for its numbers";
        }
      }
      dashboard().catch(() => {});

      // The feed browser: a topic, words to match, live feeds only.
      const tabs = [...document.querySelectorAll(".tabs button")];
      const filter = document.getElementById("filter");
      const liveOnly = document.getElementById("live-only");
      let topic = "";
      const opened = new Set();  // topics whose every feed is shown
      const FIRST = matchMedia("(max-width: 40rem)").matches ? 3 : 6;
      function browse() {
        const words = (filter.value || "").toLowerCase().split(/\s+/).filter(Boolean);
        // with nothing picked, each topic shows its first feeds, so the page stays short
        const brief = !topic && !words.length && !liveOnly.checked;
        let shown = 0;
        for (const group of document.querySelectorAll(".group")) {
          let inGroup = 0, n = 0;
          const all = !brief || opened.has(group.dataset.topic);
          for (const card of group.querySelectorAll(".card")) {
            const ok = (!topic || group.dataset.topic === topic)
              && words.every((w) => card.dataset.words.includes(w))
              && (!liveOnly.checked || card.hasAttribute("data-live"));
            card.hidden = !ok || (!all && n >= FIRST);
            n += ok;
            inGroup += ok;
          }
          group.hidden = !inGroup;
          const more = group.querySelector(".more");
          if (more) more.hidden = all || inGroup <= FIRST;
          shown += inGroup;
        }
        document.getElementById("no-feeds").hidden = shown > 0;
        for (const b of [...tabs, ...document.querySelectorAll(".tile")]) {
          b.setAttribute("aria-pressed", String(b.dataset.topic === topic && (b.dataset.topic
            || b.closest(".tabs"))));
        }
      }
      const choose = (slug) => { topic = slug; browse(); };
      for (const b of tabs) b.addEventListener("click", () => choose(b.dataset.topic));
      for (const more of document.querySelectorAll(".group .more")) {
        more.addEventListener("click", () => {
          opened.add(more.closest(".group").dataset.topic);
          browse();
        });
      }
      for (const tile of document.querySelectorAll(".tile")) {
        tile.addEventListener("click", () => {
          choose(tile.dataset.topic);
          document.querySelector(".browse").scrollIntoView({ behavior: "smooth" });
        });
      }
      filter.addEventListener("input", browse);
      liveOnly.addEventListener("change", browse);
      // A link to a feed (#feed-earthquakes, as health alerts send): show it, whatever is chosen.
      function reveal() {
        const card = location.hash.startsWith("#feed-")
          && document.getElementById(location.hash.slice(1));
        if (!card) return;
        topic = ""; filter.value = ""; liveOnly.checked = false;
        opened.add(card.closest(".group").dataset.topic);
        browse();
        card.scrollIntoView({ block: "center" });
      }
      window.addEventListener("hashchange", reveal);
      browse();
      reveal();
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
      /* A control room for public records: calm navy surfaces, one colour per topic, numbers
         that line up. System fonts only: the page loads nothing from anyone else. */
      :root { --bg: #f2f4f8; --card: #ffffff; --ink: #0f1729; --muted: #5b6579;
        --line: #e1e6ef; --accent: #4338ca; --accent-ink: #ffffff; --live: #e11d48;
        --pill: #eef1f7; --link: #3730a3; --shade: 0 1px 2px rgba(15, 23, 41, .06),
          0 4px 16px rgba(15, 23, 41, .05); --grid: #e9edf4;
        --c0: #4e79a7; --c1: #e15759; --c2: #f28e2b; --c3: #59a14f; --c4: #b07aa1;
        --c5: #edc948; --c6: #76b7b2; --c7: #9c755f; --c8: #ff9da7; --c9: #8b8f99;
        color-scheme: light;
        --serif: var(--sans);
        --sans: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
        --mono: ui-monospace, "SF Mono", "Cascadia Mono", "Segoe UI Mono", Menlo, Consolas,
          monospace; }
      @media (prefers-color-scheme: dark) {
        :root:not([data-theme="light"]) { --bg: #0a0f1c; --card: #111a2c; --ink: #e7ebf3;
          --muted: #96a1b6; --line: #1f2a40; --accent: #8b8cff; --accent-ink: #0a0f1c;
          --live: #ff5d7a; --pill: #18233a; --link: #a5b4fc; --grid: #1a2438;
          --shade: 0 1px 2px rgba(0, 0, 0, .4), 0 6px 20px rgba(0, 0, 0, .25);
          --c0: #78a6d9; --c1: #ff7b7d; --c2: #ffa85a; --c3: #7fc96f; --c4: #d39ec5;
          --c5: #f5d76e; --c6: #93d3cd; --c7: #c39b84; --c8: #ffb8c0; --c9: #a4a9b4;
          color-scheme: dark; }
      }
      :root[data-theme="dark"] { --bg: #0a0f1c; --card: #111a2c; --ink: #e7ebf3;
        --muted: #96a1b6; --line: #1f2a40; --accent: #8b8cff; --accent-ink: #0a0f1c;
        --live: #ff5d7a; --pill: #18233a; --link: #a5b4fc; --grid: #1a2438;
        --shade: 0 1px 2px rgba(0, 0, 0, .4), 0 6px 20px rgba(0, 0, 0, .25);
        --c0: #78a6d9; --c1: #ff7b7d; --c2: #ffa85a; --c3: #7fc96f; --c4: #d39ec5;
        --c5: #f5d76e; --c6: #93d3cd; --c7: #c39b84; --c8: #ffb8c0; --c9: #a4a9b4;
        color-scheme: dark; }
      * { box-sizing: border-box; }
      html { scroll-padding-top: 1rem; }
      body { margin: 0; background: var(--bg); color: var(--ink);
        font: 15px/1.55 var(--sans); padding-inline: 16px; }
      a { color: var(--link); text-underline-offset: .15em; }
      .wrap { max-width: 78rem; margin: 0 auto; }
      .top { display: flex; flex-wrap: wrap; gap: .5rem 1.5rem; align-items: center;
        justify-content: space-between; padding-block: 1rem; }
      .brand { font-weight: 750; font-size: 1.05rem; letter-spacing: -.01em; color: var(--ink);
        text-decoration: none; display: inline-flex; gap: .55rem; align-items: center; }
      .brand::before { content: ""; width: 1.4rem; height: 1.4rem; border-radius: 6px;
        background: conic-gradient(from 200deg, var(--c0), var(--c3), var(--c6), var(--c2),
          var(--c1), var(--c0)); }
      .top nav { display: flex; flex-wrap: wrap; gap: .25rem 1.1rem; font-size: .9rem; }
      .top nav a { color: var(--muted); text-decoration: none; }
      .top nav a:hover { color: var(--ink); }
      .hero { padding-block: 2rem 1rem; max-width: 50rem; }
      .kicker { font: 600 .72rem/1.5 var(--mono); letter-spacing: .12em; text-transform: uppercase;
        color: var(--accent); margin: 0 0 .7rem; }
      h1 { font-size: clamp(1.9rem, 4.4vw, 2.9rem); line-height: 1.08; font-weight: 800;
        margin: 0 0 .8rem; letter-spacing: -.03em; text-wrap: balance; }
      .lede { color: var(--muted); font-size: 1.05rem; margin: 0 0 1.2rem; max-width: 44rem; }
      .find { position: relative; }
      #q { width: 100%; font: inherit; font-size: 1.05rem; padding: .85rem 3rem .85rem 1rem;
        border: 1px solid var(--line); border-radius: 12px; background: var(--card);
        color: var(--ink); box-shadow: var(--shade); }
      #q:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
      .find kbd { position: absolute; right: .8rem; top: 50%; translate: 0 -50%;
        font: .76rem var(--mono); color: var(--muted); border: 1px solid var(--line);
        border-radius: 5px; padding: .05rem .4rem; pointer-events: none; }
      @media (pointer: coarse) { .find kbd { display: none; } #q { padding-right: 1rem; } }
      #status { color: var(--muted); font-size: .88rem; margin: .6rem 0 0; }
      #status:empty, #results:empty { display: none; }
      #deep { margin-top: .6rem; font: inherit; font-size: .88rem; font-weight: 600;
        color: var(--accent-ink); background: var(--accent); border: 0; border-radius: 8px;
        padding: .45rem .9rem; cursor: pointer; }
      #deep[hidden] { display: none; }
      #results { list-style: none; padding: 0; margin: .6rem 0 0; background: var(--card);
        border: 1px solid var(--line); border-radius: 12px; box-shadow: var(--shade); }
      #results li { padding: .65rem 1rem; border-bottom: 1px solid var(--line); }
      #results li:last-child { border-bottom: 0; }
      #results a, .wire a, .latest a { color: var(--ink); text-decoration: none; }
      #results a:hover, .wire a:hover, .latest a:hover { color: var(--link);
        text-decoration: underline; }
      #results small, .wire small { display: block; color: var(--muted);
        font: .76rem var(--mono); margin-top: .15rem; }
      .try { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem;
        margin: .75rem 0 0; color: var(--muted); font-size: .86rem; }
      .try button { font: inherit; font-size: .83rem; color: var(--ink); background: var(--card);
        border: 1px solid var(--line); border-radius: 999px; padding: .22rem .7rem;
        cursor: pointer; }
      .try button:hover { border-color: var(--accent); color: var(--accent); }
      .kpis { display: grid; gap: .8rem; margin-block: 1.2rem;
        grid-template-columns: repeat(auto-fit, minmax(min(9rem, 100%), 1fr)); }
      @media (max-width: 40rem) { .kpi b { font-size: 1.35rem; } .kpi small { font-size: .74rem; } }
      .kpi { background: var(--card); border: 1px solid var(--line); border-radius: 14px;
        padding: .9rem 1.1rem; box-shadow: var(--shade); min-width: 0; }
      .kpi span { display: block; color: var(--muted); font-size: .78rem; font-weight: 600;
        letter-spacing: .04em; text-transform: uppercase; }
      .kpi b { display: block; font-size: 1.65rem; font-weight: 800; letter-spacing: -.02em;
        font-variant-numeric: tabular-nums; margin-top: .15rem; }
      .kpi small { color: var(--muted); font-size: .8rem; }
      .dash { display: grid; gap: 1rem; margin-block: 1rem; align-items: start; }
      @media (min-width: 64rem) {
        .dash { grid-template-columns: minmax(0, 1.65fr) minmax(0, 1fr); } }
      .panel { background: var(--card); border: 1px solid var(--line); border-radius: 14px;
        padding: 1rem 1.15rem 1.1rem; box-shadow: var(--shade); min-width: 0; }
      .panel h2 { font-size: .95rem; font-weight: 700; margin: 0; display: flex; gap: .5rem;
        align-items: center; justify-content: space-between; flex-wrap: wrap; }
      .panel h2 small { color: var(--muted); font-weight: 500; font-size: .8rem; }
      .panel .note { color: var(--muted); font-size: .8rem; margin: .2rem 0 .6rem; }
      .chart { width: 100%; height: auto; display: block; overflow: visible; }
      .chart text { fill: var(--muted); font: 10px var(--mono); }
      .chart .gridline { stroke: var(--grid); stroke-width: 1; }
      .chart rect:hover { opacity: .75; }
      .legend { display: flex; flex-wrap: wrap; gap: .3rem .9rem; margin-top: .6rem;
        font-size: .78rem; color: var(--muted); }
      .legend span { display: inline-flex; gap: .35rem; align-items: center; }
      .legend i { width: .65rem; height: .65rem; border-radius: 3px; background: var(--c); }
      .readout { min-height: 1.2rem; font: .78rem var(--mono); color: var(--ink);
        margin-top: .3rem; }
      .wire { list-style: none; padding: 0; margin: .4rem 0 0; }
      .wire li { padding: .5rem 0 .5rem .7rem; border-top: 1px solid var(--line);
        overflow-wrap: anywhere; position: relative; font-size: .9rem; }
      .wire li::before { content: ""; position: absolute; left: 0; top: .75rem; width: .3rem;
        height: .3rem; border-radius: 50%; background: var(--c, var(--accent)); }
      .wire li:first-child { border-top: 0; }
      .wire a { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
        overflow: hidden; }
      .wire small { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .topics { padding-block: 1.5rem .5rem; }
      .topics > h2, .browse > h2 { font-size: 1.3rem; font-weight: 800; letter-spacing: -.02em;
        margin: 0 0 .8rem; }
      .tiles { display: grid; gap: .7rem;
        grid-template-columns: repeat(auto-fill, minmax(min(14.5rem, 100%), 1fr)); }
      .tile { font: inherit; text-align: left; color: var(--ink); background: var(--card);
        border: 1px solid var(--line); border-radius: 14px; padding: .8rem .95rem;
        cursor: pointer; box-shadow: var(--shade); display: grid; gap: .25rem;
        border-top: 4px solid var(--c); min-width: 0; }
      .tile:hover, .tile[aria-pressed="true"] { outline: 2px solid var(--c); }
      .tile b { font-size: .98rem; }
      .tile small { color: var(--muted); font-size: .8rem; font-variant-numeric: tabular-nums; }
      .tile svg { width: 100%; height: 28px; display: block; }
      .browse { padding-block: 1.5rem 1rem; }
      .toolbar { position: sticky; top: env(safe-area-inset-top, 0px); z-index: 3;
        background: var(--bg); padding-block: .6rem; display: flex; flex-wrap: wrap;
        gap: .5rem; align-items: center; border-bottom: 1px solid var(--line);
        margin-bottom: 1rem; }
      .tabs { display: flex; gap: .35rem; overflow-x: auto; scrollbar-width: none; flex: 1 1 30rem;
        min-width: 0; }
      .tabs button { flex: none; font: inherit; font-size: .84rem; color: var(--ink);
        background: var(--card); border: 1px solid var(--line); border-radius: 999px;
        padding: .3rem .8rem; cursor: pointer; display: inline-flex; gap: .4rem;
        align-items: center; }
      .tabs button i { width: .55rem; height: .55rem; border-radius: 50%; background: var(--c); }
      .tabs button[aria-pressed="true"] { background: var(--ink); color: var(--bg);
        border-color: var(--ink); }
      #filter { font: inherit; font-size: .88rem; padding: .4rem .8rem; border-radius: 999px;
        border: 1px solid var(--line); background: var(--card); color: var(--ink);
        flex: 0 1 15rem; min-width: 0; }
      .toolbar label { font-size: .84rem; color: var(--muted); display: inline-flex; gap: .3rem;
        align-items: center; }
      .group { padding-block: .5rem 1rem; }
      .group[hidden] { display: none; }
      .group h2 { font-size: 1.05rem; font-weight: 750; margin: 0 0 .7rem; display: flex;
        gap: .5rem; align-items: center; }
      .group h2::before { content: ""; width: .7rem; height: .7rem; border-radius: 3px;
        background: var(--c); }
      .group h2 small { font-size: .8rem; color: var(--muted); font-weight: 500; }
      .grid { display: grid; gap: .7rem;
        grid-template-columns: repeat(auto-fill, minmax(min(21rem, 100%), 1fr)); }
      .card { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
        padding: .8rem .95rem; display: flex; flex-direction: column; gap: .45rem; min-width: 0;
        border-left: 4px solid var(--c, var(--accent)); scroll-margin-top: 5rem; }
      .card[hidden] { display: none; }
      .card:target { outline: 2px solid var(--accent); outline-offset: 2px; }
      .card h3 { font-size: .97rem; font-weight: 700; margin: 0; display: flex; gap: .5rem;
        align-items: baseline; justify-content: space-between; line-height: 1.3; }
      .card h3 a { color: inherit; text-decoration: none; }
      .card h3 a:hover { text-decoration: underline; }
      .live { color: var(--live); font: 700 .66rem/1 var(--mono); letter-spacing: .08em;
        text-transform: uppercase; white-space: nowrap; display: inline-flex; gap: .35rem;
        align-items: center; }
      .live::before { content: ""; width: .45rem; height: .45rem; border-radius: 50%;
        background: currentColor; animation: pulse 2s ease-in-out infinite; }
      @keyframes pulse { 50% { opacity: .3; } }
      @media (prefers-reduced-motion: reduce) { .live::before { animation: none; } }
      .desc { color: var(--muted); font-size: .86rem; margin: .4rem 0 0; }
      .about summary { color: var(--muted); font-size: .8rem; cursor: pointer; width: max-content; }
      .latest { font-size: .88rem; margin: 0; overflow-wrap: anywhere; display: -webkit-box;
        -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
      .latest:empty { display: none; }
      .latest span { color: var(--muted); font: .76rem var(--mono); }
      .card footer { margin-top: auto; display: flex; flex-wrap: wrap; gap: .4rem;
        align-items: center; font-size: .8rem; }
      .card footer .about { margin-left: auto; }
      .card footer .about[open] { flex-basis: 100%; margin-left: 0; order: 9; }
      .more { font: inherit; font-size: .86rem; font-weight: 600; color: var(--link);
        background: none; border: 1px dashed var(--line); border-radius: 10px; width: 100%;
        padding: .55rem; margin-top: .7rem; cursor: pointer; }
      .more:hover { border-color: var(--link); }
      .more[hidden] { display: none; }
      .pill { background: var(--pill); color: var(--ink); text-decoration: none;
        padding: .1rem .5rem; border-radius: 5px; font: 600 .72rem/1.5 var(--mono); }
      .pill:hover { background: var(--accent); color: var(--accent-ink); }
      .warn { color: var(--live); }
      .empty { color: var(--muted); font-size: .9rem; }
      .ways { display: grid; gap: .8rem; padding-block: 1.5rem;
        grid-template-columns: repeat(auto-fit, minmax(min(15rem, 100%), 1fr)); }
      .ways div { background: var(--card); border: 1px solid var(--line); border-radius: 14px;
        padding: .9rem 1.05rem; min-width: 0; }
      .ways h2 { font-size: .98rem; margin: 0 0 .35rem; }
      .ways p { margin: 0; color: var(--muted); font-size: .88rem; overflow-wrap: anywhere; }
      .use { display: grid; gap: 1rem 2rem; padding-block: 1.5rem;
        grid-template-columns: repeat(auto-fit, minmax(min(16rem, 100%), 1fr)); }
      .use h2 { font-size: .95rem; margin: 0 0 .3rem; }
      .use p { margin: 0; color: var(--muted); font-size: .86rem; overflow-wrap: anywhere; }
      code { background: var(--pill); padding: .05rem .35rem; border-radius: 4px;
        font: .85em var(--mono); }
      .foot { color: var(--muted); font-size: .82rem; padding-block: 1.5rem 3rem;
        border-top: 1px solid var(--line); }
"""


def live_feed_names(url: str) -> set[str]:
    """The feeds a live copy (`unlimited watch --catalog`) keeps, from its feeds.json; empty
    when it cannot be read, so a page can always be written."""
    import httpx

    try:
        document = httpx.get(url, timeout=10, follow_redirects=True).json()
        return {str(f["name"]) for f in document.get("feeds", []) if f.get("name")}
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        return set()


COLORS = 10  # topic colours in the page's palette (--c0 to --c9)
FIRST_CARDS_PHONE = 3  # the fewest first feeds a topic shows (on a phone; 6 elsewhere)


def index_page(p: PublishPlan, every: str) -> str:
    esc = html.escape
    order = list(dict.fromkeys([*p.groups, *sorted({i.group for i in p.pipelines if i.group})]))
    grouped: dict[str, list[Published]] = {g: [] for g in order}
    for item in p.pipelines:
        grouped.setdefault(item.group or "More feeds", []).append(item)
    lanes = {Path(path).as_posix() for path in p.express}
    watched = live_feed_names(p.live) if p.live else set()  # the live copy's feeds
    sections, tabs, tiles, topics, feed_topic = [], [], [], [], {}
    for n, (group, items) in enumerate((g, i) for g, i in grouped.items() if i):
        slug, color = _slug(group), f"var(--c{n % COLORS})"
        topics.append({"slug": slug, "name": group, "color": color})
        cards = []
        for item in items:
            feed_topic[item.name] = slug
            pills = "".join(
                f'<a class="pill" href="{esc(f.as_posix())}">{esc(_format_label(f))}</a>'
                for f in item.files
            )
            is_live = item.name in watched or item.path.as_posix() in lanes
            live = (
                '<span class="live" title="Checked every 30 seconds to 5 minutes">Live</span>'
                if item.name in watched
                else '<span class="live" title="Refreshed in the express lane">Live</span>'
                if is_live
                else ""
            )
            about = (
                '<details class="about"><summary>About</summary>'
                f'<p class="desc">{esc(item.description)}</p></details>'
                if item.description
                else ""
            )
            words = esc(f"{item.name} {item.title or ''} {item.description or ''}".lower())
            cards.append(
                f'        <article class="card" id="feed-{esc(item.name)}" data-words="{words}"'
                f"{' data-live' if is_live else ''}>\n"
                f'          <h3><a href="#feed-{esc(item.name)}">'
                f"{esc(item.title or _readable(item.name))}</a>{live}</h3>\n"
                f'          <p class="latest" data-latest="{esc(item.name)}"></p>\n'
                f'          <footer>{pills}<span data-health="{esc(item.name)}"></span>'
                f"{about}</footer>\n"
                "        </article>"
            )
        count = f"{len(items)} feed{'s' if len(items) != 1 else ''}"
        tabs.append(
            f'<button type="button" data-topic="{slug}" aria-pressed="false" '
            f'style="--c: {color}"><i></i>{esc(group)}</button>'
        )
        tiles.append(
            f'        <button class="tile" type="button" data-topic="{slug}" '
            f'aria-pressed="false" style="--c: {color}"><b>{esc(group)}</b>'
            f'<small><span data-new="{slug}">…</span> new in 24 h · {count}</small>'
            f'<svg data-spark="{slug}" viewBox="0 0 140 28" preserveAspectRatio="none" '
            'aria-hidden="true"></svg></button>'
        )
        more = (
            f'\n      <button class="more" type="button">Show all {count}</button>'
            if len(items) > FIRST_CARDS_PHONE
            else ""
        )
        sections.append(
            f'    <section class="group" id="{slug}" data-topic="{slug}" style="--c: {color}">\n'
            f"      <h2>{esc(group)} <small>{count}</small></h2>\n"
            f'      <div class="grid">\n'
            + "\n".join(cards)
            + f"\n      </div>{more}\n    </section>"
        )
    title = esc(p.title or p.name)
    headline = esc(p.headline or p.title or p.name)
    about = f'\n      <p class="lede">{esc(p.about)}</p>' if p.about else ""
    links = "".join(f'<a href="{esc(url)}">{esc(label)}</a>' for label, url in p.links)
    tries = ""
    if p.examples:
        buttons = "".join(
            f'<button type="button" data-q="{esc(text)}">{esc(text)}</button>'
            for text in p.examples
        )
        tries = f'      <p class="try">Try {buttons}</p>\n'
    live_kpi, pace_kpi = "", f"every {every}"
    if p.express and p.express_every:
        from unlimitedpipe.watch import format_duration

        names = {i.name for i in p.pipelines if i.path.as_posix() in lanes} | watched
        live_kpi = f"<small>{len(names)} live</small>"
        pace = "30 seconds to 5 minutes" if watched else format_duration(p.express_every)
        pace_kpi = f"every {every}; live feeds every {'30 s to 5 min' if watched else pace}"
        every = f"{every} (live feeds: {pace})"
    # what the page's charts need to know: each topic's colour, and each feed's topic
    data = json.dumps({"topics": topics, "feeds": feed_topic}, ensure_ascii=False)
    data = data.replace("<", "\\u003c")
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
      <p class="kicker">Open feed catalog · every item linked to its source</p>
      <h1>{headline}</h1>{about}
      <div class="find"><input id="q" type="search"
        placeholder="Search every feed: hurricane katrina, sanctions, nvidia earnings…"
        autocomplete="off" aria-label="Search every feed"><kbd>/</kbd></div>
{tries}      <p id="status"></p>
      <button id="deep" type="button" hidden>Search every past record, not only the latest</button>
      <ul id="results"></ul>
    </section>
    <section class="kpis" aria-label="The catalog in numbers">
      <div class="kpi"><span>Records</span><b id="stat-archive">…</b>
        <small id="stat-since"></small></div>
      <div class="kpi"><span>Feeds</span><b>{len(p.pipelines)}</b>{live_kpi}</div>
      <div class="kpi"><span>New in 24 hours</span><b id="stat-new">…</b>
        <small>items dated today or yesterday</small></div>
      <div class="kpi"><span>Updated</span><b id="stat-updated">…</b>
        <small>{esc(pace_kpi)}</small></div>
    </section>
    <div class="dash">
      <section class="panel" aria-labelledby="days-title">
        <h2 id="days-title">The last 30 days <small>items a day, by topic</small></h2>
        <svg class="chart" id="chart-days" viewBox="0 0 640 220" role="img"
          aria-label="Items a day over the last 30 days, by topic"></svg>
        <p class="readout" id="days-readout"></p>
        <div class="legend" id="legend"></div>
      </section>
      <aside class="panel" aria-labelledby="desk-title">
        <h2 id="desk-title"><span><span class="live">Live</span> Just in</span></h2>
        <ol class="wire" id="wire"><li>Loading the newest items…</li></ol>
      </aside>
    </div>
    <section class="panel" aria-labelledby="years-title">
      <h2 id="years-title">The archive, year by year <small id="years-note"></small></h2>
      <svg class="chart" id="chart-years" viewBox="0 0 960 200" role="img"
        aria-label="Records in the archive each year, by topic"></svg>
      <p class="readout" id="years-readout"></p>
    </section>
    <section class="topics" id="topics" aria-label="Topics">
      <h2>Topics</h2>
      <div class="tiles">
{chr(10).join(tiles)}
      </div>
    </section>
    <section class="browse" aria-label="Every feed">
      <h2>Every feed</h2>
      <div class="toolbar">
        <div class="tabs" role="group" aria-label="Show a topic"><button type="button"
          data-topic="" aria-pressed="true">All</button>{"".join(tabs)}</div>
        <input id="filter" type="search" placeholder="Filter feeds…" aria-label="Filter feeds">
        <label><input id="live-only" type="checkbox"> Live only</label>
      </div>
{chr(10).join(sections)}
      <p class="empty" id="no-feeds" hidden>No feed matches.</p>
    </section>
    <section class="ways" aria-label="Ways to use it">
      <div><h2>Search and ask</h2><p>Search above, or in a terminal:
        <code>pip install unlimitedpipe</code>, then <code>unlimited ask "QUESTION"</code>,
        answered from these records with every source cited.</p></div>
      <div><h2>Get alerts</h2><p><code>unlimited follow WORDS --to ntfy:TOPIC</code> sends each
        new match to your phone (the free ntfy app, no account), Telegram, Discord or
        Slack.</p></div>
      <div><h2>Subscribe</h2><p>Every feed is RSS for any reader and JSON for code: the buttons
        on each card.</p></div>
      <div><h2>Make your own</h2><p>Each feed is a short YAML pipeline; fork one and
        <code>unlimited publish</code> hosts yours for free on GitHub.</p></div>
    </section>
    <section class="use">
      <div><h2>Where it comes from</h2><p>Official APIs, feeds and public pages, read politely
        (robots.txt, rate limits, an honest User-Agent). Each item links to its source.</p></div>
      <div><h2>History</h2><p>Every item goes into a monthly archive,
        <a href="{esc("archive/index.json")}">archive/index.json</a>, so questions about a year or a
        month reach back. Runs every {esc(every)}.</p></div>
    </section>
    <footer class="foot">Built with <a href="https://github.com/Fuyuki0/unlimitedpipe">UnlimitedPipe</a>,
      open source: no server, no account, no tracking. Items come from public records and news,
      each with a link to its source; nothing here is investment, legal or medical advice.</footer>
    </div>
    <script type="application/json" id="page-data">{data}</script>
{SEARCH_SCRIPT}{DASH_SCRIPT}  </body>
</html>
"""
