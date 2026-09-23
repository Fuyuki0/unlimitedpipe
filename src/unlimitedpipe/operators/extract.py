from __future__ import annotations

import re
from dataclasses import dataclass

from unlimitedpipe.component import Operator, arg, opt
from unlimitedpipe.event import Event
from unlimitedpipe.fields import MISSING, iter_strings, resolve, set_path, split_path

# Common English words that say nothing about a topic, so word counts show subjects.
STOPWORDS = frozenset(
    """a about above after again against ago all almost along already also although always am
    among an and another any anyone anything are around as ask asked at away back bad be
    became because become been before being below best better between big both but by came
    can can't cannot come could couldn't day days did didn't do does doesn't doing don't
    done down during each either else etc even ever every everyone everything few find first
    for found from full further get gets getting give go goes going gone good got great had
    has hasn't have haven't having he he's her here hers herself him himself his hn how i
    i'd i'll i'm i've if in into is isn't it it's its itself just keep know last least less
    let let's like little look lot lots made make makes many may maybe me might more most
    much must my myself need needs never new next no nor not nothing now of off often oh ok
    okay old on once one only or other others our ours out over own part people put rather
    really right said same saw say says see seem seems shall she she's should show since so
    some someone something still such sure take tell than thank thanks that that's the their
    theirs them then there there's these they they're thing things think this those though
    thought through time to today too took two under until up upon us use used using very
    via vs want wants was wasn't way we we're well went were weren't what what's when where
    whether which while who whom whose why will with within without won't would wouldn't
    yeah year years yes yet you you'd you'll you're you've your yours yourself""".split()  # noqa: SIM905
) | frozenset(  # dates in bot posts ("Wed, Sep 23") are not topics either
    """jan feb mar apr jun jul aug sep sept oct nov dec
    mon tue tues wed thu thurs fri sat sun pm""".split()  # noqa: SIM905
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
# Links, bare domains (example.com/page) and @handles are not words; people are not topics.
_NOT_WORDS = re.compile(
    r"(?:https?://|www\.)\S+|@[\w.-]+|\b[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}(?:/\S*)?", re.IGNORECASE
)


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
                    text = _NOT_WORDS.sub(" ", text)
                for match in self._regex.finditer(text):
                    item = self._normalize(match)
                    if self._words and item in STOPWORDS:
                        continue
                    found[item] = None
        set_path(event.data, self._into, list(found))
        return event
