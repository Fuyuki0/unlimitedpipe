from __future__ import annotations

from collections.abc import Callable
from typing import Any

from unlimitedpipe.component import Operator, arg, opt
from unlimitedpipe.event import Event
from unlimitedpipe.expr import compile_expression


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class Filter(Operator):
    """Keep only events matching an expression.

    Examples: ``price > 100``, ``availability == "InStock"``,
    ``title contains "AI" and not (title contains "hiring")``. Or without expression syntax:
    ``--field country --eq Thailand``. See docs/expressions.md for the full syntax.
    """

    name = "filter"
    expr: str | None = arg("Expression to test, e.g. 'price > 100'", default=None)
    field: str | None = opt(
        "Field to test (instead of an expression)", metavar="PATH", default=None
    )
    eq: str | None = opt("--field equals this value", default=None)
    ne: str | None = opt("--field differs from this value", default=None)
    gt: float | None = opt("--field is greater than this number", default=None)
    lt: float | None = opt("--field is less than this number", default=None)
    contains: str | None = opt("--field contains this text (ignoring case)", default=None)

    def __post_init__(self) -> None:
        tests = {
            "==": self.eq,
            "!=": self.ne,
            ">": self.gt,
            "<": self.lt,
            "contains": self.contains,
        }
        given = [(op, value) for op, value in tests.items() if value is not None]
        if self.expr and (self.field or given):
            raise ValueError(
                "use either an expression or --field with --eq/--ne/--gt/--lt/--contains"
            )
        if self.expr:
            source = self.expr
        elif self.field:
            if not given:
                raise ValueError("--field needs a test: --eq, --ne, --gt, --lt or --contains")
            parts = []
            for op, value in given:
                literal = _quote(value) if isinstance(value, str) else repr(value)
                parts.append(f"`{self.field}` {op} {literal}")
            source = " and ".join(parts)
        else:
            raise ValueError(
                "give an expression, e.g. filter 'price > 100', or --field NAME --eq VALUE"
            )
        self._test: Callable[[Event], Any] = compile_expression(source)

    def process(self, event: Event) -> Event | None:
        return event if self._test(event) else None
