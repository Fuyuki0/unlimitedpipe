from __future__ import annotations

from unlimitedpipe.component import Operator, arg
from unlimitedpipe.event import Event
from unlimitedpipe.fields import MISSING, resolve, split_path


def parse_field_specs(specs: list[str]) -> list[tuple[str, list[str]]]:
    """``title`` -> (title, [title]); ``price=offers.0.price`` -> (price, [offers, 0, price])."""
    parsed: list[tuple[str, list[str]]] = []
    for spec in specs:
        name, sep, path = spec.partition("=")
        if sep:
            name, path = name.strip(), path.strip()
            if not name or not path:
                raise ValueError(f"invalid field {spec!r}; use NAME=PATH")
        else:
            path = spec.strip()
            name = split_path(path)[-1]
        parsed.append((name, split_path(path)))
    names = [name for name, _ in parsed]
    clashes = sorted({name for name in names if names.count(name) > 1})
    if clashes:
        raise ValueError(
            f"two fields would both be named {clashes[0]!r}; rename one with NAME=PATH"
        )
    return parsed


class Select(Operator):
    """Keep only the given fields in each event's data.

    Fields are looked up in data first, then in the envelope (``source_url``,
    ``metadata.status``). Rename with NAME=PATH, e.g. ``price=offers.0.price``. Missing fields
    become null so every event has the same shape. The envelope and provenance are kept.
    """

    name = "select"
    fields: list[str] = arg("Fields to keep: `title`, `offers.0.price`, `price=offers.0.price`")

    def __post_init__(self) -> None:
        if not self.fields:
            raise ValueError("select needs at least one field")
        self._specs = parse_field_specs(self.fields)

    def process(self, event: Event) -> Event:
        selected = {}
        for name, parts in self._specs:
            value = resolve(event, parts)
            selected[name] = None if value is MISSING else value
        event.data = selected
        return event
