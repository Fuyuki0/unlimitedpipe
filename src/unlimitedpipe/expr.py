"""A small, safe expression language for ``filter`` and ``map``. Never uses ``eval``.

Examples::

    price > 100
    availability == "InStock" and price <= 50
    title contains "security" or categories contains "security"
    country in ["Thailand", "Vietnam"]
    not exists(summary)
    lower(author) startswith "a"

Rules:

* A bare word is a field path (``offers.0.price``), looked up in ``data`` first, then the
  envelope. Quote literal text: ``"InStock"``. Backticks quote odd paths: ```og:title```.
* Numbers compare numerically, also when the field holds a numeric string (``"89.00"``).
* ``contains``, ``startswith``, ``endswith`` and ``in`` on text ignore case; ``==`` does not.
* ``matches`` is a Python regular expression search.
* ``+`` adds numbers and joins text: ``"https://nvd.nist.gov/vuln/detail/" + cveID``.
* ``replace(text, pattern, replacement)`` substitutes a regular expression:
  ``replace(summary, "^arXiv:\\S+ .*? Abstract: ", "")``.
* A missing field is ``null``; ordering comparisons with ``null`` are false.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from unlimitedpipe.errors import ExpressionError
from unlimitedpipe.fields import MISSING, resolve, split_path

if TYPE_CHECKING:
    from unlimitedpipe.event import Event

_TOKEN = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<number>-?\d+(?:\.\d+)?(?![\w.]))
  | (?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<quoted>`[^`]+`)
  | (?P<op>==|!=|>=|<=|&&|\|\||[<>=!+])
  | (?P<punct>[()\[\],])
  | (?P<word>[A-Za-z_$@][\w$@:-]*(?:\.[\w$@:-]+)*)
    """,
    re.VERBOSE,
)

_KEYWORDS = {"and", "or", "not", "contains", "in", "startswith", "endswith", "matches"}
_LITERALS = {"true": True, "false": False, "null": None}
_COMPARISONS = {
    "==",
    "=",
    "!=",
    ">",
    ">=",
    "<",
    "<=",
    "contains",
    "in",
    "startswith",
    "endswith",
    "matches",
}
_NUMERIC = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*$")

Node = tuple[Any, ...]


class _Parser:
    def __init__(self, source: str) -> None:
        self.source = source
        self.tokens: list[tuple[str, Any, int]] = []
        pos = 0
        while pos < len(source):
            match = _TOKEN.match(source, pos)
            if match is None:
                self.fail(f"unexpected character {source[pos]!r}", pos)
            assert match is not None
            kind = match.lastgroup or ""
            text = match.group()
            if kind == "number":
                self.tokens.append(("lit", float(text) if "." in text else int(text), pos))
            elif kind == "string":
                body = text[1:-1]
                self.tokens.append(("lit", re.sub(r"\\(.)", r"\1", body), pos))
            elif kind == "quoted":
                self.tokens.append(("path", text[1:-1], pos))
            elif kind == "word":
                lowered = text.lower()
                if lowered in _LITERALS:
                    self.tokens.append(("lit", _LITERALS[lowered], pos))
                elif lowered in _KEYWORDS:
                    self.tokens.append(("kw", lowered, pos))
                else:
                    self.tokens.append(("path", text, pos))
            elif kind in ("op", "punct"):
                self.tokens.append((kind, text, pos))
            pos = match.end()
        self.tokens.append(("end", None, len(source)))
        self.index = 0

    def fail(self, reason: str, pos: int) -> None:
        pointer = " " * pos + "^"
        raise ExpressionError(
            f"invalid expression: {reason}\n  {self.source}\n  {pointer}",
            hint='quote text values, e.g. availability == "InStock"',
        )

    def peek(self) -> tuple[str, Any, int]:
        return self.tokens[self.index]

    def take(self) -> tuple[str, Any, int]:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def at(self, *values: str) -> bool:
        kind, value, _ = self.peek()
        return kind in ("kw", "op", "punct") and value in values

    def expect(self, value: str) -> None:
        if not self.at(value):
            _, found, pos = self.peek()
            self.fail(f"expected {value!r}" + (f", found {found!r}" if found else ""), pos)
        self.take()

    def parse(self) -> Node:
        node = self.parse_or()
        kind, value, pos = self.peek()
        if kind != "end":
            self.fail(f"unexpected {value!r}", pos)
        return node

    def parse_or(self) -> Node:
        node = self.parse_and()
        while self.at("or", "||"):
            self.take()
            node = ("or", node, self.parse_and())
        return node

    def parse_and(self) -> Node:
        node = self.parse_not()
        while self.at("and", "&&"):
            self.take()
            node = ("and", node, self.parse_not())
        return node

    def parse_not(self) -> Node:
        if self.at("not", "!"):
            self.take()
            return ("not", self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self) -> Node:
        left = self.parse_sum()
        kind, value, _ = self.peek()
        if kind in ("op", "kw") and value in _COMPARISONS:
            self.take()
            return ("cmp", "==" if value == "=" else value, left, self.parse_sum())
        return left

    def parse_sum(self) -> Node:
        node = self.parse_value()
        while self.at("+"):
            self.take()
            node = ("add", node, self.parse_value())
        return node

    def parse_value(self) -> Node:
        kind, value, pos = self.take()
        if kind == "lit":
            return ("lit", value)
        if kind == "path":
            if self.at("("):
                return self.parse_call(value, pos)
            return ("path", split_path(value))
        if kind == "punct" and value == "(":
            node = self.parse_or()
            self.expect(")")
            return node
        if kind == "punct" and value == "[":
            items: list[Node] = []
            while not self.at("]"):
                items.append(self.parse_value())
                if not self.at("]"):
                    self.expect(",")
            self.take()
            return ("list", items)
        self.fail("expected a value" if kind == "end" else f"unexpected {value!r}", pos)
        raise AssertionError  # unreachable

    def parse_call(self, name: str, pos: int) -> Node:
        function = name.lower()
        if function not in _FUNCTIONS:
            self.fail(f"unknown function {name!r} (known: {', '.join(sorted(_FUNCTIONS))})", pos)
        self.expect("(")
        arguments = [self.parse_or()]
        while self.at(","):
            self.take()
            arguments.append(self.parse_or())
        self.expect(")")
        expected = _ARITY.get(function, 1)
        if len(arguments) != expected:
            self.fail(f"{function}() takes {expected} argument(s), got {len(arguments)}", pos)
        if function == "exists" and arguments[0][0] != "path":
            self.fail("exists() takes a field name", pos)
        return ("call", function, arguments)


