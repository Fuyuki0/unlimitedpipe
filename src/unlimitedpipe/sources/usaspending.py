"""New US federal contracts and grants from USAspending.gov (public)."""

from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from unlimitedpipe.component import Source, arg, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError
from unlimitedpipe.event import Event
from unlimitedpipe.names import readable_name

SEARCH = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
AWARD = "https://www.usaspending.gov/award/{id}"
KINDS = {  # USAspending's award type codes
    "contracts": ["A", "B", "C", "D"],
    "grants": ["02", "03", "04", "05"],
}
FIELDS = [
    "Award ID",
    "Recipient Name",
    "Award Amount",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Description",
    "generated_internal_id",
    "Base Obligation Date",
    "Start Date",
]


def _sentence(text: str) -> str:
    """A description written in capitals, as a sentence."""
    text = " ".join((text or "").split()).rstrip(".")
    if text.isupper():
        text = text.lower()
    return text[:1].upper() + text[1:]


def _recipient(name: str) -> str:
    """A recipient as people write it: entities decoded, and agencies named the way round
    ("HEALTH CARE SERVICES, CALIFORNIA DEPARTMENT OF" California Department of Health Care
    Services)."""
    name = " ".join(html.unescape(name or "").split())
    inverted = re.match(r"^(.+?),\s*(.+?)\s+(DEPARTMENT|DEPT\.?|OFFICE|DIVISION) OF$", name, re.I)
    if inverted:
        name = f"{inverted.group(2)} {inverted.group(3)} of {inverted.group(1)}"
    return readable_name(name) or name


def award(row: dict[str, Any], kind: str) -> dict[str, Any] | None:
    from unlimitedpipe.expr import short_number

    try:
        amount = float(row.get("Award Amount") or 0)
    except ValueError:
        return None
    day = row.get("Base Obligation Date") or row.get("Start Date")
    if not (day and row.get("generated_internal_id") and row.get("Recipient Name")):
        return None
    recipient = _recipient(row["Recipient Name"])
    agency = row.get("Awarding Agency") or "a federal agency"
    office = row.get("Awarding Sub Agency") or ""
    description = _sentence(row.get("Description") or "")
    return {
        "title": f"{recipient} won a ${short_number(amount)} contract from the {agency}"
        if kind == "contracts"
        else f"{recipient} was awarded a ${short_number(amount)} grant by the {agency}",
        "summary": (f"{description}. " if description else "")
        + (f"Awarded by {office}. " if office and office != row.get("Awarding Agency") else "")
        + f"Award {row.get('Award ID')}, first obligated {day}, as reported to USAspending.gov.",
        "recipient": recipient,
        "agency": agency,
        "value": amount,
        "link": AWARD.format(id=row["generated_internal_id"]),
        "published_at": f"{day}T00:00:00Z",
        "id": row["generated_internal_id"],
    }


class UsaSpending(Source):
    """New US federal contracts or grants, biggest first, from USAspending.gov.

    Each is a new award (not a change to an old one) of at least --min-value dollars, first
    obligated within the last --days days, with who won it, from which agency, and what for.
    Agencies report contracts within days, so the newest days fill in over the next week.
    """

    name = "usaspending"
    examples = (
        "unlimited usaspending contracts",
        "unlimited usaspending grants --min-value 50000000 --days 14",
    )

    resource: Literal["contracts", "grants"] = arg("What to read")
    min_value: float = opt("Only awards of at least this many dollars", default=100_000_000.0)
    days: int = opt("Days back to read (1 to 90)", default=14)
    limit: int = opt("Most awards to list (1 to 100)", default=100)
    timeout: float = opt("Seconds to wait for USAspending", default=60.0)

    def __post_init__(self) -> None:
        if not 1 <= self.days <= 90:
            raise ValueError("--days must be 1 to 90")
        if not 1 <= self.limit <= 100:
            raise ValueError("--limit must be 1 to 100")

    async def collect(self, ctx: Context):
        today = datetime.now(UTC).date()
        body = {
            "filters": {
                "award_type_codes": KINDS[self.resource],
                "time_period": [
                    {
                        "start_date": (today - timedelta(days=self.days)).isoformat(),
                        "end_date": today.isoformat(),
                        "date_type": "new_awards_only",
                    }
                ],
                "award_amounts": [{"lower_bound": self.min_value}],
            },
            "fields": FIELDS,
            "sort": "Award Amount",
            "order": "desc",
            "limit": self.limit,
            "page": 1,
        }
        try:
            response = await ctx.http.post(
                SEARCH, json_body=body, timeout=self.timeout, secret_url=False
            )
            rows = json.loads(response.text).get("results") or []
        except FetchError as exc:
            if (error := ctx.fail(exc, source=self.name, url=SEARCH)) is not None:
                yield error
            return
        except ValueError as exc:
            ctx.warn(f"usaspending: the answer could not be read ({exc})")
            return
        for row in rows:
            found = award(row, self.resource)
            if found is None:
                continue
            yield Event(
                source=self.name,
                type=self.resource.removesuffix("s"),
                source_url=found["link"],
                key=found["id"],
                timestamp=found["published_at"],
                data={k: v for k, v in found.items() if k != "id"},
                metadata={"method": "usaspending-api"},
            )
