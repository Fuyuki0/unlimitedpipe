"""The ``unlimited`` command.

Every source, operator and output is a subcommand generated from its component class, so
plugins get a CLI for free. Commands are built lazily: a pipe stage only imports what it runs.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

import click

from unlimitedpipe import registry
from unlimitedpipe._version import __version__
from unlimitedpipe.commands import STAGE_SEPARATOR, build_command, parse_inline
from unlimitedpipe.component import Component, Output, Source, kind_of, suggest
from unlimitedpipe.errors import UnlimitedError, UsageError

MAIN_HELP = """\
UnlimitedPipe: pipe the public internet.

Sources emit JSONL events, operators transform them, outputs write them. In a terminal you see
readable output; in a pipe you get one JSON event per line.

\b
  unlimited web https://example.com
  unlimited web https://example.com | unlimited select title url | unlimited json
  unlimited rss https://hnrss.org/frontpage | unlimited grep AI | unlimited diff --only added
  unlimited run pipeline.yml
  unlimited watch --every 1h pipeline.yml

Run `unlimited COMMAND --help` for a command's options.
"""

SECTIONS = (
    ("source", "Sources"),
    ("operator", "Operators"),
    ("output", "Outputs"),
    ("tool", "Pipelines"),
)


class _StdinSource(Source):
    """Events piped in on stdin."""

    name = "stdin"

    def provenance_step(self) -> dict[str, Any] | None:
        return None

    async def collect(self, ctx):
        from unlimitedpipe.jsonl import read_events

        async for event in read_events(sys.stdin.buffer):
            yield event


def default_output() -> Output:
    """Readable output for terminals, JSONL for pipes.

    ``UNLIMITEDPIPE_FORMAT=jsonl`` forces JSONL on a terminal too. To force readable output
    into a pipe, end it with ``| unlimited pretty``.
    """
    force_jsonl = os.environ.get("UNLIMITEDPIPE_FORMAT", "").lower() == "jsonl"
    choice = "pretty" if sys.stdout.isatty() and not force_jsonl else "jsonl"
    cls = registry.load(choice)
    assert cls is not None
    return cls()  # type: ignore[return-value]


def _run(
    sources, operators, outputs, *, errors_as_events: bool, quiet: bool, piped_input: bool
) -> None:
    from unlimitedpipe.context import Context
    from unlimitedpipe.engine import run_pipeline

    input_events = None
    if piped_input:
        from unlimitedpipe.jsonl import read_events

        input_events = read_events(sys.stdin.buffer, lenient=True)
    ctx = Context(errors_as_events=errors_as_events, quiet=quiet, input=input_events)
    asyncio.run(run_pipeline(sources, operators, outputs, ctx))
    if ctx.failures:
        sys.exit(1)


def _execute(component: Component, options: dict[str, Any]) -> None:
    stdin_piped = not sys.stdin.isatty()
    kind = kind_of(component)
    if kind != "source" and not stdin_piped:
        raise UsageError(
            f"`{component.name}` reads events from stdin; pipe a source into it",
            hint=f"unlimited web https://example.com | unlimited {component.name} ...",
        )
    if kind == "source":
        sources, operators, outputs = [component], [], [default_output()]
    elif kind == "operator":
        sources, operators, outputs = [_StdinSource()], [component], [default_output()]
    else:
        sources, operators, outputs = [_StdinSource()], [], [component]
    _run(
        sources,
        operators,
        outputs,
        errors_as_events=options.get("errors_as_events", False),
        quiet=options.get("quiet", False),
        piped_input=kind == "source" and stdin_piped,
    )


class UnlimitedGroup(click.Group):
    def list_commands(self, ctx: click.Context) -> list[str]:
        return [*registry.names(), *super().list_commands(ctx)]

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        command = super().get_command(ctx, cmd_name)
        if command is not None:
            return command
        cls = registry.load(cmd_name)
        return build_command(cls, _execute) if cls is not None else None

    def resolve_command(self, ctx: click.Context, args: list[str]):
        name = args[0] if args else ""
        if name and not name.startswith("-") and self.get_command(ctx, name) is None:
            close = suggest(name, self.list_commands(ctx))
            hint = (
                f" Did you mean `{close}`?"
                if close
                else " Run `unlimited --help` to list commands."
            )
            ctx.fail(f"No such command {name!r}.{hint}")
        return super().resolve_command(ctx, args)

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        rows: dict[str, list[tuple[str, str]]] = {kind: [] for kind, _ in SECTIONS}
        for name in self.list_commands(ctx):
            command = self.get_command(ctx, name)
            if command is None or command.hidden:
                continue
            kind = getattr(command, "kind", "tool")
            rows.setdefault(kind, []).append((name, command.get_short_help_str(limit=72)))
        for kind, title in SECTIONS:
            if rows.get(kind):
                with formatter.section(title):
                    formatter.write_dl(rows[kind])


@click.group(
    cls=UnlimitedGroup, help=MAIN_HELP, context_settings={"help_option_names": ["-h", "--help"]}
)
@click.version_option(__version__, "-V", "--version", prog_name="unlimited")
@click.option(
    "-v", "--verbose", count=True, help="Log requests (-v) or debug details (-vv) to stderr."
)
@click.option("-q", "--quiet", is_flag=True, help="Only print errors to stderr.")
@click.option(
    "--errors-as-events",
    is_flag=True,
    help="Emit failures as `error` events instead of printing them.",
)
@click.pass_context
def cli(ctx: click.Context, verbose: int, quiet: bool, errors_as_events: bool) -> None:
    ctx.obj = {"quiet": quiet, "errors_as_events": errors_as_events}
    level = logging.DEBUG if verbose > 1 else logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=level, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr
    )
    if not verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)


PIPELINE_ARGS = {"ignore_unknown_options": True, "help_option_names": ["-h", "--help"]}


def _load(target: tuple[str, ...]):
    """A pipeline from a YAML file, or from inline stages separated by `--`."""
    from unlimitedpipe.config import Pipeline, load_pipeline

    if not target:
        raise UsageError(
            "give a pipeline file or inline stages",
            hint="unlimited run pipeline.yml   or   unlimited run web https://example.com -- json",
        )
    if len(target) == 1 and target[0].endswith((".yml", ".yaml")):
        return load_pipeline(Path(target[0])), Path(target[0])
    sources, operators, outputs = parse_inline(list(target))
    return Pipeline(name="inline", sources=sources, operators=operators, outputs=outputs), None


@cli.command("run", context_settings=PIPELINE_ARGS)
@click.argument("target", nargs=-1, type=click.UNPROCESSED)
@click.option("--validate", is_flag=True, help="Check the pipeline and exit without running it.")
@click.pass_context
def run_command(ctx: click.Context, target: tuple[str, ...], validate: bool) -> None:
    """Run a pipeline in one process: a YAML file, or stages separated by `--`.

    \b
    Examples:
      unlimited run pipeline.yml
      unlimited run web https://example.com -- select title url -- json

    \b
    A pipeline.yml:
      sources:
        - type: rss
          url: https://hnrss.org/frontpage
      operators:
        - type: grep
          patterns: [AI]
        - type: diff
          only: [added]
      outputs:
        - type: feed
          path: ai-news.xml
    """
    loaded, path = _load(target)
    if validate:
        counts = (len(loaded.sources), len(loaded.operators), len(loaded.outputs) or "default")
        click.echo(
            f"{path or 'pipeline'}: valid ({counts[0]} source(s), {counts[1]} operator(s), "
            f"{counts[2]} output(s))",
            err=True,
        )
        return
    options = ctx.obj or {}
    _run(
        loaded.sources,
        loaded.operators,
        loaded.outputs or [default_output()],
        errors_as_events=loaded.errors_as_events or options.get("errors_as_events", False),
        quiet=options.get("quiet", False),
        piped_input=False,
    )


@cli.command("watch", context_settings=PIPELINE_ARGS)
@click.argument("target", nargs=-1, type=click.UNPROCESSED)
@click.option(
    "--every", "every", required=True, metavar="DURATION", help="Interval: 30s, 5m, 1h, 1d."
)
@click.option("--times", type=int, default=None, help="Stop after this many runs.")
@click.option(
    "--jitter",
    type=float,
    default=0.1,
    show_default=True,
    help="Random extra delay, as a fraction of the interval.",
)
@click.pass_context
def watch_command(
    ctx: click.Context, target: tuple[str, ...], every: str, times: int | None, jitter: float
) -> None:
    """Run a pipeline repeatedly, in one process, until Ctrl+C.

    A failed run is reported and the watch continues. A pipeline file is reloaded when it
    changes. Outputs run once per round: `feed` keeps its history, and jsonl files need
    `append: true` to keep earlier rounds. Combine with `diff` to see only what changed.

    \b
    Examples:
      unlimited watch --every 1h pipeline.yml
      unlimited watch --every 30m web https://store.example/p -- diff -- feed prices.xml
    """
    from unlimitedpipe.watch import MIN_INTERVAL, Watch, parse_duration

    seconds = parse_duration(every)
    if seconds < MIN_INTERVAL:
        raise UsageError(
            f"--every {every} is too frequent; the minimum is 30s",
            hint="most pages change far less often; 5m to 1d is typical",
        )
    if times is not None and times < 1:
        raise UsageError("--times must be at least 1")
    if not 0 <= jitter <= 1:
        raise UsageError("--jitter must be between 0 and 1")
    pipeline, path = _load(target)
    options = ctx.obj or {}
    if options.get("errors_as_events"):
        pipeline.errors_as_events = True

    def load():
        loaded = _load(target)[0] if path is not None else pipeline
        loaded.errors_as_events = loaded.errors_as_events or options.get("errors_as_events", False)
        return loaded

    Watch(
        load,
        every=seconds,
        jitter=jitter,
        times=times,
        quiet=options.get("quiet", False),
        reload_path=path,
        default_outputs=lambda: [default_output()],
    ).run()


@cli.command("new")
@click.argument("url")
@click.option(
    "-o",
    "--output",
    "output",
    default=None,
    metavar="FILE",
    help="Where to write the pipeline (default: NAME.yml; `-` prints it).",
)
@click.option("--force", is_flag=True, help="Overwrite an existing file.")
@click.pass_context
def new_command(ctx: click.Context, url: str, output: str | None, force: bool) -> None:
    """Inspect a URL and write a pipeline that watches it the most reliable way.

    Product pages become price and stock watches, sites with a feed become new-item
    watches, other pages become text watches you can narrow with CSS selectors.

    \b
    Examples:
      unlimited new https://www.allbirds.com/products/mens-strider-explore
      unlimited new https://simonwillison.net -o blog.yml
    """
    from unlimitedpipe.context import Context
    from unlimitedpipe.scaffold import scaffold

    options = ctx.obj or {}
    result = asyncio.run(scaffold(url, Context(quiet=options.get("quiet", False))))
    if output == "-":
        click.echo(result.yaml, nl=False)
        return
    path = Path(output or f"{result.name}.yml")
    if path.exists() and not force:
        raise UsageError(
            f"{path} already exists", hint="choose another name with -o, or pass --force"
        )
    path.write_text(result.yaml, encoding="utf-8")
    if not options.get("quiet"):
        click.echo(f"Wrote {path}: {result.description}.", err=True)
        click.echo("Next:", err=True)
        click.echo(f"  unlimited run {path}              # first run saves a baseline", err=True)
        click.echo(f"  unlimited watch --every 1h {path}  # keep watching", err=True)


@cli.command("publish")
@click.argument(
    "pipelines",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--every",
    default="1h",
    show_default=True,
    metavar="DURATION",
    help="How often GitHub Actions runs them: 15m to 1d.",
)
@click.option(
    "--name", default=None, help="Workflow name (default: the pipeline's name, or feeds)."
)
@click.option("--force", is_flag=True, help="Overwrite an existing workflow.")
@click.pass_context
def publish_command(
    ctx: click.Context, pipelines: tuple[Path, ...], every: str, name: str | None, force: bool
) -> None:
    """Host pipelines' outputs for free: GitHub Actions runs them, GitHub Pages serves them.

    Writes one workflow that runs every given pipeline on a schedule, commits their diff
    state and outputs to the repository, and deploys the output folder to GitHub Pages with
    an index page. A pipeline that fails does not stop the others. Outputs must live in a
    folder of their own, such as public/.

    \b
    Examples:
      unlimited publish feeds/blog.yml --every 1h
      unlimited publish feeds/*.yml --every 1h        # a catalog of feeds
    """
    from unlimitedpipe.config import load_pipeline
    from unlimitedpipe.publish import INDEX_MARKER, github_repo, index_page, plan, workflow
    from unlimitedpipe.watch import format_duration, parse_duration

    items = [(path, load_pipeline(path)) for path in pipelines]
    seconds = parse_duration(every)
    p = plan(items, seconds, name)
    workflow_path = p.root / p.workflow
    if workflow_path.exists() and not force:
        raise UsageError(f"{p.workflow} already exists", hint="pass --force to replace it")
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text(workflow(p), encoding="utf-8")
    index = p.root / p.site_dir / "index.html"
    # Rewrite the index page unless someone replaced it with their own.
    wrote_index = not index.exists() or INDEX_MARKER in index.read_text(encoding="utf-8")
    if wrote_index:
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(index_page(p, format_duration(seconds)), encoding="utf-8")
    if (ctx.obj or {}).get("quiet"):
        return
    repo = github_repo(p.root)
    slug = f"{repo[0]}/{repo[1]}" if repo else "OWNER/REPO"
    say = lambda line="": click.echo(line, err=True)  # noqa: E731
    count = f"{len(p.pipelines)} pipeline(s)" if len(p.pipelines) > 1 else p.pipelines[0].name
    say(f'Wrote {p.workflow}: {count}, every {format_duration(seconds)} (cron "{p.cron}")')
    if wrote_index:
        say(f"Wrote {p.site_dir / 'index.html'}")
    say()
    say("Next:")
    files = " ".join([".github", p.site_dir.as_posix(), *(i.path.as_posix() for i in p.pipelines)])
    say(f"  1. git add {files} && git commit -m 'Publish {p.name}' && git push")
    say("  2. Turn on GitHub Pages with GitHub Actions as the source (once per repository):")
    say(f"       gh api -X POST repos/{slug}/pages -f build_type=workflow")
    if p.secrets:
        say("  2b. Store the secrets the pipelines use (once; values stay encrypted on GitHub):")
        for secret in p.secrets:
            say(f"       gh secret set {secret} -R {slug}")
    say("  3. Start the first run now instead of waiting for the schedule:")
    say(f"       gh workflow run {p.workflow.name}")
    if p.site_url:
        say()
        say(f"Index: {p.site_url}")
        for file in p.files[:10]:
            say(f"Feed:  {p.site_url}{file.as_posix()}")
        if len(p.files) > 10:
            say(f"       … and {len(p.files) - 10} more")
    say()
    say("GitHub Pages needs a public repository on free GitHub plans.")


@cli.command("mcp")
@click.argument("pipelines", nargs=-1, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--no-builtin", is_flag=True, help="Serve only the given pipelines.")
@click.option(
    "--allow-private",
    is_flag=True,
    help="Let built-in tools reach private and local addresses (trusted setups only).",
)
def mcp_command(pipelines: tuple[Path, ...], no_builtin: bool, allow_private: bool) -> None:
    """Serve public web data to AI agents over the Model Context Protocol (stdio).

    Built-in tools: fetch_page, read_feed, inspect_url and github. Each pipeline file given
    becomes a tool too, so an agent can ask what changed. Results carry provenance. Built-in
    tools refuse private and local addresses, so content an agent reads cannot steer it into
    your network.

    \b
    Claude Code:     claude mcp add unlimitedpipe -- unlimited mcp
    Claude Desktop:  {"mcpServers": {"unlimitedpipe": {"command": "unlimited", "args": ["mcp"]}}}
    With pipelines:  unlimited mcp competitor-watch.yml ai-news.yml
    """
    from unlimitedpipe.mcp import run_server

    run_server(list(pipelines), builtins=not no_builtin, allow_private=allow_private)


for _command in (run_command, watch_command, new_command, publish_command, mcp_command):
    _command.kind = "tool"  # type: ignore[attr-defined]


def _print_error(error: UnlimitedError) -> None:
    click.echo(click.style("error: ", fg="red", bold=True) + error.message, err=True)
    if error.hint:
        click.echo(click.style("hint: ", fg="cyan") + error.hint, err=True)


def _protect_stage_separators(args: list[str]) -> list[str]:
    """Keep `--` between inline stages away from click, which would read it as end-of-options."""
    for index, token in enumerate(args):
        if token.startswith("-"):
            continue
        if token in ("run", "watch"):
            rest = [STAGE_SEPARATOR if t == "--" else t for t in args[index + 1 :]]
            return [*args[: index + 1], *rest]
        return args
    return args


def main() -> None:
    # `docker stop`, systemd and CI timeouts send SIGTERM: shut down like Ctrl+C, so outputs
    # are closed and diff state is saved.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        cli.main(
            args=_protect_stage_separators(sys.argv[1:]),
            prog_name="unlimited",
            standalone_mode=False,
        )
    except click.exceptions.Exit as exc:
        sys.exit(exc.exit_code)
    except click.ClickException as exc:
        exc.show()
        sys.exit(exc.exit_code)
    except (click.exceptions.Abort, KeyboardInterrupt):
        click.echo(click.style("interrupted", dim=True), err=True)
        sys.exit(130)
    except UnlimitedError as exc:
        _print_error(exc)
        sys.exit(exc.exit_code)
    except BrokenPipeError:
        # The reader went away (| head, | limit): stop quietly, like other Unix tools.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(0)
