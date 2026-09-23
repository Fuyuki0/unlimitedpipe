"""Reading HTML pages: title, metadata, headings, visible text, links, tables, selectors."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import urldefrag, urljoin

from bs4 import BeautifulSoup, Tag
from bs4.element import Comment, Doctype, NavigableString, ProcessingInstruction

SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "canvas", "iframe", "head", "object"}
BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "dd",
    "details",
    "div",
    "dl",
    "dt",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "summary",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}
FEED_TYPES = {
    "application/rss+xml",
    "application/atom+xml",
    "application/feed+json",
    "application/json",
}


def parse(content: bytes, encoding: str | None = None) -> BeautifulSoup:
    return BeautifulSoup(content, "lxml", from_encoding=encoding)


def _clean(text: str) -> str:
    return " ".join(text.split())


def _hidden(tag: Tag) -> bool:
    if tag.has_attr("hidden") or tag.get("aria-hidden") == "true":
        return True
    style = tag.get("style")
    return isinstance(style, str) and re.search(r"display\s*:\s*none", style, re.I) is not None


def _text_parts(node: Tag) -> Iterator[str]:
    for child in node.children:
        if isinstance(child, (Comment, Doctype, ProcessingInstruction)):
            continue
        if isinstance(child, NavigableString):
            yield str(child)
        elif isinstance(child, Tag):
            if child.name in SKIP_TAGS or _hidden(child):
                continue
            block = child.name in BLOCK_TAGS
            if block:
                yield "\n"
            yield from _text_parts(child)
            if block:
                yield "\n"


def visible_text(node: Tag) -> str:
    """Text a person would see, one block per line. Scripts, styles and hidden nodes skipped."""
    lines = (_clean(line) for line in "".join(_text_parts(node)).split("\n"))
    return "\n".join(line for line in lines if line)


def element_text(node: Tag) -> str:
    return _clean(" ".join(_text_parts(node)))


def title(soup: BeautifulSoup, meta: dict[str, str]) -> str | None:
    if soup.title and soup.title.string and soup.title.string.strip():
        return _clean(soup.title.string)
    heading = soup.find("h1")
    return (
        meta.get("og:title")
        or (element_text(heading) if isinstance(heading, Tag) else None)
        or None
    )


def canonical(soup: BeautifulSoup, base_url: str) -> str | None:
    link = soup.find("link", rel=lambda v: v is not None and "canonical" in v)
    href = link.get("href") if isinstance(link, Tag) else None
    return urljoin(base_url, href) if isinstance(href, str) and href.strip() else None


def lang(soup: BeautifulSoup) -> str | None:
    node = soup.find("html")
    value = node.get("lang") if isinstance(node, Tag) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def headings(soup: BeautifulSoup) -> list[dict[str, Any]]:
    found = []
    for node in soup.find_all(re.compile(r"^h[1-6]$")):
        if isinstance(node, Tag) and not _hidden(node):
            text = element_text(node)
            if text:
                found.append({"level": int(node.name[1]), "text": text})
    return found


def links(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
    """Unique absolute http(s) links with their text, in page order."""
    seen: dict[str, dict[str, str]] = {}
    for node in soup.find_all("a", href=True):
        href = node.get("href")
        if not isinstance(href, str):
            continue
        url = urldefrag(urljoin(base_url, href.strip()))[0]
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen[url] = {"url": url, "text": element_text(node)}
        rel = node.get("rel")
        if rel:
            seen[url]["rel"] = " ".join(rel) if isinstance(rel, list) else str(rel)
    return list(seen.values())


def feeds(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Feeds the page advertises with ``<link rel="alternate">``."""
    found: dict[str, None] = {}
    for node in soup.find_all("link", href=True):
        rel = node.get("rel") or []
        kind = str(node.get("type") or "").lower()
        if (
            "alternate" in rel
            and kind in FEED_TYPES
            and (kind != "application/json" or "feed" in str(node.get("href")))
        ):
            found[urljoin(base_url, str(node["href"]))] = None
    return list(found)


def tables(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Tables as lists of rows keyed by header text (or ``col1``, ``col2``... without headers)."""
    result = []
    for table in soup.find_all("table"):
        if not isinstance(table, Tag) or table.find_parent("table") is not None:
            continue
        rows = [r for r in table.find_all("tr") if r.find_parent("table") is table]
        if not rows:
            continue
        header_cells = rows[0].find_all(["th", "td"])
        has_header = bool(rows[0].find_all("th")) or table.find("thead") is not None
        headers = (
            [element_text(c) or f"col{i + 1}" for i, c in enumerate(header_cells)]
            if has_header
            else []
        )
        body = rows[1:] if has_header else rows
        records = []
        for row in body:
            cells = [element_text(c) for c in row.find_all(["td", "th"])]
            if not any(cells):
                continue
            names = headers + [f"col{i + 1}" for i in range(len(headers), len(cells))]
            records.append(dict(zip(names, cells, strict=False)))
        caption = table.find("caption")
        result.append(
            {
                "caption": element_text(caption) if isinstance(caption, Tag) else None,
                "rows": records,
            }
        )
    return result


def select(soup: BeautifulSoup | Tag, selector: str) -> list[Tag]:
    from soupsieve import SelectorSyntaxError

    try:
        return [node for node in soup.select(selector) if isinstance(node, Tag)]
    except SelectorSyntaxError as exc:
        raise ValueError(f"invalid CSS selector {selector!r}: {exc}") from None


def element_value(node: Tag, attribute: str | None, base_url: str) -> str | None:
    """Text of an element, or one of its attributes (URLs made absolute)."""
    if attribute is None:
        return element_text(node) or None
    value = node.get(attribute)
    if isinstance(value, list):
        value = " ".join(value)
    if value is None:
        return None
    if attribute in ("href", "src", "action"):
        return urljoin(base_url, value)
    return value.strip()


def element_data(node: Tag, base_url: str) -> dict[str, Any]:
    data: dict[str, Any] = {"text": element_text(node), "tag": node.name}
    attrs = {k: " ".join(v) if isinstance(v, list) else v for k, v in node.attrs.items()}
    if attrs:
        data["attrs"] = attrs
    href = node.get("href")
    if isinstance(href, str):
        data["url"] = urljoin(base_url, href)
    return data


def looks_js_rendered(soup: BeautifulSoup, text: str) -> bool:
    """Heuristic: almost no visible text, but scripts or an empty app root."""
    words = len(text.split())
    if words >= 80:
        return False
    scripts = len(soup.find_all("script"))
    root = soup.find(id=re.compile(r"^(root|app|__next|__nuxt|svelte)$"))
    empty_root = isinstance(root, Tag) and not element_text(root)
    return empty_root or (words < 30 and scripts >= 3)
