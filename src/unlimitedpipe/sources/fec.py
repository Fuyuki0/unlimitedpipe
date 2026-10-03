"""US federal election spending from the Federal Election Commission's bulk data (public)."""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import UTC, datetime
from typing import Any, Literal

from unlimitedpipe.component import Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError
from unlimitedpipe.event import Event
from unlimitedpipe.names import readable_name

BULK = "https://www.fec.gov/files/bulk-downloads/{cycle}/"
FILING = "https://docquery.fec.gov/cgi-bin/fecimg/?{image}"
FEC_INTERVAL = 10.0  # www.fec.gov's robots.txt asks for ten seconds between requests
OFFICES = {"H": "the House", "S": "the Senate", "P": "President"}
TOO_BIG = 1e8  # one expenditure over $100M is a mistyped form, not an ad buy


def cycle_of(day: datetime) -> int:
    """The two-year election cycle a day belongs to (2025 and 2026: 2026)."""
    return day.year + day.year % 2


def committees(zipped: bytes) -> dict[str, str]:
    """Committee ID -> name, from the FEC's committee master file (cmYY.zip)."""
    with zipfile.ZipFile(io.BytesIO(zipped)) as archive:
        text = archive.read(archive.namelist()[0]).decode("utf-8", errors="replace")
    found = {}
    for line in text.splitlines():
        fields = line.split("|")
        if len(fields) > 1 and fields[0].startswith("C"):
            found[fields[0]] = fields[1]
    return found


