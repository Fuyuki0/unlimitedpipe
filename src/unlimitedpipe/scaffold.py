"""`unlimited new URL`: inspect a page and write a pipeline that watches it the reliable way."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import yaml

from unlimitedpipe.context import Context
from unlimitedpipe.errors import UsageError


@dataclass
class Scaffold:
    name: str
    yaml: str
    description: str  # one line: what the pipeline watches and how


def pipeline_name(url: str) -> str:
    """``https://www.store.com/products/shoe`` -> ``store-com-products-shoe``."""
    parts = urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.")
    slug = re.sub(r"[^a-z0-9]+", "-", f"{host}{parts.path}".lower()).strip("-")
    return slug[:60].rstrip("-") or "watch"


def _quote(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)  # a JSON string is a valid YAML scalar


def _home(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/"


def _outputs(name: str, title: str, link: str) -> str:
    return (
        "outputs:\n"
        "  - type: feed           # subscribe to this file in any feed reader\n"
        f"    path: {name}.xml\n"
        f"    title: {_quote(title)}\n"
        f"    link: {_quote(link)}\n"
        "  - type: pretty         # also show changes in the terminal\n"
    )


def render(url: str, report: dict[str, Any]) -> Scaffold:
    """Pipeline YAML for a URL, from an `inspect` report."""
    kind = report.get("kind")
    name = pipeline_name(url)
    title = report.get("title") or urlsplit(url).netloc
    header = f"# Created by `unlimited new {url}`.\n"

    if kind == "blocked":
        github = re.match(r"https?://(?:www\.)?github\.com/([\w.-]+/[\w.-]+)", url)
        hint = (
            f"use GitHub's API instead: unlimited github releases {github.group(1)}"
            if github
            else "look for an official API or feed; UnlimitedPipe does not fetch disallowed pages"
        )
        raise UsageError(
            f"{url}: robots.txt asks automated clients not to fetch this page", hint=hint
        )
    if kind == "json":
        body = (
            f"{header}# The URL returns JSON: each item becomes a record.\n"
            f"name: {name}\n"
            f"description: {_quote('Changes to ' + url)}\n\n"
            "sources:\n"
            "  - type: web\n"
            f"    url: {url}\n\n"
            "operators:\n"
            "  - type: diff           # the first run saves a baseline; later runs emit changes\n"
            "    # key: id            # match items by a field so edits show as modifications\n\n"
            "outputs:\n"
            "  - type: jsonl\n"
            f"    path: {name}.jsonl\n"
            "    append: true\n"
            "  - type: pretty\n"
        )
        return Scaffold(name, body, "changes to a JSON API")

    feed_url = url if kind == "feed" else (report.get("feeds") or [None])[0]
    method = report.get("product_method")
    if method:
        body = (
            f"{header}# Read from the page's product data ({method}).\n"
            f"name: {name}\n"
            f"description: {_quote('Price and stock of ' + title)}\n\n"
            "sources:\n"
            "  - type: web\n"
            f"    url: {url}\n\n"
            "operators:\n"
            "  - type: diff           # the first run saves a baseline; later runs emit changes\n"
            "    # only: [modified]   # ignore variants appearing or disappearing\n\n"
            + _outputs(name, f"Price and stock: {title}", url)
        )
        return Scaffold(name, body, f"price and stock changes (product data via {method})")

    if feed_url:
        feed_name = pipeline_name(feed_url) if kind == "feed" else name
        body = (
            f"{header}# New items from the feed {feed_url}.\n"
            f"name: {feed_name}\n"
            f"description: {_quote('New items from ' + title)}\n\n"
            "sources:\n"
            "  - type: rss\n"
            f"    url: {feed_url}\n\n"
            "operators:\n"
            "  # - type: grep         # keep only items that mention these words\n"
            "  #   patterns: [AI, security]\n"
            "  - type: diff\n"
            "    only: [added]\n"
            "    emit_initial: true   # the first run fills the feed with current items\n\n"
            + _outputs(feed_name, f"New: {title}", url if kind != "feed" else _home(url))
        )
        return Scaffold(feed_name, body, "new items from the site's feed")

    warning = ""
    if report.get("js_required"):
        warning = (
            "# Warning: this page renders with JavaScript, so there is little to read without a\n"
            "# browser: uncomment `browser: true` below, or look for an API or a feed.\n"
        )
    body = (
        f"{header}{warning}"
        f"name: {name}\n"
        f"description: {_quote('Changes to ' + title)}\n\n"
        "sources:\n"
        "  - type: web\n"
        f"    url: {url}\n"
        '    # browser: true   # render JavaScript: pip install "unlimitedpipe[browser]"\n'
        "    # To watch specific parts instead of the whole page text, name them:\n"
        "    # each: .plan                     # one record per matching element\n"
        "    # field: [name=h2, price=.price]  # NAME=CSS, or NAME=CSS@attribute\n\n"
        "operators:\n"
        "  - type: diff           # the first run saves a baseline; later runs emit changes\n"
        "    ignore: [word_count]\n\n" + _outputs(name, f"Changes: {title}", url)
    )
    return Scaffold(name, body, "changes to the page's text and headings")


async def scaffold(url: str, ctx: Context) -> Scaffold:
    from unlimitedpipe.config import parse_pipeline
    from unlimitedpipe.sources.inspect import Inspect

    try:
        event = await Inspect().inspect(url, ctx)
    finally:
        await ctx.aclose()
    result = render(event.source_url or url, event.data)
    parse_pipeline(yaml.safe_load(result.yaml), source_name=f"{result.name}.yml", text=result.yaml)
    return result
