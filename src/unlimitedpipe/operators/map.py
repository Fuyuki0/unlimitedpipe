from __future__ import annotations

from unlimitedpipe.component import Operator, arg, opt
from unlimitedpipe.event import Event
from unlimitedpipe.expr import compile_expression
from unlimitedpipe.fields import delete_path, split_path


class Map(Operator):
    """Set fields from expressions and drop fields.

    Each assignment is NAME=EXPRESSION: ``price=offers.0.price``, ``title=upper(title)``,
    ``cheap='price < 20'``, ``currency='"USD"'`` (quote literal text). Assignments run in order,
    so later ones see earlier results.
    """

    name = "map"
    assign: list[str] = arg("NAME=EXPRESSION assignments", default_factory=list)
    drop: list[str] = opt("Remove this field (repeatable)", short="-d", metavar="PATH")

    def __post_init__(self) -> None:
        if not self.assign and not self.drop:
            raise ValueError("map needs NAME=EXPRESSION assignments or --drop FIELD")
        self._assignments = []
        for item in self.assign:
            name, sep, source = item.partition("=")
            if not sep or not name.strip() or not source.strip():
                raise ValueError(f"invalid assignment {item!r}; use NAME=EXPRESSION")
            self._assignments.append((split_path(name), compile_expression(source)))
        self._drops = [split_path(path) for path in self.drop]

    def process(self, event: Event) -> Event:
        for parts, expression in self._assignments:
            value = expression(event)
            target = event.data
            for part in parts[:-1]:
                child = target.get(part)
                if not isinstance(child, dict):
                    child = target[part] = {}
                target = child
            target[parts[-1]] = value
        for parts in self._drops:
            delete_path(event.data, parts)
        return event
