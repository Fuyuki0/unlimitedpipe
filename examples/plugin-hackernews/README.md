# unlimitedpipe-hackernews

A complete, installable UnlimitedPipe connector in about 60 lines. Copy this folder to start
your own; the walkthrough is in [docs/connectors.md](../../docs/connectors.md).

```bash
pip install -e examples/plugin-hackernews
unlimited hackernews "local llm" --min-points 50
unlimited hackernews rust | unlimited diff --only added | unlimited feed rust-hn.xml
```

In a pipeline file:

```yaml
sources:
  - type: hackernews
    query: local llm
    min_points: 50
```

Files:

- `pyproject.toml`: the entry point that registers the `hackernews` command.
- `src/unlimitedpipe_hackernews/__init__.py`: the source.
- `tests/test_hackernews.py`: a test with a fake API, no network.
