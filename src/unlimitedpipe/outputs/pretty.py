"""Human-readable terminal output. Used automatically when stdout is a terminal."""

from __future__ import annotations

import difflib
import json
from collections.abc import Callable
from typing import Any

from unlimitedpipe.component import Output
from unlimitedpipe.event import Event
from unlimitedpipe.fields import flatten


def _clip(value: Any, width: int = 100) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _price(data: dict[str, Any]) -> str:
    price = data.get("price")
    if price is None:
        return ""
    amount = f"{price:,.2f}" if isinstance(price, (int, float)) else str(price)
    return f"{amount} {data.get('currency') or ''}".strip()


class Pretty(Output):
    """Show events in a readable form for people. Pipes should use jsonl instead."""

    name = "pretty"

    async def open(self, ctx) -> None:
        from rich.console import Console

        self._console = Console(highlight=False)
        self._count = 0
        self._last_type = ""

    async def write(self, event: Event) -> None:
        from rich.text import Text

        renderer = _RENDERERS.get(event.type, _record)
        lines: list[Text] = renderer(event)
        compact = event.type in ("count", "trend") and event.type == self._last_type
        if self._count and not compact:
            self._console.print()
        self._last_type = event.type
        for line in lines:
            self._console.print(line, overflow="ellipsis", no_wrap=True, crop=True)
        self._count += 1


def _dim(text: str):
    from rich.text import Text

    return Text(text, style="dim")


def _document(event: Event):
    from rich.text import Text

    d, m = event.data, event.metadata
    lines = [Text(d.get("title") or "(untitled)", style="bold")]
    facts = [d.get("url") or event.source_url, m.get("status"), m.get("method")]
    if m.get("elapsed_ms") is not None:
        facts.append(f"{m['elapsed_ms']} ms")
    if m.get("not_modified"):
        facts.append("not modified")
    lines.append(_dim("  ·  ".join(str(f) for f in facts if f)))
    if d.get("description"):
        lines.append(Text(_clip(d["description"], 200)))
    for heading in (d.get("headings") or [])[:6]:
        lines.append(Text(f"{'#' * heading.get('level', 1)} {_clip(heading.get('text', ''), 90)}"))
    if d.get("text"):
        lines.append(_dim(_clip(d["text"], 240)))
    stats = [f"{d.get('word_count', 0)} words"]
    if "links" in d:
        stats.append(f"{len(d['links'])} links")
    if d.get("feeds"):
        stats.append(f"feeds: {', '.join(d['feeds'][:2])}")
    if d.get("structured"):
        stats.append(f"structured: {', '.join(d['structured'][:4])}")
    lines.append(_dim(" · ".join(stats)))
    return lines


def _product(event: Event):
    from rich.text import Text

    d = event.data
    availability = d.get("availability") or ""
    style = "green" if availability in ("InStock", "available") else "red" if availability else ""
    line = Text.assemble(
        (d.get("name") or "(product)", "bold"),
        "  ",
        (_price(d), "bold cyan"),
        "  ",
        (availability, style),
    )
    facts = [d.get("url") or event.source_url]
    if d.get("sku"):
        facts.append(f"sku {d['sku']}")
    facts.append(f"via {event.metadata.get('method', event.source)}")
    return [line, _dim("  ·  ".join(str(f) for f in facts if f))]


def _entry(event: Event):
    from rich.text import Text

    d = event.data
    date = (d.get("published_at") or event.timestamp or "")[:10]
    lines = [
        Text.assemble(
            (date + "  " if date else "", "dim"), (d.get("title") or "(untitled)", "bold")
        )
    ]
    feed = (d.get("feed") or {}).get("title")
    lines.append(_dim("  ·  ".join(str(x) for x in (d.get("link"), feed) if x)))
    if d.get("summary"):
        lines.append(Text(_clip(d["summary"], 200)))
    return lines


def _element(event: Event):
    from rich.text import Text

    d = event.data
    label = f"{d.get('selector')} #{d.get('index', 0)}"
    return [Text.assemble((label, "dim"), "  ", _clip(d.get("text") or "", 160))]


def _link(event: Event):
    from rich.text import Text

    d = event.data
    return [
        Text.assemble((_clip(d.get("text") or "", 60), "bold"), "  ", (d.get("url") or "", "cyan"))
    ]


def _text_diff(old: str, new: str):
    from rich.text import Text

    lines = []
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0):
        if line.startswith(("---", "+++", "@@")):
            continue
        style = "green" if line.startswith("+") else "red"
        lines.append(Text("      " + _clip(line, 110), style=style))
        if len(lines) == 8:
            lines.append(_dim("      …"))
            break
    return lines