def _day(text: str) -> str | None:
    try:
        return datetime.strptime(text.strip(), "%d-%b-%y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _amendment(row: dict[str, str]) -> int:
    """N (new) 0, A1 1, A2 2...: the later amendment wins."""
    mark = (row.get("amndt_ind") or "N").strip().upper()
    digits = "".join(c for c in mark if c.isdigit())
    return 0 if mark == "N" else int(digits or 1)


SUFFIXES = {"JR", "SR", "II", "III", "IV"}


def _cased(word: str) -> str:
    """One word of a name written in capitals: "MCCORMICK" McCormick, "O'ROURKE" O'Rourke,
    "J." and "III" as they are."""
    bare = word.strip(".,").upper()
    if len(bare) <= 1 or bare in SUFFIXES - {"JR", "SR"}:
        return word
    cased = "-".join(part.capitalize() for part in word.lower().split("-"))
    cased = re.sub(r"'(\w)", lambda m: "'" + m.group(1).upper(), cased)
    if cased.startswith("Mc") and len(cased) > 3:
        cased = "Mc" + cased[2:].capitalize()
    return cased


def _person(name: str) -> str:
    """A candidate's name as people write it: "HARRIGAN, PAT" Pat Harrigan, "BIDEN, JOSEPH R
    JR" Joseph R Biden Jr, "TRUMP, DONALD J. / J.D. VANCE" Donald J. Trump."""
    name = name.split("/")[0]
    last, _, first = name.partition(",")
    given = first.split()
    suffix = [w for w in given if w.strip(".").upper() in SUFFIXES]
    given = [w for w in given if w not in suffix]
    words = [*given, *last.split(), *suffix] if first else name.split()
    if name.upper() == name:
        return " ".join(_cased(w) for w in words)
    whole = " ".join(words)
    return readable_name(whole) or whole


# Short words in committee names that are words, not initials ("Get Our Jobs Back")
WORDS = frozenset(
    {
        "ACT",
        "BAD",
        "CAN",
        "CAP",
        "DOG",
        "END",
        "ERA",
        "FIX",
        "GET",
        "GUN",
        "IS",
        "IT",
        "KEY",
        "LET",
        "LOS",
        "MAD",
        "NO",
        "NOW",
        "OUR",
        "OUT",
        "SAN",
        "SKY",
        "TEA",
        "UP",
        "WE",
        "WHO",
        "WIN",
    }
)


def _committee(name: str) -> str:
    """A committee's name, readable: "... EMPLOYEES P E O P L E" ... Employees People, "GET
    OUR JOBS BACK, INC" Get Our Jobs Back, Inc."""
    joined = re.sub(r"\b(?:[A-Za-z] ){2,}[A-Za-z]\b", lambda m: m.group(0).replace(" ", ""), name)
    readable = readable_name(joined) or joined
    if not joined.isupper():
        return readable
    return re.sub(
        r"\b[A-Z]{2,3}\b",
        lambda m: m.group(0).capitalize() if m.group(0) in WORDS else m.group(0),
        readable,
    )


def outside_spending(table: str, known: dict[str, str], min_value: float = 0.0) -> list[dict]:
    """Independent expenditures by committees in the FEC's committee list (the file also holds
    forms filed by individuals with made-up amounts), the latest amendment of each, newest
    first."""
    from unlimitedpipe.expr import short_number

    latest: dict[tuple[str, str], dict[str, str]] = {}
    for row in csv.DictReader(io.StringIO(table)):
        spender = row.get("spe_id") or ""
        try:
            amount = float(row.get("exp_amo") or 0)
        except ValueError:
            continue
        if spender not in known or amount < min_value or amount > TOO_BIG:
            continue
        key = (spender, row.get("tran_id") or row.get("image_num") or "")
        before = latest.get(key)
        if before is None or _amendment(row) >= _amendment(before):
            latest[key] = row
    found = []
    for (spender, transaction), row in latest.items():
        # dated when filed (public): ads are often reported before they run
        when = _day(row.get("receipt_dat") or "") or _day(row.get("exp_date") or "")
        shown = _day(row.get("dissem_dt") or "")
        if not when or not row.get("cand_name"):
            continue
        amount = float(row["exp_amo"])
        name = _committee(known[spender])
        candidate = _person(row["cand_name"])
        side = "supporting" if row.get("sup_opp") == "S" else "opposing"
        office = OFFICES.get(row.get("can_office") or "", "office")
        state = (row.get("can_office_state") or "").strip()
        district = (row.get("can_office_dis") or "").strip()
        place = state + (f"-{district}" if row.get("can_office") == "H" and district else "")
        where = f" ({place})" if place and row.get("can_office") != "P" else ""
        purpose = " ".join((row.get("pur") or "").split())
        payee = " ".join((row.get("pay") or "").split())
        summary = (
            f"{name} reported ${amount:,.2f} {side} {candidate} for {office}{where}"
            + (f": {purpose}" if purpose else "")
            + (f", paid to {payee}" if payee else "")
            + (f". To be seen from {shown}" if shown and shown > when else "")
            + (f". Seen from {shown}" if shown and shown <= when else "")
            + f"; reported {when}, as filed with the FEC."
        )
        found.append(
            {
                "title": f"{name} spent ${short_number(amount)} {side} {candidate} for "
                f"{office}{where}",
                "summary": summary,
                "spender": name,
                "candidate": candidate,
                "side": side,
                "value": amount,
                "published_at": f"{when}T00:00:00Z",
                "link": FILING.format(image=row.get("image_num") or ""),
                "id": f"{spender}:{transaction}",
            }
        )
    found.sort(key=lambda item: item["published_at"], reverse=True)
    return found


class Fec(Source):
    """US federal election spending, from the Federal Election Commission's bulk files.

    `outside-spending` is what super PACs, parties and other committees report spending for
    or against a candidate (independent expenditures), each with who spent how much, for or
    against whom, for which office, and the filing. Only committees in the FEC's committee
    list count: the files also hold forms individuals filed with made-up amounts. Amounts are
    as filed. The bulk files are refreshed daily; www.fec.gov asks for ten seconds between
    requests.
    """

    name = "fec"
    examples = (
        "unlimited fec outside-spending --min-value 1000000",
        "unlimited fec outside-spending --cycle 2024 --min-value 5000000",
    )

    resource: Literal["outside-spending"] = arg("What to read")
    cycle: int | None = opt(
        "Two-year election cycle, e.g. 2024 (default: the current one)", default=None
    )
    min_value: float = opt("Only expenditures of at least this many dollars", default=0.0)
    timeout: float = opt("Seconds to wait for each download", default=120.0)

    async def collect(self, ctx: Context):
        cycle = self.cycle or cycle_of(datetime.now(UTC))
        base = BULK.format(cycle=cycle)
        table_url = f"{base}independent_expenditure_{cycle}.csv"
        names_url = f"{base}cm{cycle % 100:02d}.zip"
        try:
            names = committees(
                (
                    await ctx.http.get(
                        names_url, timeout=self.timeout, interval=FEC_INTERVAL, robots=True
                    )
                ).content
            )
            table = await ctx.http.get(
                table_url, timeout=self.timeout, interval=FEC_INTERVAL, robots=True
            )
        except FetchError as exc:
            if (error := ctx.fail(exc, source=self.name, url=exc.url)) is not None:
                yield error
            return
        text = table.content.decode("utf-8", errors="replace")
        for item in outside_spending(text, names, self.min_value):
            data: dict[str, Any] = {k: v for k, v in item.items() if k != "id"}
            yield Event(
                source=self.name,
                type="expenditure",
                source_url=item["link"],
                key=item["id"],
                timestamp=item["published_at"],
                data=data,
                metadata={"method": "fec-bulk", "file": table_url},
            )
