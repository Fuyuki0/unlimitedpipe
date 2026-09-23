"""YAML pipelines: the same components as the CLI, run in one process.

::

    name: competitor-watch
    sources:
      - type: web
        url: https://competitor.example/pricing
        each: .plan
        field: [name=.plan-name, price=.price]
    operators:
      - type: diff
        key: name
    outputs:
      - type: feed
        path: public/changes.xml

Relative paths (``path``, ``state``) are resolved from the pipeline file's directory.
Every error names the file, line and option at fault.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from unlimitedpipe import registry
from unlimitedpipe.component import Component, Operator, Output, Source, kind_of, suggest
from unlimitedpipe.errors import ConfigError

SECTIONS = {"sources": "source", "operators": "operator", "outputs": "output"}
TOP_LEVEL = {"name", "description", "sources", "operators", "outputs", "settings"}
SETTINGS = {"errors_as_events"}
PATH_OPTIONS = {"path", "state"}


@dataclass
class Pipeline:
    name: str
    sources: list[Source]
    operators: list[Operator] = field(default_factory=list)
    outputs: list[Output] = field(default_factory=list)
    errors_as_events: bool = False


class _Locator:
    """Maps a path like ``["operators", 1, "by"]`` to its line in the YAML file."""

    def __init__(self, text: str) -> None:
        try:
            self.root = yaml.compose(text, Loader=yaml.SafeLoader)
        except yaml.YAMLError:
            self.root = None

    def line(self, *path: str | int) -> int | None:
        node = self.root
        line = node.start_mark.line + 1 if node is not None else None
        for step in path:
            if isinstance(node, yaml.MappingNode):
                node = next((v for k, v in node.value if k.value == step), None)
            elif (
                isinstance(node, yaml.SequenceNode)
                and isinstance(step, int)
                and step < len(node.value)
            ):
                node = node.value[step]
            else:
                node = None
            if node is None:
                break
            line = node.start_mark.line + 1
        return line


def load_pipeline(path: Path) -> Pipeline:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror or exc}") from None
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"{path}:{mark.line + 1}" if mark else str(path)
        problem = getattr(exc, "problem", None) or str(exc)
        raise ConfigError(f"{where}: invalid YAML: {problem}") from None
    return parse_pipeline(
        document, source_name=str(path), base_dir=path.parent, text=text, default_name=path.stem
    )


def parse_pipeline(
    document: Any,
    *,
    source_name: str = "<pipeline>",
    base_dir: Path | None = None,
    text: str | None = None,
    default_name: str = "pipeline",
) -> Pipeline:
    locator = _Locator(text) if text is not None else None

    def fail(message: str, *path: str | int, hint: str | None = None) -> ConfigError:
        line = locator.line(*path) if locator else None
        where = f"{source_name}:{line}" if line else source_name
        return ConfigError(f"{where}: {message}", hint=hint)

    if not isinstance(document, dict):
        raise fail("a pipeline must be a mapping with `sources`, `operators` and `outputs`")
    for key in document:
        if key not in TOP_LEVEL:
            close = suggest(str(key), TOP_LEVEL)
            raise fail(
                f"unknown key {key!r}",
                str(key),
                hint=f"did you mean {close!r}?"
                if close
                else f"valid keys: {', '.join(sorted(TOP_LEVEL))}",
            )
    name = document.get("name") or default_name
    if not isinstance(name, str):
        raise fail("`name` must be text", "name")
    settings = document.get("settings") or {}
    if not isinstance(settings, dict):
        raise fail("`settings` must be a mapping", "settings")
    for key in settings:
        if key not in SETTINGS:
            raise fail(
                f"unknown setting {key!r}",
                "settings",
                str(key),
                hint=f"valid: {', '.join(sorted(SETTINGS))}",
            )

    built: dict[str, list[Component]] = {}
    for section, kind in SECTIONS.items():
        entries = document.get(section) or []
        if not isinstance(entries, list):
            raise fail(f"`{section}` must be a list", section)
        built[section] = []
        for index, entry in enumerate(entries):
            built[section].append(_build(entry, section, kind, index, base_dir, fail))
    if not built["sources"]:
        raise fail(
            "a pipeline needs at least one source",
            hint="add e.g.\nsources:\n  - type: web\n    url: https://example.com",
        )

    diffs = [op for op in built["operators"] if op.name == "diff"]
    for number, op in enumerate(diffs, 1):
        if getattr(op, "namespace", None) is None and getattr(op, "state", None) is None:
            op.namespace = name if number == 1 else f"{name}-{number}"  # type: ignore[attr-defined]

    return Pipeline(
        name=name,
        sources=built["sources"],  # type: ignore[arg-type]
        operators=built["operators"],  # type: ignore[arg-type]
        outputs=built["outputs"],  # type: ignore[arg-type]
        errors_as_events=bool(settings.get("errors_as_events", False)),
    )


def _build(
    entry: Any, section: str, kind: str, index: int, base_dir: Path | None, fail
) -> Component:
    where = f"{section}[{index}]"
    if isinstance(entry, str):
        entry = {"type": entry}
    if not isinstance(entry, dict):
        raise fail(f"{where} must be a mapping with a `type`", section, index)
    type_name = entry.get("type")
    if not isinstance(type_name, str):
        raise fail(f"{where} needs a `type`", section, index, hint=f"e.g. - type: {_example(kind)}")
    cls = registry.load(type_name)
    if cls is not None:
        where = f"{where} ({type_name})"
    if cls is None:
        close = suggest(type_name, [n for n in registry.names() if _kind_of(n) == kind])
        raise fail(
            f"{where}: unknown {kind} type {type_name!r}",
            section,
            index,
            "type",
            hint=f"did you mean {close!r}?"
            if close
            else "run `unlimited --help` to list components",
        )
    actual = kind_of(cls)
    if actual != kind:
        article = "an" if actual[0] in "aeiou" else "a"
        raise fail(
            f"{where}: {type_name!r} is {article} {actual}, not a {kind}", section, index, "type"
        )
    options = {k: v for k, v in entry.items() if k != "type"}
    if base_dir is not None:
        for key in PATH_OPTIONS & options.keys():
            value = options[key]
            if isinstance(value, str) and value != "-":
                options[key] = str((base_dir / Path(value).expanduser()).resolve())
            elif isinstance(value, list):
                options[key] = [
                    str((base_dir / Path(v).expanduser()).resolve())
                    if isinstance(v, str) and v != "-"
                    else v
                    for v in value
                ]
    try:
        return cls.from_options(options)
    except ConfigError as exc:
        bad = next((k for k in options if repr(k) in exc.message), None)
        path = (section, index, bad) if bad else (section, index)
        raise fail(f"{where}: {exc.message}", *path, hint=exc.hint) from None


def _kind_of(name: str) -> str | None:
    cls = registry.load(name)
    return kind_of(cls) if cls else None


def _example(kind: str) -> str:
    return {"source": "web", "operator": "filter", "output": "jsonl"}[kind]