def _change(event: Event):
    from rich.text import Text

    d = event.data
    kind = str(d.get("change"))
    label = d.get("label") or event.key or ""
    heading = {
        "added": ("NEW", "bold green"),
        "removed": ("REMOVED", "bold red"),
    }.get(kind, ("CHANGE DETECTED", "bold yellow"))
    lines = [Text.assemble(heading, "  ", (label, "bold"))]
    for change in d.get("fields") or []:
        old, new = change.get("old"), change.get("new")
        if isinstance(old, str) and isinstance(new, str) and (len(old) > 60 or "\n" in old + new):
            lines.append(Text(f"  {change['path']}"))
            lines.extend(_text_diff(old, new))
        else:
            lines.append(
                Text.assemble(
                    f"  {change['path']}  ",
                    (_clip(old, 50) if old is not None else "none", "red"),
                    " → ",
                    (_clip(new, 50) if new is not None else "none", "green"),
                )
            )
    item = d.get("after") or d.get("before") or {}
    item = item if isinstance(item, dict) else {}
    if kind in ("added", "removed"):
        facts = [
            f"{key} {_clip(value, 40)}"
            for key, value in item.items()
            if key not in ("title", "name", "label", "link", "url", "summary", "text", "id")
            and isinstance(value, (str, int, float))
            and value != ""
            and value is not False
        ][:4]
        if facts:
            lines.append(Text("  " + " · ".join(facts)))
    link = item.get("link") or item.get("url")
    if link or event.source_url:
        lines.append(_dim(f"  {link or event.source_url}"))
    return lines


def _error(event: Event):
    from rich.text import Text

    d = event.data
    return [Text.assemble(("ERROR  ", "bold red"), d.get("url") or "", "  ", d.get("error") or "")]


def _inspection(event: Event):
    from rich.text import Text

    d, m = event.data, event.metadata
    facts = [m.get("status"), m.get("content_type"), f"{m.get('elapsed_ms')} ms"]
    lines = [
        Text(d.get("title") or d.get("url") or "", style="bold"),
        _dim("  ·  ".join(str(f) for f in [d.get("url"), *facts] if f)),
    ]
    for check in d.get("checks") or []:
        mark = ("✓", "green") if check.get("ok") else ("✗", "red" if check.get("warn") else "dim")
        lines.append(
            Text.assemble(mark, f" {check['name']:<14}", _clip(check.get("detail") or "", 90))
        )
    if d.get("suggestions"):
        lines.append(Text("Try:", style="bold"))
        lines.extend(Text(f"  {s}", style="cyan") for s in d["suggestions"])
    return lines


def _post(event: Event):
    from rich.text import Text

    d = event.data
    stamp = (event.timestamp or "")[11:19]
    lines = [Text.assemble((stamp + "  ", "dim"), _clip(d.get("text") or "", 150))]
    extras = [" ".join(d.get("tags") or []), d.get("url") or ""]
    lines.append(_dim("          " + "  ·  ".join(x for x in extras if x)))
    return lines


def _count(event: Event):
    from rich.text import Text

    d = event.data
    window = f"{str(d.get('window_start', ''))[11:16]}–{str(d.get('window_end', ''))[11:16]}"
    if d.get("complete") is False:
        window += " (partial)"
    return [
        Text.assemble(
            (f"{d.get('count', 0):>6}", "bold cyan"),
            "  ",
            str(d.get("value")),
            ("   " + window, "dim"),
        )
    ]


def _trend(event: Event):
    from rich.text import Text

    d = event.data
    change = "new" if not d.get("baseline") else f"+{d.get('change_pct', 0):.0f}%"
    return [
        Text.assemble(
            (f"↑ {change:>6}", "bold green"),
            "  ",
            (str(d.get("value")), "bold"),
            (
                f"   {d.get('count')} now, usually {str(d.get('baseline')).removesuffix('.0')}",
                "dim",
            ),
        )
    ]


def _record(event: Event):
    from rich.text import Text

    flat = flatten(event.data)
    lines = [Text(event.label, style="bold")] if event.label != event.id else []
    for key, value in list(flat.items())[:12]:
        lines.append(Text.assemble((f"{key}: ", "dim"), _clip(value, 110)))
    if len(flat) > 12:
        lines.append(_dim(f"… {len(flat) - 12} more fields"))
    if not flat:
        lines.append(_dim("(empty)"))
    return lines


_RENDERERS: dict[str, Callable[[Event], list[Any]]] = {
    "document": _document,
    "product": _product,
    "entry": _entry,
    "element": _element,
    "link": _link,
    "change": _change,
    "error": _error,
    "inspection": _inspection,
    "post": _post,
    "count": _count,
    "trend": _trend,
}
