"""The ``unlimited`` command.

Every source, operator and output is a subcommand generated from its component class, so
plugins get a CLI for free. Commands are built lazily: a pipe stage only imports what it runs.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

import click

from unlimitedpipe import registry
from unlimitedpipe._version import __version__
from unlimitedpipe.component import Component, Output, Param, Source, kind_of, suggest
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


def _click_type(param: Param) -> click.ParamType:
    if param.choices:
        return click.Choice(param.choices)
    return {str: click.STRING, int: click.INT, float: click.FLOAT, bool: click.BOOL}[param.base]


def _click_param(param: Param) -> click.Parameter:
    if param.positional:
        return click.Argument(
            [param.name],
            type=_click_type(param),
            nargs=-1 if param.is_list else 1,
            required=param.required,
            default=None if param.is_list or param.required else param.default,
            metavar=param.metavar or param.name.upper() + ("..." if param.is_list else ""),
        )
    declarations = [param.flag] + ([param.short] if param.short else [])
    if param.base is bool and not param.is_list:
        if param.default:
            declarations = [f"{param.flag}/--no-{param.flag[2:]}"]
        return click.Option(
            declarations,
            is_flag=True,
            default=bool(param.default),
            help=param.help,
            show_default=bool(param.default),
        )
    show_default = param.default not in (None, [], False)
    return click.Option(
        declarations,
        type=_click_type(param),
        multiple=param.is_list,
        default=None if param.is_list else param.default,
        required=param.required,
        help=param.help,
        metavar=param.metavar,
        show_default=show_default,
    )


def _help_text(cls: type[Component]) -> str:
    parts = [cls.help_text or cls.help_summary]
    positional = [p for p in cls.params() if p.positional]
    if positional:
        lines = ["\b", "Arguments:"]
        for p in positional:
            name = p.metavar or p.name.upper() + ("..." if p.is_list else "")
            lines.append(f"  {name:<12} {p.help}")
        parts.append("\n".join(lines))
    if cls.examples:
        parts.append("\n".join(["\b", "Examples:", *(f"  {e}" for e in cls.examples)]))
    return "\n\n".join(p for p in parts if p)


def build_command(cls: type[Component]) -> click.Command:
    params = cls.params()

    @click.pass_context
    def callback(click_ctx: click.Context, **values: Any) -> None:
        kwargs: dict[str, Any] = {}
        for param in params:
            value = values.get(param.name)
            if param.is_list:
                value = list(value or []) or list(param.default or [])
            kwargs[param.name] = value
        try:
            component = cls(**kwargs)
        except (ValueError, TypeError) as exc:
            raise click.UsageError(str(exc), ctx=click_ctx) from None
        _execute(component, click_ctx.obj or {})

    command = click.Command(
        cls.name,
        callback=callback,
        params=[_click_param(p) for p in params],
        help=_help_text(cls),
        short_help=cls.help_summary,
        no_args_is_help=False,
    )
    command.kind = kind_of(cls)  # type: ignore[attr-defined]
    return command


class UnlimitedGroup(click.Group):
    def list_commands(self, ctx: click.Context) -> list[str]:
        return [*registry.names(), *super().list_commands(ctx)]

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        command = super().get_command(ctx, cmd_name)
        if command is not None:
            return command
        cls = registry.load(cmd_name)
        return build_command(cls) if cls is not None else None

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


@cli.command("run")
@click.argument("pipeline", type=click.Path(dir_okay=False, path_type=Path))
@click.option(
    "--validate", is_flag=True, help="Check the pipeline file and exit without running it."
)
@click.pass_context
def run_command(ctx: click.Context, pipeline: Path, validate: bool) -> None:
    """Run a YAML pipeline: sources, operators and outputs in one process.

    \b
    Example pipeline.yml:
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
    from unlimitedpipe.config import load_pipeline

    loaded = load_pipeline(pipeline)
    if validate:
        counts = (len(loaded.sources), len(loaded.operators), len(loaded.outputs) or "default")
        click.echo(
            f"{pipeline}: valid ({counts[0]} source(s), {counts[1]} operator(s), "
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


run_command.kind = "tool"  # type: ignore[attr-defined]


def _print_error(error: UnlimitedError) -> None:
    click.echo(click.style("error: ", fg="red", bold=True) + error.message, err=True)
    if error.hint:
        click.echo(click.style("hint: ", fg="cyan") + error.hint, err=True)


def main() -> None:
    try:
        cli.main(prog_name="unlimited", standalone_mode=False)
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