def _as_number(value: Any) -> float | int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str) and _NUMERIC.match(value):
        return float(value)
    return None


def _equal(left: Any, right: Any) -> bool:
    ln, rn = _as_number(left), _as_number(right)
    if ln is not None and rn is not None:
        return ln == rn
    return left == right


def _fold(value: Any) -> Any:
    return value.casefold() if isinstance(value, str) else value


def _compare(op: str, left: Any, right: Any) -> bool:
    if op == "==":
        return _equal(left, right)
    if op == "!=":
        return not _equal(left, right)
    if op in (">", ">=", "<", "<="):
        ln, rn = _as_number(left), _as_number(right)
        if ln is not None and rn is not None:
            left, right = ln, rn
        elif not (isinstance(left, str) and isinstance(right, str)):
            return False
        return {
            ">": left > right,
            ">=": left >= right,
            "<": left < right,
            "<=": left <= right,
        }[op]
    if op == "contains":
        if isinstance(left, str) and isinstance(right, str):
            return right.casefold() in left.casefold()
        if isinstance(left, list):
            return any(_fold(item) == _fold(right) or _equal(item, right) for item in left)
        return False
    if op == "in":
        if isinstance(right, list):
            return any(_fold(item) == _fold(left) or _equal(item, left) for item in right)
        if isinstance(left, str) and isinstance(right, str):
            return left.casefold() in right.casefold()
        return False
    if op in ("startswith", "endswith"):
        if not (isinstance(left, str) and isinstance(right, str)):
            return False
        method = str.startswith if op == "startswith" else str.endswith
        return method(left.casefold(), right.casefold())
    if op == "matches":
        if left is None or right is None:
            return False
        return _regex(str(right)).search(str(left)) is not None
    raise AssertionError(op)


@lru_cache(maxsize=128)
def _regex(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ExpressionError(f"invalid regular expression {pattern!r}: {exc}") from None


def _number(value: Any) -> float | int | None:
    from unlimitedpipe.structured import parse_price

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return parse_price(value) if isinstance(value, str) else None


def _replace(value: Any, pattern: Any, replacement: Any) -> Any:
    if not isinstance(value, str):
        return value
    return _regex(str(pattern)).sub(str(replacement), value)


_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "replace": _replace,
    "lower": lambda v: v.lower() if isinstance(v, str) else v,
    "upper": lambda v: v.upper() if isinstance(v, str) else v,
    "trim": lambda v: v.strip() if isinstance(v, str) else v,
    "len": lambda v: len(v) if isinstance(v, (str, list, dict)) else 0,
    "number": _number,
    "exists": lambda v: v is not MISSING,
}
_ARITY = {"replace": 3}


def _evaluate(node: Node, event: Event) -> Any:
    tag = node[0]
    if tag == "lit":
        return node[1]
    if tag == "path":
        value = resolve(event, node[1])
        return None if value is MISSING else value
    if tag == "cmp":
        return _compare(node[1], _evaluate(node[2], event), _evaluate(node[3], event))
    if tag == "and":
        return bool(_evaluate(node[1], event)) and bool(_evaluate(node[2], event))
    if tag == "or":
        return bool(_evaluate(node[1], event)) or bool(_evaluate(node[2], event))
    if tag == "not":
        return not _evaluate(node[1], event)
    if tag == "list":
        return [_evaluate(item, event) for item in node[1]]
    if tag == "add":
        left, right = _evaluate(node[1], event), _evaluate(node[2], event)
        ln, rn = _as_number(left), _as_number(right)
        if (
            ln is not None
            and rn is not None
            and not (isinstance(left, str) and isinstance(right, str))
        ):
            return ln + rn
        if left is None or right is None:
            return None  # a missing part makes the whole value missing, not "None"
        return f"{left}{right}"
    if tag == "call":
        if node[1] == "exists":
            return resolve(event, node[2][0][1]) is not MISSING
        return _FUNCTIONS[node[1]](*(_evaluate(argument, event) for argument in node[2]))
    raise AssertionError(tag)


def compile_expression(source: str) -> Callable[[Event], Any]:
    """Parse ``source`` once; return a function evaluating it against an event."""
    if not source.strip():
        raise ExpressionError("empty expression")
    tree = _Parser(source).parse()
    return lambda event: _evaluate(tree, event)
