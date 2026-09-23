"""Change detection: compare each item with what the previous run saw."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from unlimitedpipe.component import Operator, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import ConfigError
from unlimitedpipe.event import Event, content_hash, utcnow
from unlimitedpipe.fields import MISSING, delete_path, resolve, split_path
from unlimitedpipe.state import state_path, write_json_atomic

STATE_VERSION = 1
ChangeKind = Literal["added", "removed", "modified"]


def compare(old: Any, new: Any, path: str = "") -> list[dict[str, Any]]:
    """Field-level differences between two JSON values, as dotted paths."""
    if isinstance(old, dict) and isinstance(new, dict):
        changes: list[dict[str, Any]] = []
        for key in [*old, *(k for k in new if k not in old)]:
            child = f"{path}.{key}" if path else str(key)
            changes.extend(compare(old.get(key), new.get(key), child))
        return changes
    if (
        isinstance(old, list)
        and isinstance(new, list)
        and len(old) == len(new)
        and all(isinstance(item, dict) for item in [*old, *new])
    ):
        changes = []
        for index, (a, b) in enumerate(zip(old, new, strict=True)):
            changes.extend(compare(a, b, f"{path}.{index}" if path else str(index)))
        return changes
    if old != new:
        return [{"path": path or "value", "old": old, "new": new}]
    return []


def _short(value: Any) -> str | None:
    """A compact rendering for summaries, or None when the value is too long to show."""
    if value is None:
        return "none"
    if isinstance(value, (dict, list)):
        return None
    text = str(value)
    if len(text) > 60 or "\n" in text:
        return None
    return text


def summarize(kind: str, label: str, fields: list[dict[str, Any]]) -> str:
    if kind == "added":
        return f"added: {label}"
    if kind == "removed":
        return f"removed: {label}"
    parts = []
    for change in fields[:4]:
        old, new = _short(change["old"]), _short(change["new"])
        if old is None or new is None:
            parts.append(f"{change['path']} changed")
        else:
            parts.append(f"{change['path']}: {old} → {new}")
    if len(fields) > 4:
        parts.append(f"and {len(fields) - 4} more")
    return "; ".join(parts)


def default_namespace(event: Event) -> str:
    basis = re.sub(r"^https?://", "", (event.source_url or "").lower())
    slug = re.sub(r"[^a-z0-9]+", "-", basis).strip("-")[:60] or "items"
    return f"{event.source}-{slug}-{content_hash(event.source, event.source_url)[:8]}"


class DiffState:
    """What the previous run saw, per item key. Stored as one small JSON file."""

    def __init__(self, path: Path, items: dict[str, dict[str, Any]], existed: bool) -> None:
        self.path = path
        self.items = items
        self.existed = existed
        self._loaded = self._fingerprint() if existed else None

    def _fingerprint(self) -> str:
        return json.dumps(self.items, sort_keys=True, ensure_ascii=False, default=str)

    @classmethod
    def load(cls, path: Path) -> DiffState:
        if not path.exists():
            return cls(path, {}, existed=False)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            items = raw["items"]
            if raw.get("version") != STATE_VERSION or not isinstance(items, dict):
                raise ValueError("unknown format")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ConfigError(
                f"cannot read diff state {path}: {exc}",
                hint="start a new baseline with --reset",
            ) from None
        return cls(path, items, existed=True)

    def save(self) -> None:
        """Write the state, unless nothing changed: an idle run leaves the file untouched, so a
        state kept in Git does not produce empty commits."""
        if self._loaded is not None and self._fingerprint() == self._loaded:
            return
        payload = {"version": STATE_VERSION, "updated_at": utcnow(), "items": self.items}
        write_json_atomic(self.path, payload)


class Diff(Operator):
    """Emit only what changed since the last run: added, removed or modified items.

    The first run saves a baseline and emits nothing. Later runs emit ``change`` events with
    field-level old/new values. Items are matched by their key (product URL + SKU, feed item id)
    or by ``--key FIELD``. An item only counts as removed when its page or feed was fetched in
    this run, so a network failure never looks like everything disappeared.
    """

    name = "diff"
    key: str | None = opt(
        "Field identifying an item, e.g. `name` (default: the event key)",
        default=None,
        metavar="PATH",
    )
    namespace: str | None = opt(
        "Name for this watch's state (default: derived from the source URL)",
        short="-n",
        default=None,
    )
    state: str | None = opt("State file path (overrides --namespace)", default=None, metavar="FILE")
    reset: bool = opt("Forget previous state and create a new baseline", default=False)
    ignore: list[str] = opt("Field to ignore when comparing (repeatable)", metavar="PATH")
    only: list[ChangeKind] = opt("Only emit these changes (repeatable): added, removed, modified")
    emit_initial: bool = opt("On the first run, emit every item as added", default=False)

    def __post_init__(self) -> None:
        self._key_path = split_path(self.key) if self.key else None
        self._ignore = [split_path(path) for path in self.ignore]
        self._wanted: set[str] = set(self.only) or {"added", "removed", "modified"}

    def _state_path(self, event: Event, ctx: Context) -> Path:
        namespace = self.namespace
        if namespace is None and not self.state:
            namespace = default_namespace(event)
            if event.source_url is None:
                ctx.warn("diff: events have no source URL; name this watch with --namespace")
        return state_path(ctx, "diff", namespace or "", self.state)

    def _item_key(self, event: Event, data: dict[str, Any]) -> str:
        if self._key_path is not None:
            value = resolve(event, self._key_path)
            if value is not MISSING and value is not None:
                return f"{event.source_url}#{value}" if event.source_url else str(value)
        return event.key or "#" + content_hash(data)[:20]

    def _comparable(self, data: dict[str, Any]) -> dict[str, Any]:
        copied = json.loads(json.dumps(data, default=str))
        for parts in self._ignore:
            delete_path(copied, parts)
        return copied

    def _change(
        self,
        kind: str,
        key: str,
        label: str,
        base: Event | None,
        entry: dict[str, Any],
        fields: list[dict[str, Any]] | None = None,
    ) -> Event:
        data: dict[str, Any] = {
            "change": kind,
            "label": label,
            "item_type": entry.get("type"),
            "summary": summarize(kind, label, fields or []),
        }
        if fields is not None:
            data["fields"] = fields
        if kind == "removed":
            data["before"] = entry["data"]
        else:
            data["after"] = entry["data"]
        return Event(
            source=base.source if base else entry.get("source", "diff"),
            type="change",
            source_url=base.source_url if base else entry.get("source_url"),
            key=key,
            data=data,
            metadata=dict(base.metadata) if base else {"seen": entry.get("seen")},
            provenance=list(base.provenance) if base else [],
        )

    async def apply(self, events, ctx):
        store: DiffState | None = None
        baseline = False
        seen: set[str] = set()
        fetched_urls: set[str | None] = set()
        counts: Counter[str] = Counter()
        completed = False
        try:
            async for event in events:
                if event.type == "error":
                    yield event
                    continue
                if store is None:
                    path = self._state_path(event, ctx)
                    if self.reset and path.exists():
                        path.unlink()
                    store = DiffState.load(path)
                    baseline = not store.existed
                data = self._comparable(event.data)
                key = self._item_key(event, data)
                if key in seen:
                    continue
                seen.add(key)
                fetched_urls.add(event.source_url)
                entry = {
                    "hash": content_hash(data),
                    "data": data,
                    "label": event.label,
                    "type": event.type,
                    "source": event.source,
                    "source_url": event.source_url,
                    "seen": event.observed_at,
                }
                old = store.items.get(key)
                if old is None or old.get("hash") != entry["hash"]:
                    store.items[key] = entry  # "seen": when this version was first seen
                if baseline:
                    counts["baseline"] += 1
                    if self.emit_initial and "added" in self._wanted:
                        yield self._change("added", key, event.label, event, entry)
                elif old is None:
                    counts["added"] += 1
                    if "added" in self._wanted:
                        yield self._change("added", key, event.label, event, entry)
                elif old.get("hash") != entry["hash"]:
                    fields = compare(old.get("data"), data)
                    counts["modified"] += 1
                    if "modified" in self._wanted:
                        yield self._change("modified", key, event.label, event, entry, fields)
            if store is not None and not baseline:
                for key, entry in list(store.items.items()):
                    if key in seen or entry.get("source_url") not in fetched_urls:
                        continue
                    del store.items[key]
                    counts["removed"] += 1
                    if "removed" in self._wanted:
                        yield self._change("removed", key, entry.get("label") or key, None, entry)
            completed = True
        finally:
            if store is not None:
                store.save()
            if completed:
                self._report(ctx, store, baseline, counts)

    def _report(
        self, ctx: Context, store: DiffState | None, baseline: bool, counts: Counter[str]
    ) -> None:
        if store is None:
            ctx.notice("diff: no input events; state unchanged")
        elif baseline and self.emit_initial:
            ctx.notice(f"diff: first run, {counts['baseline']} item(s) emitted as added")
        elif baseline:
            ctx.notice(
                f"diff: baseline created for {counts['baseline']} item(s) in {store.path}. "
                "Run again to see changes."
            )
        else:
            changed = [f"{counts[k]} {k}" for k in ("modified", "added", "removed") if counts[k]]
            ctx.notice("diff: " + (", ".join(changed) if changed else "no changes"))
