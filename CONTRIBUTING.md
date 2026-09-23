# Contributing

Thanks for helping. The most useful contributions, roughly in order:

1. **Connectors**: a new source as its own package. See [docs/connectors.md](docs/connectors.md);
   [examples/plugin-hackernews](examples/plugin-hackernews) is a template to copy.
2. **Recipes**: a pipeline in `examples/` that solves a real problem, with a short README.
3. **Bug reports** with the exact command and output.
4. **Fixes and improvements** to the core.

For anything larger than a bug fix, open an issue first so we can agree on the approach.

## Setup

```bash
git clone <your fork>
cd unlimitedpipe
make install        # .venv with UnlimitedPipe (editable) and dev tools
make check          # lint, formatting, types, tests: the same as CI
```

Tests never touch the network: HTTP is faked with `httpx.MockTransport` (see
`tests/conftest.py`).

## What belongs in the core

Ask: can it be an event entering a pipeline, being transformed, and leaving it? If yes, it
fits. Beyond that, the core stays small:

- Sources most users need, with no heavy dependencies. Everything else is a plugin package.
- Operators that are general (filter, window, count), not tied to one site.
- No feature whose purpose is getting around logins, CAPTCHAs, rate limits or blocks, and no
  connector built around collecting data about individuals. See
  [docs/responsible-use.md](docs/responsible-use.md).

## Code

- Python 3.11+, formatted with `ruff format`, checked with `ruff` and `pyright`.
- Keep pipe stages fast: import heavy libraries (httpx, bs4, feedparser, rich) inside the
  functions that use them, not at module level.
- User-facing errors raise `UnlimitedError` (or a subclass) with a message that says what went
  wrong and a `hint` that says what to do. No tracebacks for expected problems.
- Stdout carries events only. Human messages go to stderr through `ctx.notice` / `ctx.warn`.
- New behavior comes with tests; bugs come with a test that fails before the fix.

## Commits and pull requests

- One logical change per pull request, with a description of what and why.
- Sign off your commits (`git commit -s`) to certify the
  [Developer Certificate of Origin](https://developercertificate.org/): you wrote the change
  or have the right to submit it under the Apache-2.0 license.
- Update `CHANGELOG.md` for user-facing changes.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
