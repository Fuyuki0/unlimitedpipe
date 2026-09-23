"""Click commands generated from component classes, and inline pipelines.

Every source, operator and output becomes a subcommand from its fields, so plugins get a CLI
for free. The same parsing builds inline pipelines, where ``--`` separates stages that run in
one process::

    unlimited run web https://example.com -- select title url -- json
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import click

from unlimitedpipe import registry
from unlimitedpipe.component import Component, Operator, Output, Param, Source, kind_of, suggest
from unlimitedpipe.errors import UsageError

# `main` swaps stage separators (`--`) for this token before click sees them: click would
# otherwise treat the first `--` as the end of its own options.
STAGE_SEPARATOR = "\x1f--"
KIND_ORDER = {"source": 0, "operator": 1, "output": 2}


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


def component_from_values(cls: type[Component], values: dict[str, Any]) -> Component:
    """Build a component from parsed click values. Raises ValueError on invalid options."""
    kwargs: dict[str, Any] = {}
    for param in cls.params():
        value = values.get(param.name)
        if param.is_list:
            value = list(value or []) or list(param.default or [])
        kwargs[param.name] = value
    return cls(**kwargs)


def build_command(
    cls: type[Component], execute: Callable[[Component, dict[str, Any]], None] | None = None
) -> click.Command:
    """A click command for a component. ``execute`` runs it; None builds a parse-only command."""

    @click.pass_context
    def callback(click_ctx: click.Context, **values: Any) -> None:
        try:
            component = component_from_values(cls, values)
        except (ValueError, TypeError) as exc:
            raise click.UsageError(str(exc), ctx=click_ctx) from None
        if execute is not None:
            execute(component, click_ctx.obj or {})

    command = click.Command(
        cls.name,
        callback=callback,
        params=[_click_param(p) for p in cls.params()],
        help=_help_text(cls),
        short_help=cls.help_summary,
        no_args_is_help=False,
    )
    command.kind = kind_of(cls)  # type: ignore[attr-defined]
    return command


def split_stages(tokens: list[str]) -> list[list[str]]:
    stages: list[list[str]] = [[]]
    for token in tokens:
        if token in (STAGE_SEPARATOR, "--"):
            stages.append([])
        else:
            stages[-1].append(token)
    if any(not stage for stage in stages):
        raise UsageError(
            "empty stage in the pipeline",
            hint="separate stages with a single `--`: web URL -- select title -- json",
        )
    return stages


def build_stage(tokens: list[str]) -> Component:
    """Parse one inline stage (``web https://x --timeout 5``) exactly like its subcommand."""
    name, *args = tokens
    cls = registry.load(name)
    if cls is None:
        close = suggest(name, registry.names())
        raise UsageError(
            f"unknown pipeline stage {name!r}",
            hint=f"did you mean {close!r}?" if close else "run `unlimited --help` to list them",
        )
    command = build_command(cls)
    try:
        with command.make_context(f"unlimited {name}", list(args)) as ctx:
            return component_from_values(cls, ctx.params)
    except (ValueError, TypeError) as exc:
        raise UsageError(f"{name}: {exc}") from None


def parse_inline(
    tokens: list[str],
) -> tuple[list[Source], list[Operator], list[Output]]:
    """Sources first, then operators, then outputs, separated by ``--``."""
    if len(tokens) == 1 and "|" in tokens[0]:
        raise UsageError(
            "pipelines run in-process, not through a shell",
            hint="separate stages with `--`: web https://example.com -- diff -- feed out.xml",
        )
    components = [build_stage(stage) for stage in split_stages(tokens)]
    kinds = [kind_of(c) for c in components]
    if kinds[0] != "source":
        raise UsageError(
            f"a pipeline starts with a source, not {kinds[0]} {components[0].name!r}",
            hint="e.g. web https://example.com -- select title",
        )
    for previous, current, component in zip(kinds, kinds[1:], components[1:], strict=False):
        if KIND_ORDER[current] < KIND_ORDER[previous]:
            raise UsageError(
                f"{current} {component.name!r} comes after an {previous}",
                hint="order stages as sources, then operators, then outputs",
            )
    sources = [c for c in components if isinstance(c, Source)]
    operators = [c for c in components if isinstance(c, Operator)]
    outputs = [c for c in components if isinstance(c, Output)]
    return sources, operators, outputs
