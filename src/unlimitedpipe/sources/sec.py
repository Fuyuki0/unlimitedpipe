"""The ``sec`` source: public filings from the US Securities and Exchange Commission's EDGAR."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Literal

from unlimitedpipe._version import __version__
from unlimitedpipe.component import Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError, UsageError
from unlimitedpipe.event import Event
from unlimitedpipe.state import state_path, write_json_atomic

LATEST = "https://www.sec.gov/cgi-bin/browse-edgar"
SEARCH = "https://efts.sec.gov/LATEST/search-index"  # EDGAR full-text search
SUBMISSIONS = "https://data.sec.gov/submissions/"
# Reports a company files once it is public: one filed before its S-1 means it was public
# already (a resale or follow-on registration, not an IPO).
PERIODIC = {"10-K", "10-Q", "20-F", "40-F", "10-KT", "10-QT", "10-K405", "N-CSR"}
IPO_FORMS = ("S-1", "F-1")
NOT_IPO_SICS = {"6311"}  # life insurers register annuities on S-1
MOST_HITS = 2000  # search results read per form and period
# Form 4 transaction codes: https://www.sec.gov/edgar/searchedgar/ownershipformcodes.html
ACTIONS = {
    "P": "bought",
    "S": "sold",
    "A": "received as an award",
    "M": "exercised options for",
    "X": "exercised options for",
    "C": "converted into",
    "F": "gave up to pay taxes",
    "G": "gave away",
    "D": "sold back to the company",
    "J": "moved",
}
_ENTITY = re.compile(
    r"\b(LLC|L\.?P\.?|INC|CORP|CO|LTD|FUND|TRUST|CAPITAL|PARTNERS|HOLDINGS|GROUP|BANK|PLC|"
    r"MANAGEMENT|ADVISORS|INVESTMENTS|VENTURES|FOUNDATION|N\.?V\.?|S\.?A\.?|AG|GMBH|"
    r"S\.?A\.?B\.?|S\.?P\.?A\.?|B\.?V\.?|SE|LIMITED|CORPORATION|COMPANY|INCORPORATED)\b",
    re.IGNORECASE,
)


_WORDS = frozenset({"INC", "CO", "LTD", "THE", "AND", "OF", "FOR", "NEW"})


def _entity_word(word: str) -> str:
    """A word of a company's name: initials and legal forms stay as written (LLC, LP, II,
    AJB), other capitals become a name (BERKSHIRE -> Berkshire, INC. -> Inc.)."""
    bare = word.strip(".,&")
    if any(c.islower() for c in word) or (len(bare) <= 3 and bare.isupper() and bare not in _WORDS):
        return word
    return word.title()


def person_name(name: str) -> str:
    """EDGAR lists people as ``LAST FIRST MIDDLE``; read them as ``First Middle Last``.
    Companies and funds keep their order."""
    words = name.replace(",", " ").split()
    if len(words) < 2 or _ENTITY.search(name):
        return " ".join(_entity_word(w) for w in words)
    last, *given = words
    return " ".join(w.title() if not (len(w) <= 2 and w.isupper()) else w for w in [*given, last])


def _text(node: Any, path: str) -> str | None:
    found = node.find(path)
    if found is None or found.text is None:
        return None
    text = found.text.strip()
    return text or None


def _number(node: Any, path: str) -> float | None:
    text = _text(node, path)
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None


def parse_form4(xml: bytes) -> dict[str, Any]:
    """The facts of one Form 4: issuer, the insider and their role, and the transactions."""
    from xml.etree import ElementTree

    # The standard parser loads no external entities and, with the expat that current Pythons
    # ship, withstands entity-expansion bombs.
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ValueError(f"the ownership document is not valid XML: {exc}") from None
    owner = root.find("reportingOwner")
    relation = owner.find("reportingOwnerRelationship") if owner is not None else None
    roles = []
    if relation is not None:
        title = _text(relation, "officerTitle")
        if _text(relation, "isOfficer") in ("1", "true") and title:
            roles.append(title)
        elif _text(relation, "isOfficer") in ("1", "true"):
            roles.append("officer")
        if _text(relation, "isDirector") in ("1", "true"):
            roles.append("director")
        if _text(relation, "isTenPercentOwner") in ("1", "true"):
            roles.append("10% owner")
    transactions = []
    for row in root.iterfind("nonDerivativeTable/nonDerivativeTransaction"):
        transactions.append(
            {
                "code": _text(row, "transactionCoding/transactionCode"),
                "date": _text(row, "transactionDate/value"),
                "shares": _number(row, "transactionAmounts/transactionShares/value"),
                "price": _number(row, "transactionAmounts/transactionPricePerShare/value"),
                "shares_after": _number(
                    row, "postTransactionAmounts/sharesOwnedFollowingTransaction/value"
                ),
            }
        )
    return {
        # EDGAR tags some names with a state or a marker: "LENNAR CORP /NEW/", "APPLE INC /CA/".
        "issuer": re.sub(r"(\s*/[A-Z]{2,5}/)+\s*$", "", _text(root, "issuer/issuerName") or "")
        or None,
        "ticker": (_text(root, "issuer/issuerTradingSymbol") or "").upper() or None,
        "owner": person_name(_text(root, "reportingOwner/reportingOwnerId/rptOwnerName") or ""),
        "role": ", ".join(roles) or None,
        "planned": _text(root, "aff10b5One") in ("1", "true"),
        "transactions": transactions,
    }


def summarize(filing: dict[str, Any], code: str) -> dict[str, Any] | None:
    """All of one filing's transactions with one code, as a single trade."""
    rows = [t for t in filing["transactions"] if t["code"] == code and t["shares"]]
    if not rows:
        return None
    shares = sum(t["shares"] for t in rows)
    priced = [t for t in rows if t["price"]]
    value = sum(t["shares"] * t["price"] for t in priced) if priced else None
    price = value / sum(t["shares"] for t in priced) if priced and value else None
    after = rows[-1]["shares_after"]
    return {
        "code": code,
        "action": ACTIONS.get(code, "reported"),
        "shares": int(shares) if float(shares).is_integer() else shares,
        "price": round(price, 4) if price else None,
        "value": round(value, 2) if value else None,
        "shares_after": int(after) if after is not None and float(after).is_integer() else after,
        "traded_on": min(t["date"] for t in rows if t["date"])
        if any(t["date"] for t in rows)
        else None,
    }


