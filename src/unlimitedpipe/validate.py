"""`unlimited validate`: check a feed catalog against the Feed Catalog Protocol (docs/protocol.md).

Errors break the protocol (a reader could fail on them); warnings are things a good catalog
should fix. With `deep`, every feed file and archive month is read as well.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError

NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
STATUSES = {"ok", "partial", "failing"}


@dataclass
class Finding:
    level: str  # "error" or "warning"
    where: str
    message: str


class Report:
    def __init__(self) -> None:
        self.findings: list[Finding] = []
        self.checked: list[str] = []

    def error(self, where: str, message: str) -> None:
        self.findings.append(Finding("error", where, message))

    def warn(self, where: str, message: str) -> None:
        self.findings.append(Finding("warning", where, message))

    @property
    def errors(self) -> int:
        return sum(f.level == "error" for f in self.findings)


def _date_ok(value: Any) -> bool:
    from unlimitedpipe.event import parse_time

    return value is None or (isinstance(value, str) and parse_time(value) is not None)


QUIET_DAYS = 14


def _quiet(latest: Any) -> str | None:
    """A warning for a feed that runs fine but has never had an item, or none for weeks: its
    source may have moved, or a filter may drop everything."""
    from datetime import UTC, datetime

    from unlimitedpipe.event import parse_time

    if not latest:
        return "has never had an item"
    when = parse_time(latest) if isinstance(latest, str) else None
    if when is None:
        return None
    days = (datetime.now(UTC) - when).days
    return f"no new item for {days} days" if days >= QUIET_DAYS else None


def _check_item(report: Report, where: str, item: Any, feeds: set[str]) -> None:
    if not isinstance(item, dict):
        return report.error(where, "is not an object")
    if item.get("feed") not in feeds:
        report.error(where, f"names a feed the catalog does not list: {item.get('feed')!r}")
    if not isinstance(item.get("title"), str) or not item["title"].strip():
        report.error(where, "has no title")
    link = item.get("link")
    if not link:
        report.warn(where, "has no link to its source")
    elif not (isinstance(link, str) and re.match(r"^https?://", link)):
        report.error(where, f"link is not an absolute web address: {link!r}")
    if not _date_ok(item.get("date")):
        report.error(where, f"date is not ISO 8601: {item.get('date')!r}")
    if item.get("summary") is not None and not isinstance(item["summary"], str):
        report.error(where, "summary is neither text nor null")


async def validate(ctx: Context, catalog: str | None, *, deep: bool = False) -> Report:
    from unlimitedpipe.archive import item_key
    from unlimitedpipe.sources.search import catalog_url, join, read

    report = Report()
    url = catalog_url(catalog)
    try:
        document = json.loads(await read(ctx, url))
    except FetchError as exc:
        report.error("feeds.json", exc.message)
        return report
    except ValueError as exc:
        report.error("feeds.json", f"is not JSON ({exc})")
        return report
    report.checked.append(url)
    if not isinstance(document, dict):
        report.error("feeds.json", "is not a JSON object")
        return report
    schema = str(document.get("schema", ""))
    if not schema.startswith("unlimitedpipe.catalog/"):
        report.error("feeds.json", f"schema is {schema!r}, not unlimitedpipe.catalog/1")
        return report
    if schema != "unlimitedpipe.catalog/1":
        report.error("feeds.json", f"{schema} is a version this reader does not know")
        return report
    if not document.get("title"):
        report.warn("feeds.json", "has no title")

    feeds = document.get("feeds")
    if not isinstance(feeds, list):
        report.error("feeds.json", "feeds is not a list")
        feeds = []
    names: set[str] = set()
    for n, feed in enumerate(feeds):
        where = f"feeds[{n}]"
        if not isinstance(feed, dict):
            report.error(where, "is not an object")
            continue
        name = feed.get("name")
        where = f"feed {name!r}" if name else where
        if not isinstance(name, str) or not NAME.match(name):
            report.error(where, "name must be lowercase letters, digits and -")
        elif name in names:
            report.error(where, "is listed twice")
        else:
            names.add(name)
        if not feed.get("description"):
            report.warn(where, "has no description of what it follows")
        files = feed.get("files")
        if not isinstance(files, list) or not files:
            report.error(where, "lists no files")
            files = []
        health = feed.get("health")
        if health is not None:
            if not isinstance(health, dict) or health.get("status") not in STATUSES:
                report.error(where, "health status must be ok, partial or failing")
            elif health["status"] != "ok":
                report.warn(where, f"health is {health['status']} since {health.get('since')}")
            elif "latest" in health and (quiet := _quiet(health["latest"])) is not None:
                report.warn(where, quiet)
        if deep:
            for path in files:
                if not isinstance(path, str) or path.startswith(("/", "http:", "https:")):
                    report.error(where, f"file path must be relative: {path!r}")
                    continue
                try:
                    await read(ctx, join(url, path))
                    report.checked.append(path)
                except FetchError as exc:
                    report.error(where, f"{path}: {exc.message}")

    items = document.get("items")
    if not isinstance(items, list):
        report.error("feeds.json", "items is not a list")
        items = []
    seen: set[str] = set()
    dates = []
    for n, item in enumerate(items):
        _check_item(report, f"items[{n}]", item, names)
        if isinstance(item, dict):
            key = item_key(item)
            if key in seen:
                report.warn(
                    f"items[{n}]", f"repeats an item of {item.get('feed')}: {item.get('title')!r}"
                )
            seen.add(key)
            if isinstance(item.get("date"), str):
                dates.append(item["date"])
    if dates != sorted(dates, reverse=True):
        report.warn("feeds.json", "items are not newest first")

    archive = document.get("archive")
    if archive:
        await _check_archive(ctx, report, url, str(archive), names, deep)
    return report


async def _check_archive(ctx, report: Report, url: str, path: str, names: set[str], deep: bool):
    from unlimitedpipe.sources.search import join, read

    index_url = join(url, path)
    try:
        index = json.loads(await read(ctx, index_url))
    except (FetchError, ValueError) as exc:
        report.error("archive", f"{path}: {getattr(exc, 'message', exc)}")
        return
    report.checked.append(path)
    if not isinstance(index, dict) or index.get("schema") != "unlimitedpipe.archive/1":
        report.error("archive", "index schema is not unlimitedpipe.archive/1")
        return
    months = index.get("months")
    if not isinstance(months, list):
        report.error("archive", "months is not a list")
        return
    labels = [m.get("month") for m in months if isinstance(m, dict)]
    good = [m for m in labels if isinstance(m, str) and MONTH.match(m)]
    if len(good) != len(labels):
        report.error("archive", "a month is not YYYY-MM")
    elif good != sorted(good, reverse=True):
        report.warn("archive", "months are not newest first")
    if not deep:
        return
    for month in months:
        if not isinstance(month, dict):
            continue
        where = f"archive {month.get('month')}"
        try:
            content = await read(ctx, join(index_url, str(month.get("file"))))
        except FetchError as exc:
            report.error(where, exc.message)
            continue
        report.checked.append(str(month.get("file")))
        lines = [line for line in content.decode("utf-8", "replace").splitlines() if line.strip()]
        if month.get("items") != len(lines):
            report.warn(where, f"index says {month.get('items')} items, the file has {len(lines)}")
        for n, line in enumerate(lines):
            try:
                item = json.loads(line)
            except ValueError:
                report.error(where, f"line {n + 1} is not JSON")
                continue
            _check_item(report, f"{where} line {n + 1}", item, names | {item.get("feed")})
            if isinstance(item, dict) and not item.get("seen"):
                report.warn(f"{where} line {n + 1}", "has no seen time")
