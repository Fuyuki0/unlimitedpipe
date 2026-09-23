# github-release-watch

Watch releases of any public GitHub repository through GitHub's official REST API.

```bash
unlimited github releases astral-sh/uv ollama/ollama --limit 3
unlimited run examples/github-release-watch/pipeline.yml
unlimited watch --every 1h examples/github-release-watch/pipeline.yml
```

After the first run, only new releases are added to `releases.xml`; subscribe to it in any
feed reader.

No account is needed for a few repositories checked hourly: GitHub allows 60 API requests per
hour without a token, and unchanged results are revalidated with ETags, which do not count
against that limit. For more, set a token (any classic or fine-grained token with no extra
scopes works for public data):

```bash
export GITHUB_TOKEN=ghp_...
```

The same connector reads repository stats, tags, commits and issues:

```bash
unlimited github repo pallets/click | unlimited select title stars forks
unlimited github issues pallets/click --limit 50 | unlimited diff --only added
```
