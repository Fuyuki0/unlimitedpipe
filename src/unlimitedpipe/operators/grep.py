from __future__ import annotations

import re

from unlimitedpipe.component import Operator, arg, opt
from unlimitedpipe.event import Event
from unlimitedpipe.fields import MISSING, iter_strings, resolve, split_path

_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


class Grep(Operator):
    """Keep events whose text matches any of the patterns.

    Matches whole words and ignores case by default, so ``grep AI`` finds "AI" and "ai" but not
    "said". Web addresses are skipped when looking for words, so ``AI`` does not match
    ``example.ai/post``; a pattern containing ``.`` or ``/`` (like ``github.com``) does search
    them. Searches every text value in data unless ``--field`` is given.
    """

    name = "grep"
    patterns: list[str] = arg("Words or phrases to look for (any one matches)")
    field: list[str] = opt("Only search this field (repeatable)", short="-f", metavar="PATH")
    regex: bool = opt("Treat patterns as regular expressions", short="-E", default=False)
    substring: bool = opt("Match inside words too", default=False)
    case_sensitive: bool = opt("Respect case", short="-s", default=False)
    invert: bool = opt("Keep events that do NOT match", short="-v", default=False)

    def __post_init__(self) -> None:
        if not self.patterns:
            raise ValueError("grep needs at least one pattern")
        parts = []
        for pattern in self.patterns:
            body = pattern if self.regex else re.escape(pattern)
            if not self.regex and not self.substring:
                body = rf"(?<!\w){body}(?!\w)"
            parts.append(f"(?:{body})")
        flags = 0 if self.case_sensitive else re.IGNORECASE
        try:
            self._pattern = re.compile("|".join(parts), flags)
        except re.error as exc:
            raise ValueError(f"invalid regular expression: {exc}") from None
        self._fields = [split_path(path) for path in self.field]
        self._skip_urls = not self.regex and not any(c in p for p in self.patterns for c in "./")

    def _texts(self, event: Event):
        if not self._fields:
            yield from iter_strings(event.data)
            return
        for parts in self._fields:
            value = resolve(event, parts)
            if value is not MISSING:
                yield from iter_strings(value)

    def process(self, event: Event) -> Event | None:
        texts = self._texts(event)
        if self._skip_urls:
            texts = (_URL.sub(" ", text) for text in texts)
        matched = any(self._pattern.search(text) for text in texts)
        return event if matched != self.invert else None
