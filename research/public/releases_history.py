"""The release history of the repositories behind ai-releases, dev-releases and crypto-releases,
with each feed's titles and filters, from GitHub's API (through `gh`, which pages it).

    research/.venv/bin/python research/public/releases_history.py FEEDS_DIR OUT.jsonl
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

from unlimitedpipe.sources.github import plain_text


def releases(repo: str) -> list[dict]:
    fields = "{tag_name, name, published_at, prerelease, html_url, body}"
    run = subprocess.run(
        [
            "gh",
            "api",
            "--paginate",
            f"repos/{repo}/releases?per_page=100",
            "--jq",
            f".[] | {fields}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return [json.loads(line) for line in run.stdout.splitlines() if line.strip()]  # one a line


def main(feeds: str, out: str) -> None:
    written = 0
    with open(out, "w", encoding="utf-8") as lines:
        for feed in ("ai-releases", "dev-releases", "crypto-releases"):
            pipeline = yaml.safe_load((Path(feeds) / f"{feed}.yml").read_text())
            repos = pipeline["sources"][0]["repo"]
            for repo in repos:
                count = 0
                for release in releases(repo):
                    tag = release.get("tag_name") or ""
                    if not release.get("published_at") or re.match(r"^b[0-9]+$", tag):
                        continue
                    name = release.get("name") or tag
                    if feed == "crypto-releases":
                        if release.get("prerelease") or re.search(r"(?i)-(rc|alpha|beta)", tag):
                            continue
                        title = f"{repo} {tag}: {name}"
                    else:
                        title = f"{repo} {name}"
                    summary = (plain_text(release.get("body")) or "")[:300]
                    item = {
                        "feed": feed,
                        "title": title,
                        "summary": summary,
                        "link": release.get("html_url"),
                        "date": release["published_at"],
                    }
                    lines.write(json.dumps(item, ensure_ascii=False) + "\n")
                    count += 1
                    written += 1
                print(feed, repo, count, flush=True)
    print(written, "releases")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
