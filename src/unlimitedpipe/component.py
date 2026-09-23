"""Base classes for sources, operators and outputs.

A component is a dataclass whose fields are its options. The same field definitions drive the
CLI (``unlimited web URL --timeout 5``), YAML pipelines (``- type: web``) and the Python API
(``Web(url=["..."])``)::

    class HackerNews(Source):
        \"\"\"Search Hacker News stories.\"\"\"

        name = "hackernews"
        query: str = arg("Search query")
        limit: int = opt("Maximum stories", default=30)

        async def collect(self, ctx):
            ...
            yield Event(source="hackernews", type="story", data={...})

Supported option types: ``str``, ``int``, ``float``, ``bool``, ``Literal[...]``, ``X | None``
and ``list[...]`` of those.
"""

from __future__ import annotations

import dataclasses
import difflib
import inspect
import types
import typing
from collections.abc import AsyncIterator, Iterable
from dataclasses import MISSING, dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, dataclass_transform

from unlimitedpipe._version import __version__
from unlimitedpipe.errors import ConfigError, UnlimitedError

if TYPE_CHECKING:
    from unlimitedpipe.context import Context
    from unlimitedpipe.event import Event


def arg(
    help: str = "",
    *,
    default: Any = MISSING,
    default_factory: Any = MISSING,
    metavar: str | None = None,
) -> Any:
    """A positional CLI argument. In YAML it is a regular key."""
    return dataclasses.field(
        default=default,
        default_factory=default_factory,
        metadata={"help": help, "cli": "argument", "metavar": metavar},
    )


def opt(
    help: str = "",
    *,
    default: Any = MISSING,
    default_factory: Any = MISSING,
    short: str | None = None,
    metavar: str | None = None,
    secret: bool = False,
) -> Any:
    """A CLI ``--option``. ``secret`` keeps the value out of provenance (tokens, keys)."""
    return dataclasses.field(
        default=default,
        default_factory=default_factory,
        metadata={
            "help": help,
            "cli": "option",
            "short": short,
            "metavar": metavar,
            "secret": secret,
        },
    )


@dataclass(frozen=True)
class Param:
    """One option of a component, as seen by the CLI and the YAML loader."""

    name: str
    base: type
    is_list: bool
    optional: bool
    choices: tuple[str, ...] | None
    required: bool
    default: Any
    help: str
    positional: bool
    short: str | None
    metavar: str | None
    secret: bool

    @property
    def flag(self) -> str:
        return "--" + self.name.replace("_", "-")


_SCALARS = (str, int, float, bool)


def _analyze(name: str, tp: Any) -> tuple[type, bool, bool, tuple[str, ...] | None]:
    optional = False
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        members = [a for a in typing.get_args(tp) if a is not type(None)]
        optional = len(members) < len(typing.get_args(tp))
        if len(members) != 1:
            raise TypeError(f"option {name!r}: unions other than `X | None` are not supported")
        tp = members[0]
        origin = typing.get_origin(tp)
    is_list = origin is list
    if is_list:
        (tp,) = typing.get_args(tp)
        origin = typing.get_origin(tp)
    choices = None
    if origin is Literal:
        choices = tuple(str(c) for c in typing.get_args(tp))
        tp = str
    if tp not in _SCALARS:
        raise TypeError(f"option {name!r}: unsupported type {tp!r}")
    return tp, is_list, optional, choices


def params_of(cls: type[Component]) -> list[Param]:
    cached = cls.__dict__.get("_params_cache")
    if cached is not None:
        return cached
    hints = typing.get_type_hints(cls)
    params: list[Param] = []
    for f in dataclasses.fields(cls):  # type: ignore[arg-type]
        if not f.init or f.name.startswith("_"):
            continue
        base, is_list, optional, choices = _analyze(f.name, hints[f.name])
        if f.default is not MISSING:
            default, required = f.default, False
        elif f.default_factory is not MISSING:
            default, required = f.default_factory(), False
        else:
            default, required = None, True
        meta = f.metadata
        params.append(
            Param(
                name=f.name,
                base=base,
                is_list=is_list,
                optional=optional,
                choices=choices,
                required=required,
                default=default,
                help=meta.get("help", ""),
                positional=meta.get("cli") == "argument",
                short=meta.get("short"),
                metavar=meta.get("metavar"),
                secret=meta.get("secret", False),
            )
        )
    cls._params_cache = params  # type: ignore[attr-defined]
    return params


_TRUE = {"true", "yes", "on", "1"}
_FALSE = {"false", "no", "off", "0"}


def _coerce_scalar(param: Param, value: Any) -> Any:
    base = param.base
    if isinstance(value, (dict, list)):
        raise ValueError(f"expected a {base.__name__}, got a {type(value).__name__}")
    if base is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in _TRUE | _FALSE:
            return value.lower() in _TRUE
        raise ValueError(f"expected true or false, got {value!r}")
    if isinstance(value, bool):
        raise ValueError(f"expected a {base.__name__}, got {value!r}")
    if base is int:
        if isinstance(value, float) and value.is_integer():
            return int(value)
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(f"expected an integer, got {value!r}") from None
    if base is float:
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(f"expected a number, got {value!r}") from None
    text = str(value)
    if param.choices and text not in param.choices:
        raise ValueError(f"expected one of {', '.join(param.choices)}; got {text!r}")
    return text


def coerce(param: Param, value: Any) -> Any:
    """Convert a YAML value to the option's type. Raises ValueError with a readable message."""
    if value is None:
        if param.is_list:
            return []
        if param.optional or not param.required:
            return None if param.optional else param.default
        raise ValueError("is required")
    if param.is_list:
        items = value if isinstance(value, list) else [value]
        return [_coerce_scalar(param, item) for item in items]
    return _coerce_scalar(param, value)