def headline(trade: dict[str, Any]) -> str:
    """``NVIDIA (NVDA): Jensen Huang (CEO) sold 120,000 shares at $180.50 ($21.7M)``."""
    from unlimitedpipe.expr import short_number

    company = trade["issuer"] + (f" ({trade['ticker']})" if trade.get("ticker") else "")
    who = trade["owner"] + (f" ({trade['role']})" if trade.get("role") else "")
    shares = f"{trade['shares']:,.0f}" if isinstance(trade["shares"], (int, float)) else "?"
    text = f"{company}: {who} {trade['action']} {shares} shares"
    if trade.get("price"):
        text += f" at ${trade['price']:,.2f}"
    if trade.get("value"):
        text += f" (${short_number(trade['value'])})"
    return text


_STAKE = re.compile(r"^SCHEDULE 13D(/A)? - (.*?) \((\d+)\) \((Subject|Filed by)\)$")


def stakes(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Schedule 13D filings from EDGAR's list of current filings. The list names each filing
    once per party, the company (Subject) and each investor (Filed by), so entries are joined
    by accession number into one stake: who disclosed 5% or more of which company."""
    joined: dict[str, dict[str, Any]] = {}
    for entry in entries:
        match = _STAKE.match(" ".join((entry.get("title") or "").split()))
        link = entry.get("link") or ""
        if not match or not link.endswith("-index.htm"):
            continue
        accession = link.rsplit("/", 1)[-1].removesuffix("-index.htm")
        stake = joined.setdefault(
            accession,
            {
                "company": None,
                "investors": [],
                "amendment": bool(match.group(1)),
                "filed_at": entry.get("updated"),
                "link": link,
                "accession": accession,
            },
        )
        name = re.sub(r"\s*/[A-Z]{2,}/\s*$", "", match.group(2)).strip()
        if match.group(4) == "Subject":
            stake["company"] = " ".join(_entity_word(w) for w in name.split())
            stake["link"] = link  # the company's copy of the filing
        elif name not in stake["investors"]:
            stake["investors"].append(person_name(name))
    found = []
    for stake in joined.values():
        if not stake["company"]:
            continue
        who = " and ".join(stake["investors"]) or "An investor"
        if stake["amendment"]:
            title = f"{stake['company']}: {who} updated a stake of 5% or more (Schedule 13D/A)"
        else:
            title = f"{stake['company']}: {who} disclosed a stake of 5% or more (Schedule 13D)"
        found.append({"title": title, **stake})
    return found


class Sec(Source):
    """Public filings from the SEC's EDGAR system, as they are filed.

    `activist-stakes` lists the latest Schedule 13D filings: an investor that owns 5% or more
    of a company and may seek to influence it, with 13D/A when a stake changes.

    `ipo-filings` lists new S-1 and F-1 registrations filed from --since to --until (the
    last week by default) by companies that were not public yet: a company that had already
    filed annual or quarterly reports is registering more shares, not going public.

    `insider-trades` reads the latest Form 4 filings and turns each into readable trades:
    who (and their role) bought or sold how many shares of which company, at what price and
    for how much, from the filing's own data. By default only open-market purchases (P) and
    sales (S) are kept.

    The SEC asks automated readers to identify themselves with a contact email; give it
    with `--contact` or `$SEC_CONTACT`. Requests stay far below the SEC's limit of 10 per
    second.
    """

    name = "sec"
    examples = (
        "unlimited sec insider-trades --contact you@example.com",
        "unlimited sec insider-trades --min-value 1000000 | unlimited feed insider.xml",
        "unlimited sec insider-trades --code P    # purchases only",
        "unlimited sec activist-stakes              # who took 5%+ of which company",
        "unlimited sec ipo-filings --since 2024-02-01 --until 2024-02-29",
    )

    resource: Literal["insider-trades", "activist-stakes", "ipo-filings"] = arg("What to read")
    since: str | None = opt("ipo-filings: first day (YYYY-MM-DD; default a week ago)", default=None)
    until: str | None = opt("ipo-filings: last day (YYYY-MM-DD; default today)", default=None)
    contact: str | None = opt(
        "Contact email the SEC asks for (default: $SEC_CONTACT)", default=None, secret=True
    )
    code: list[str] = opt(
        "Transaction codes to keep (repeatable; P purchase, S sale, A award, M exercise, "
        "F tax withholding, G gift; default: P and S)",
        metavar="CODE",
        default_factory=list,
    )
    min_value: float = opt("Only trades worth at least this many dollars", default=0.0)
    limit: int = opt(
        "How many of the latest filings to read, up to 200 (1,000 with --all-new)", default=60
    )
    all_new: bool = opt(
        "Read every Form 4 filed since the last run, up to --limit, remembering the ones read "
        "(for scheduled runs: the latest 200 are only an hour or two on a busy day)",
        default=False,
    )
    timeout: float = opt("Seconds to wait for each response", default=20.0)

    def __post_init__(self) -> None:
        top = 1000 if self.all_new else 200
        if not 1 <= self.limit <= top:
            raise ValueError(f"--limit must be between 1 and {top}")
        self._codes = [c.upper() for c in self.code] or ["P", "S"]
        unknown = [c for c in self._codes if c not in ACTIONS]
        if unknown:
            raise ValueError(
                f"unknown transaction code {unknown[0]!r}; known: {', '.join(ACTIONS)}"
            )

    async def collect(self, ctx: Context):
        contact = (self.contact or os.environ.get("SEC_CONTACT") or "").strip()
        if "@" not in contact:
            raise UsageError(
                "the SEC asks automated readers for a contact email",
                hint="pass --contact you@example.com or set SEC_CONTACT",
            )
        # The SEC turns away User-Agents that carry a URL, so this one is name and email only.
        agent = f"UnlimitedPipe/{__version__} {contact}"
        if self.resource == "activist-stakes":
            async for event in self._stakes(ctx, agent):
                yield event
            return
        if self.resource == "ipo-filings":
            async for event in self._ipos(ctx, agent):
                yield event
            return
        path = state_path(ctx, "sec", "insider-trades-read")
        read: dict[str, str | None] | None = _load_read(path) if self.all_new else None
        try:
            filings = await self._latest(ctx, agent, read)
        except FetchError as exc:
            if (error := ctx.fail(exc, source=self.name, url=LATEST)) is not None:
                yield error
            return
        try:
            async for event in self._trades(ctx, agent, filings, read):
                yield event
        finally:
            if read is not None:
                newest = sorted(read.items(), key=lambda kv: kv[1] or "", reverse=True)
                write_json_atomic(path, dict(newest[:KEEP_READ]))

    async def _trades(self, ctx, agent, filings, read):
        for index_url, filed_at in filings:
            text_url = index_url.removesuffix("-index.htm") + ".txt"
            try:
                response = await ctx.http.get(
                    text_url, user_agent=agent, timeout=self.timeout, interval=SEC_INTERVAL
                )
                filing = parse_form4(_xml_part(response.content))
            except (FetchError, ValueError) as exc:
                if (error := ctx.fail(exc, source=self.name, url=text_url)) is not None:
                    yield error
                continue  # not remembered: the next run tries it again
            if read is not None:
                read[index_url.rsplit("/", 1)[-1].removesuffix("-index.htm")] = filed_at
            for code in self._codes:
                trade = summarize(filing, code)
                if trade is None or (self.min_value and (trade["value"] or 0) < self.min_value):
                    continue
                trade = {
                    "issuer": filing["issuer"],
                    "ticker": filing["ticker"],
                    "owner": filing["owner"],
                    "role": filing["role"],
                    **trade,
                    "planned": filing["planned"],
                    "link": index_url,
                }
                accession = index_url.rsplit("/", 1)[-1].removesuffix("-index.htm")
                yield Event(
                    source=self.name,
                    type="insider-trade",
                    source_url=index_url,
                    key=f"{accession}#{code}",
                    timestamp=filed_at,
                    data={"title": headline(trade), **trade, "accession": accession},
                    metadata={"method": "edgar-form4"},
                )

    async def _stakes(self, ctx: Context, agent: str):
        import feedparser

        params = {
            "action": "getcurrent",
            "type": "SCHEDULE 13D",
            "owner": "include",
            "count": "100",
            "output": "atom",
        }
        try:
            response = await ctx.http.get(
                LATEST, params=params, user_agent=agent, timeout=self.timeout, cache=False
            )
        except FetchError as exc:
            if (error := ctx.fail(exc, source=self.name, url=LATEST)) is not None:
                yield error
            return
        entries = [dict(e) for e in feedparser.parse(response.content).entries]
        for stake in stakes(entries)[: self.limit]:
            yield Event(
                source=self.name,
                type="stake",
                source_url=stake["link"],
                key=stake["accession"],
                timestamp=stake["filed_at"],
                data=stake,
                metadata={"method": "edgar-schedule-13d"},
            )

    async def _ipos(self, ctx: Context, agent: str):
        from datetime import UTC, datetime, timedelta

        today = datetime.now(UTC).date()
        since = self.since or (today - timedelta(days=7)).isoformat()
        until = self.until or today.isoformat()
        reported: dict[str, list[str]] = {}
        for form in IPO_FORMS:
            try:
                hits = await self._search(ctx, agent, form, since, until)
            except FetchError as exc:
                if (error := ctx.fail(exc, source=self.name, url=SEARCH)) is not None:
                    yield error
                continue
            for hit in hits:
                filing = ipo_filing(hit)
                if filing is None or filing["form"] != form:
                    continue  # an amendment (S-1/A), or another form the search matched
                cik = filing["cik"]
                if cik not in reported:
                    try:
                        reported[cik] = await self._periodic(ctx, agent, cik, filing["filed_at"])
                    except (FetchError, ValueError) as exc:
                        if (error := ctx.fail(exc, source=self.name, url=SUBMISSIONS)) is not None:
                            yield error
                        continue
                if any(day < filing["filed_at"] for day in reported[cik]):
                    continue  # public already
                yield Event(
                    source=self.name,
                    type="ipo-filing",
                    source_url=filing["link"],
                    key=filing["accession"],
                    timestamp=f"{filing['filed_at']}T00:00:00Z",
                    data=filing,
                    metadata={"method": "edgar-full-text-search"},
                )

    async def _search(self, ctx: Context, agent: str, form: str, since: str, until: str):
        """Every search hit for one form filed in the period, 100 at a time."""
        hits: list[dict[str, Any]] = []
        while len(hits) < MOST_HITS:
            params = {"forms": form, "dateRange": "custom", "startdt": since, "enddt": until}
            if hits:
                params["from"] = str(len(hits))
            response = await ctx.http.get(
                SEARCH,
                params=params,
                user_agent=agent,
                timeout=self.timeout,
                interval=SEC_INTERVAL,
            )
            page = (response.json().get("hits") or {}).get("hits") or []
            hits += page
            if len(page) < 100:
                break
        return hits

    async def _periodic(self, ctx: Context, agent: str, cik: str, before: str) -> list[str]:
        """The days a company filed annual or quarterly reports, as far back as ``before``."""
        url = f"{SUBMISSIONS}CIK{int(cik):010d}.json"
        response = await ctx.http.get(
            url, user_agent=agent, timeout=self.timeout, interval=SEC_INTERVAL
        )
        document = response.json()
        days = _periodic_days((document.get("filings") or {}).get("recent") or {})
        recent = (document.get("filings") or {}).get("recent") or {}
        oldest = min(recent.get("filingDate") or [before])
        if not any(d < before for d in days) and oldest > before:
            # A long history is split: the older filings are in more files.
            for older in (document.get("filings") or {}).get("files") or []:
                page = await ctx.http.get(
                    SUBMISSIONS + older["name"],
                    user_agent=agent,
                    timeout=self.timeout,
                    interval=SEC_INTERVAL,
                )
                days += _periodic_days(page.json())
        return days

    async def _latest(
        self, ctx: Context, agent: str, read: dict[str, str | None] | None = None
    ) -> list[tuple[str, str | None]]:
        """Index pages of the newest Form 4 filings, newest first, each once; with `read`,
        only those not read yet, going back until the ones read before."""
        import feedparser

        # A filing is listed once per party (the insider, the company, co-filers), each under
        # its own folder; the accession number at the end of the link identifies it. The list
        # also holds every form starting with 4 (424B2 prospectuses): about two days fit in
        # 5,000 entries.
        filings: dict[str, tuple[str, str | None]] = {}
        for start in range(0, 200 if read is None else 5000, 100):
            params = {
                "action": "getcurrent",
                "type": "4",
                "owner": "include",
                "count": "100",
                "start": str(start),
                "output": "atom",
            }
            response = await ctx.http.get(
                LATEST,
                params=params,
                user_agent=agent,
                timeout=self.timeout,
                cache=False,
                interval=SEC_INTERVAL,
            )
            feed = feedparser.parse(response.content)
            known = fresh = 0
            for entry in feed.entries:
                link = entry.get("link") or ""
                accession = link.rsplit("/", 1)[-1]
                # `type=4` matches every form that starts with 4, such as 424B2 prospectuses.
                is_form4 = re.match(r"4(/A)? - ", entry.get("title") or "")
                if not (is_form4 and link.endswith("-index.htm")):
                    continue
                if read is not None and accession.removesuffix("-index.htm") in read:
                    known += 1
                elif accession not in filings:
                    filings[accession] = (link, entry.get("updated"))
                    fresh += 1
            caught_up = read is not None and known and not fresh  # back to what was read
            if len(filings) >= self.limit or len(feed.entries) < 100 or caught_up:
                break
        return list(filings.values())[: self.limit]


SEC_INTERVAL = 0.2  # five requests a second: half of what the SEC allows automated readers


def _periodic_days(filings: dict[str, Any]) -> list[str]:
    forms, days = filings.get("form") or [], filings.get("filingDate") or []
    return [d for f, d in zip(forms, days, strict=False) if str(f).split("/")[0] in PERIODIC]


def ipo_filing(hit: dict[str, Any]) -> dict[str, Any] | None:
    """A search hit as a registration: the company (without the ticker EDGAR shows today),
    the form, when and where, and the filing's index page."""
    source = hit.get("_source") or {}
    ident = str(hit.get("_id") or "")
    names, ciks = source.get("display_names") or [], source.get("ciks") or []
    if not (names and ciks and ":" in ident and source.get("file_date")):
        return None
    if NOT_IPO_SICS & set(source.get("sics") or []):
        return None
    company = re.sub(r"\s*\(CIK \d+\)\s*$", "", names[0])
    company = re.sub(r"\s*\([A-Z0-9., -]{1,30}\)\s*$", "", company)  # today's ticker
    company = re.sub(r"\s*/\s*[A-Z]{2}\s*/?\s*$", "", " ".join(company.split()))
    accession = ident.split(":", 1)[0]
    cik = str(int(ciks[0]))
    form = str(source.get("form") or "")
    place = (source.get("biz_locations") or [None])[0]
    filed = str(source["file_date"])
    return {
        "title": f"{company} filed to go public ({form})",
        "company": company,
        "form": form,
        "filed_at": filed,
        "published_at": f"{filed}T00:00:00Z",
        "place": place,
        "cik": cik,
        "accession": accession,
        "link": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/"
        f"{accession}-index.htm",
        "summary": f"Registration statement filed {filed}"
        + (f" by a company based in {place}." if place else "."),
    }


KEEP_READ = 20000  # Form 4 accession numbers remembered by --all-new: about two months


def _load_read(path) -> dict[str, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _xml_part(content: bytes) -> bytes:
    """The ownership document inside a full submission text file."""
    match = re.search(rb"<XML>\s*(.*?)\s*</XML>", content, re.DOTALL)
    if not match:
        raise ValueError("the filing has no ownership document")
    return match.group(1)
