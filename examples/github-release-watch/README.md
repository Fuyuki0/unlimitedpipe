# github-release-watch

Watch releases of any public GitHub repository through its Atom feed
(`https://github.com/OWNER/REPO/releases.atom`). No token needed.

```bash
unlimited rss https://github.com/astral-sh/uv/releases.atom | unlimited limit 3
unlimited run examples/github-release-watch/pipeline.yml
```

Run it from cron or a scheduled GitHub Action and subscribe to `releases.xml`. After the first
run, only new releases are added.