def suggest(name: str, options: Iterable[str]) -> str | None:
    match = difflib.get_close_matches(name, list(options), n=1, cutoff=0.6)
    return match[0] if match else None


RESERVED = frozenset(
    {"name", "version", "examples", "help_summary", "help_text", "finite", "buffering", "bounded"}
)


def _check_reserved(cls: type) -> None:
    """Options must not shadow the attributes UnlimitedPipe reads from every component."""
    for option, annotation in inspect.get_annotations(cls).items():
        text = annotation if isinstance(annotation, str) else repr(annotation)
        if option in RESERVED and "ClassVar" not in text:
            raise TypeError(
                f"{cls.__name__}.{option}: {option!r} is reserved for components; "
                "give the option another name"
            )


def kind_of(component: Component | type[Component]) -> str:
    """``source``, ``operator`` or ``output``: decided by the base class, never an attribute."""
    cls = component if isinstance(component, type) else type(component)
    for base, kind in ((Source, "source"), (Operator, "operator"), (Output, "output")):
        if issubclass(cls, base):
            return kind
    return ""


def _default_empty_options(cls: type) -> None:
    """``list`` options default to ``[]`` and ``bool`` options to False unless told otherwise."""
    annotations = inspect.get_annotations(cls)
    for name, value in list(cls.__dict__.items()):
        if not isinstance(value, dataclasses.Field) or name not in annotations:
            continue
        if value.default is not MISSING or value.default_factory is not MISSING:
            continue
        annotation = annotations[name]
        text = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", "")
        if text.startswith("list[") or typing.get_origin(annotation) is list:
            value.default_factory = list
        elif text == "bool" or annotation is bool:
            value.default = False


@dataclass_transform(kw_only_default=True, field_specifiers=(arg, opt, dataclasses.field))
class Component:
    """Base class of every source, operator and output."""

    name: ClassVar[str] = ""
    version: ClassVar[str] = __version__
    help_summary: ClassVar[str] = ""  # from the docstring; option names cannot clash with these
    help_text: ClassVar[str] = ""
    examples: ClassVar[tuple[str, ...]] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        doc = cls.__dict__.get("__doc__") or ""
        paragraphs = [p.strip() for p in doc.strip().split("\n\n") if p.strip()]
        _check_reserved(cls)
        cls.help_summary = " ".join(paragraphs[0].split()).replace("``", "`") if paragraphs else ""
        cls.help_text = "\n\n".join(" ".join(p.split()) for p in paragraphs).replace("``", "`")
        _default_empty_options(cls)
        dataclass(kw_only=True)(cls)

    @classmethod
    def params(cls) -> list[Param]:
        return params_of(cls)

    @classmethod
    def from_options(cls, options: dict[str, Any]) -> Component:
        """Build a component from a YAML mapping, validating every option.

        Raises ConfigError whose message names the offending option.
        """
        params = {p.name: p for p in cls.params()}
        kwargs: dict[str, Any] = {}
        for key, value in options.items():
            name = str(key).replace("-", "_")
            param = params.get(name)
            if param is None:
                hint = suggest(name, params)
                valid = ", ".join(params) or "(none)"
                raise ConfigError(
                    f"unknown option {key!r} for {cls.name}",
                    hint=f"did you mean {hint!r}?" if hint else f"valid options: {valid}",
                )
            try:
                kwargs[name] = coerce(param, value)
            except ValueError as exc:
                raise ConfigError(f"option {key!r} of {cls.name}: {exc}") from None
        missing = [p.name for p in params.values() if p.required and p.name not in kwargs]
        if missing:
            raise ConfigError(f"{cls.name} needs option {missing[0]!r}")
        try:
            return cls(**kwargs)
        except (ValueError, TypeError) as exc:
            raise ConfigError(str(exc)) from None
        except UnlimitedError as exc:
            raise ConfigError(exc.message, hint=exc.hint) from None

    def provenance_step(self) -> dict[str, Any] | None:
        """What this component adds to each event's provenance (None to add nothing)."""
        step: dict[str, Any] = {"step": self.name, "version": self.version}
        if isinstance(self, Operator):
            args = {
                p.name: getattr(self, p.name)
                for p in self.params()
                if not p.secret and getattr(self, p.name) != p.default
            }
            if args:
                step["args"] = args
        return step


class Source(Component):
    """Emits events. Implement ``collect``."""

    finite: ClassVar[bool] = True

    def collect(self, ctx: Context) -> AsyncIterator[Event]:
        raise NotImplementedError


class Operator(Component):
    """Transforms a stream of events.

    Override ``process`` for per-event work (return an event, several, or None to drop it), or
    ``apply`` when you need the whole stream (sorting, windows, state).
    """

    buffering: ClassVar[bool] = False  # needs the whole stream before emitting (sort)
    bounded: ClassVar[bool] = False  # always ends the stream after finitely many events (limit)

    def process(self, event: Event) -> Event | Iterable[Event] | None:
        raise NotImplementedError

    async def apply(self, events: AsyncIterator[Event], ctx: Context) -> AsyncIterator[Event]:
        from unlimitedpipe.event import Event

        async for event in events:
            result = self.process(event)
            if result is None:
                continue
            if isinstance(result, Event):
                yield result
            else:
                for item in result:
                    yield item


class Output(Component):
    """Consumes events: ``open`` once, ``write`` per event, ``close`` once (also on Ctrl+C)."""

    async def open(self, ctx: Context) -> None:
        return None

    async def write(self, event: Event) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        return None
