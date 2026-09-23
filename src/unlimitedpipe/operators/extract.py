from __future__ import annotations

import re
from dataclasses import dataclass

from unlimitedpipe.component import Operator, arg, opt
from unlimitedpipe.event import Event
from unlimitedpipe.fields import MISSING, iter_strings, resolve, set_path, split_path

# A small English stoplist: enough to keep "the" and "with" out of word counts.
STOPWORDS = frozenset(
    """a about after again against all also am an and any are as at be because been before
    being between both but by can could did do does doing down during each few for from
    further had has have having he her here hers him his how i if in into is it its itself
    just me more most my new no nor not now of off on once only or other our ours out over
    own same she should so some such than that the their theirs them then there these they
    this those through to too under until up very was we were what when where which while who
    whom why will with would you your yours get got like make made one two use using used via
    show hn ask says said us ok vs etc it's don't i'm you're let's way""".split()  # noqa: SIM905
)


@dataclass(frozen=True)
class Preset:
    pattern: str
    case: str  # "lower", "upper" or "keep"
    help: str


PRESETS = {
    "hashtags": Preset(r"(?<![\w#])#([A-Za-z_]\w{1,49})", "lower", "#tags, lowercased"),
    "cashtags": Preset(r"(?<![\w$])\$([A-Za-z]{1,6})(?![\w])", "upper", "$TICKERS, uppercased"),
    "domains": Preset(r"https?://(?:www\.)?([^/\s:?#]+)", "lower", "web domains in links"),
    "words": Preset(r"(?<![\w'])([A-Za-z][A-Za-z'+-]*[A-Za-z+])", "lower", "words, no stopwords"),
}
PREFIX = {"hashtags": "#", "cashtags": "$"}
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


class Extract(Operator):
    """Find every match of a pattern in the text and store the matches as a list.

    Presets: hashtags (#tags), cashtags ($TICKERS), domains (from links), words (minus common
    stopwords); anything else is a regular expression, whose first group (or whole match) is
    kept. Combine with `count --by` to see what is being talked about. Mentions of people are
    deliberately not a preset.
    """

    name = "extract"
    examples = (
        "unlimited rss https://hnrss.org/frontpage | unlimited extract words -f title",
        "unlimited extract cashtags --into tickers",
        r"unlimited extract 'CVE-\d{4}-\d+' --into cves",
    )

    what: str = arg("hashtags, cashtags, domains, words, or a regular expression")
    field: list[str] = opt(
        "Field to search (repeatable; default: title, summary, text)",
        short="-f",
        metavar="PATH",
        default_factory=list,
    )
    into: str | None = opt("Field for the list of matches (default: the preset name)", default=None)
    keep_case: bool = opt("Do not change the case of matches", default=False)

    def __post_init__(self) -> None:
        preset = PRESETS.get(self.what)
        pattern = preset.pattern if preset else self.what
        try:
            self._regex = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"invalid regular expression {self.what!r}: {exc}") from None
        self._case = "keep" if self.keep_case or preset is None else preset.case
        self._prefix = PREFIX.get(self.what, "")
        self._words = self.what == "words"
        self._strip_urls = preset is not None and self.what != "domains"
        self._into = split_path(self.into or (self.what if preset else "matches"))
        self._fields = [split_path(p) for p in (self.field or ["title", "summary", "text"])]

    def _normalize(self, match: re.Match[str]) -> str:
        value = match.group(1) if self._regex.groups else match.group(0)
        if self._case == "lower":
            value = value.lower()
        elif self._case == "upper":
            value = value.upper()
        return self._prefix + value

    def process(self, event: Event) -> Event:
        found: dict[str, None] = {}
        for parts in self._fields:
            value = resolve(event, parts)
            if value is MISSING:
                continue
            for text in iter_strings(value):
                if self._strip_urls:
                    text = _URL.sub(" ", text)
                for match in self._regex.finditer(text):
                    item = self._normalize(match)
                    if self._words and item in STOPWORDS:
                        continue
                    found[item] = None
        set_path(event.data, self._into, list(found))
        return event
