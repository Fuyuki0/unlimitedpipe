"""Where component names come from: built-ins, plus plugins installed with pip.

A plugin package registers its classes under the ``unlimitedpipe.plugins`` entry point group::

    [project.entry-points."unlimitedpipe.plugins"]
    hackernews = "unlimitedpipe_hackernews:HackerNews"

After ``pip install unlimitedpipe-hackernews``, ``unlimited hackernews`` and
``- type: hackernews`` work with no further setup.

Modules are imported only when a component is used, which keeps every pipe stage fast.
"""

from __future__ import annotations

import importlib
import logging
from functools import cache
from importlib.metadata import EntryPoint, entry_points

from unlimitedpipe.component import Component, kind_of

log = logging.getLogger("unlimitedpipe")

ENTRY_POINT_GROUP = "unlimitedpipe.plugins"

BUILTINS: dict[str, str] = {
    # sources
    "web": "unlimitedpipe.sources.web:Web",
    "rss": "unlimitedpipe.sources.rss:Rss",
    "file": "unlimitedpipe.sources.file:File",
    "inspect": "unlimitedpipe.sources.inspect:Inspect",
    # operators
    "select": "unlimitedpipe.operators.select:Select",
    "filter": "unlimitedpipe.operators.filter:Filter",
    "map": "unlimitedpipe.operators.map:Map",
    "grep": "unlimitedpipe.operators.grep:Grep",
    "dedupe": "unlimitedpipe.operators.dedupe:Dedupe",
    "limit": "unlimitedpipe.operators.limit:Limit",
    "sort": "unlimitedpipe.operators.sort:Sort",
    "diff": "unlimitedpipe.operators.diff:Diff",
    # outputs
    "jsonl": "unlimitedpipe.outputs.jsonl:Jsonl",
    "json": "unlimitedpipe.outputs.json:Json",
    "csv": "unlimitedpipe.outputs.csv:Csv",
    "feed": "unlimitedpipe.outputs.feed:Feed",
    "pretty": "unlimitedpipe.outputs.pretty:Pretty",
}


def _import(target: str) -> type[Component]:
    module, _, attribute = target.partition(":")
    return getattr(importlib.import_module(module), attribute)


@cache
def plugins() -> dict[str, EntryPoint]:
    found: dict[str, EntryPoint] = {}
    for entry in entry_points(group=ENTRY_POINT_GROUP):
        if entry.name in BUILTINS:
            log.warning("plugin %r ignored: the name is taken by a built-in", entry.name)
            continue
        found[entry.name] = entry
    return found


def names() -> list[str]:
    return [*BUILTINS, *sorted(plugins())]


@cache
def load(name: str) -> type[Component] | None:
    """The component class registered as ``name``, or None."""
    if name in BUILTINS:
        return _import(BUILTINS[name])
    entry = plugins().get(name)
    if entry is None:
        return None
    try:
        cls = entry.load()
    except Exception as exc:
        log.warning("plugin %r failed to load: %s", name, exc)
        return None
    if not (isinstance(cls, type) and issubclass(cls, Component) and kind_of(cls)):
        log.warning("plugin %r is not a Source, Operator or Output subclass", name)
        return None
    return cls
