"""Names and titles written the way people read them.

EDGAR, the FDA and Congress's lobbying records list companies in capitals ("HERTZ GLOBAL
HOLDINGS, INC"); a feed reads better with "Hertz Global Holdings, Inc", while initials and
acronyms stay as they are ("BNSF Railway Company", "AT&T Inc.", "IBM").
"""

from __future__ import annotations

import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Short words that are words, not initials, in a company's name.
_SHORT_WORDS = frozenset(
    {
        "INC",
        "CO",
        "LTD",
        "THE",
        "AND",
        "OF",
        "FOR",
        "NEW",
        "BAY",
        "ONE",
        "TWO",
        "SUN",
        "OIL",
        "GAS",
        "CAR",
        "AIR",
        "SEA",
        "BIO",
        "BOX",
        "LAB",
        "LAW",
        "BAR",
        "NET",
        "WAY",
        "TOP",
        "BIG",
        "RED",
        "ALL",
        "ART",
        "AGE",
        "FUN",
        "PAY",
        "WEB",
        "LIFE",
        "CORP",
        "BANK",
    }
)
# Acronyms that have vowels, so the rule for initials would miss them.
_ACRONYMS = frozenset(
    {"REIT", "AMEX", "NASDAQ", "NYSE", "ETF", "ETN", "ADR", "ESG", "SPAC", "PIMCO", "TIAA", "USAA"}
)
# Names whose owners write them with capitals inside (common in SEC filings)
_SPELLED = {
    "JPMORGAN": "JPMorgan",
    "BLACKROCK": "BlackRock",
    "SOFTBANK": "SoftBank",
    "PAYPAL": "PayPal",
    "FEDEX": "FedEx",
    "ISHARES": "iShares",
    "OPENAI": "OpenAI",
    "LINKEDIN": "LinkedIn",
    "YOUTUBE": "YouTube",
    "GITHUB": "GitHub",
    "MASTERCARD": "Mastercard",
}
_SMALL = frozenset({"of", "and", "the", "for", "in", "on", "to", "a", "an", "at", "by"})
_VOWELS = frozenset("AEIOUY")
_BREAK = re.compile(r"<(br|p|div|li)\b[^>]*>", re.IGNORECASE)
_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9]*(\s[^<>]*)?/?>")
_STATE = re.compile(r"(\s*/[A-Z]{2,5}/?)+\s*$")  # EDGAR's "APPLE INC /CA/"
# Query parameters that only say where a click came from.
_TRACKING = re.compile(
    r"^(utm_[a-z]+|fbclid|gclid|dclid|mc_cid|mc_eid|_hsenc|_hsmi|mkt_tok)$", re.I
)


def _word(word: str) -> str:
    bare = word.strip(".,;:()&'\"")
    if bare in _SPELLED:
        return word.replace(bare, _SPELLED[bare])
    if bare in _SHORT_WORDS and not any(c.islower() for c in word):
        return word[0] + word[1:].lower()  # LTD -> Ltd, CO -> Co
    if (
        not bare
        or bare in _ACRONYMS
        or any(c.islower() for c in word)
        or any(c.isdigit() for c in bare)
        or "&" in bare
        or (len(bare) <= 3 and bare not in _SHORT_WORDS)
        or (len(bare) >= 2 and not (set(bare) & _VOWELS))
    ):
        return word  # initials, acronyms and codes: IBM, BNSF, AT&T, 3M, LLC
    parts = []
    for part in word.split("-"):
        lower = part.lower()
        cased = re.sub(r"[a-z]", lambda m: m.group(0).upper(), lower, count=1)
        if lower.startswith("mc") and len(lower) > 4:
            cased = "Mc" + lower[2:].capitalize()  # MCDONALD -> McDonald
        parts.append(cased)
    return "-".join(parts)


def readable_name(text: str | None) -> str | None:
    """A name in capitals as people write it; any other name as it is."""
    if not text:
        return text
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 4 or sum(c.isupper() for c in letters) < 0.8 * len(letters):
        return text
    words = [_word(word) for word in _STATE.sub("", text).split()]
    return " ".join(w.lower() if n and w.lower() in _SMALL else w for n, w in enumerate(words))


def clean_title(text: str | None) -> str | None:
    """A title as a reader should see it: entities decoded, tags and extra spaces gone."""
    if text is None:
        return None
    text = _TAG.sub("", _BREAK.sub(" ", html.unescape(text)))
    return " ".join(text.split()) or None


def clean_link(url: str | None) -> str | None:
    """A link without the parameters that only track where a click came from."""
    if not url or "?" not in url:
        return url
    parts = urlsplit(url)
    kept = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)
    ]
    return urlunsplit(parts._replace(query=urlencode(kept, safe=":/,@")))
