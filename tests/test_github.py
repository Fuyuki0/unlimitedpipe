import json

import httpx
import pytest

from tests.conftest import run_source
from unlimitedpipe.sources.github import GitHub, parse_repo

API = "https://api.github.com/repos"

RELEASES = [
    {
        "id": 2,
        "name": "v2.0",
        "tag_name": "v2.0",
        "html_url": "https://github.com/o/r/releases/tag/v2.0",
        "published_at": "2026-09-20T10:00:00Z",
        "prerelease": False,
        "author": {"login": "ana"},
        "body": "Big release",
        "assets": [{}, {}],
    },
    {
        "id": 1,
        "name": None,
        "tag_name": "v1.0",
        "html_url": "https://github.com/o/r/releases/tag/v1.0",
        "published_at": "2026-01-01T00:00:00Z",
        "prerelease": True,
        "author": {"login": "bo"},
        "body": "",
    },
]


def test_parse_repo():
    assert parse_repo("pallets/click") == "pallets/click"
    assert parse_repo("https://github.com/pallets/click.git") == "pallets/click"
    assert parse_repo("https://github.com/pallets/click/") == "pallets/click"
    with pytest.raises(ValueError, match="owner/repo"):
        parse_repo("click")


def test_releases(web, ctx, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    web.add(
        f"{API}/o/r/releases?per_page=30", json.dumps(RELEASES), content_type="application/json"
    )
    first, second = run_source(GitHub(resource="releases", repo=["o/r"]), ctx)
    assert first.type == "release"
    assert first.key == "https://github.com/o/r/releases/tag/v2.0"
    assert first.timestamp == "2026-09-20T10:00:00Z"
    assert first.data["repo"] == "o/r" and first.data["title"] == "v2.0"
    assert first.data["author"] == "ana" and first.data["assets"] == 2
    assert second.data["title"] == "v1.0" and second.data["prerelease"] is True
    assert second.data["summary"] is None
    request = web.requests[0]
    assert "authorization" not in request.headers
    assert request.headers["accept"] == "application/vnd.github+json"


def test_repo_stats_with_token(web, ctx, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    repo = {
        "full_name": "o/r",
        "html_url": "https://github.com/o/r",
        "stargazers_count": 10,
        "forks_count": 2,
        "license": {"spdx_id": "MIT"},
        "topics": ["cli"],
    }
    web.add(f"{API}/o/r", json.dumps(repo), content_type="application/json")
    [event] = run_source(GitHub(resource="repo", repo=["o/r"]), ctx)
    assert event.type == "repository"
    assert (event.data["stars"], event.data["license"], event.data["topics"]) == (
        10,
        "MIT",
        ["cli"],
    )
    assert web.requests[0].headers["authorization"] == "Bearer secret-token"
    assert "secret-token" not in json.dumps(
        GitHub(resource="repo", repo=["o/r"], token="x").provenance_step()
    )


def test_commits_issues_and_tags(web, ctx):
    commits = [
        {
            "sha": "abc",
            "html_url": "https://github.com/o/r/commit/abc",
            "author": {"login": "ana"},
            "commit": {
                "message": "Fix bug\n\nDetails",
                "author": {"name": "Ana", "date": "2026-09-01T00:00:00Z"},
            },
        }
    ]
    issues = [
        {
            "id": 5,
            "number": 7,
            "title": "Crash",
            "html_url": "https://github.com/o/r/issues/7",
            "state": "open",
            "user": {"login": "bo"},
            "labels": [{"name": "bug"}],
            "comments": 3,
            "created_at": "2026-09-02T00:00:00Z",
            "updated_at": "2026-09-03T00:00:00Z",
        }
    ]
    tags = [{"name": "v1", "commit": {"sha": "def"}}]
    for resource, payload in (("commits", commits), ("issues", issues), ("tags", tags)):
        web.add(
            f"{API}/o/r/{resource}?per_page=5", json.dumps(payload), content_type="application/json"
        )
    [commit] = run_source(GitHub(resource="commits", repo=["o/r"], limit=5), ctx)
    assert commit.data["title"] == "Fix bug" and commit.data["author"] == "ana"
    [issue] = run_source(GitHub(resource="issues", repo=["o/r"], limit=5), ctx)
    assert issue.data["labels"] == ["bug"] and issue.data["pull_request"] is False
    [tag] = run_source(GitHub(resource="tags", repo=["o/r"], limit=5), ctx)
    assert tag.data["url"] == "https://github.com/o/r/releases/tag/v1"


def test_rate_limit_and_missing_repo_are_explained(web, make_ctx, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    def limited(request):
        headers = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1790000000"}
        return httpx.Response(403, json={"message": "rate limit"}, headers=headers)

    web.pages[f"{API}/o/limited/releases?per_page=30"] = limited
    ctx = make_ctx(errors_as_events=True)
    limited_error, missing = run_source(
        GitHub(resource="releases", repo=["o/limited", "o/missing"]), ctx
    )
    assert "rate limit reached" in limited_error.data["error"]
    assert "GITHUB_TOKEN" in limited_error.data["hint"]
    assert "not found" in missing.data["error"]


def test_invalid_options():
    with pytest.raises(ValueError, match="between 1 and 100"):
        GitHub(resource="releases", repo=["o/r"], limit=500)
    with pytest.raises(ValueError, match="at least one"):
        GitHub(resource="releases", repo=[])
