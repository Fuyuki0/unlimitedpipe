"""US airport ground stops and delays from the FAA's National Airspace System status (public)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any

from unlimitedpipe.component import Source, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError
from unlimitedpipe.event import Event

STATUS = "https://nasstatus.faa.gov/api/airport-status-information"
PAGE = "https://nasstatus.faa.gov/"
AIRPORTS = {  # the busiest US airports, by the code the FAA uses
    "ATL": "Atlanta", "BOS": "Boston", "BWI": "Baltimore", "CLT": "Charlotte",
    "DCA": "Washington National", "DEN": "Denver", "DFW": "Dallas/Fort Worth", "DTW": "Detroit",
    "EWR": "Newark", "FLL": "Fort Lauderdale", "HNL": "Honolulu", "IAD": "Washington Dulles",
    "IAH": "Houston", "JFK": "New York JFK", "LAS": "Las Vegas", "LAX": "Los Angeles",
    "LGA": "New York LaGuardia", "MCO": "Orlando", "MDW": "Chicago Midway", "MIA": "Miami",
    "MSP": "Minneapolis", "ORD": "Chicago O'Hare", "PHL": "Philadelphia", "PHX": "Phoenix",
    "PDX": "Portland", "SAN": "San Diego", "SEA": "Seattle", "SFO": "San Francisco",
    "SLC": "Salt Lake City", "TPA": "Tampa", "AUS": "Austin", "BNA": "Nashville",
    "MSY": "New Orleans", "RDU": "Raleigh-Durham", "SJC": "San Jose", "OAK": "Oakland",
    "SMF": "Sacramento", "STL": "St. Louis", "HOU": "Houston Hobby", "DAL": "Dallas Love Field",
}  # fmt: skip
CAUSES = {"WX": "", "RWY": "runway", "VOL": "", "EQ": "equipment", "TM": ""}


def _airport(code: str) -> str:
    return f"{AIRPORTS[code]} ({code})" if code in AIRPORTS else code


def _reason(text: str) -> str:
    """A reason as words: "WX:Thunderstorms" thunderstorms, "RWY:Construction" runway
    construction."""
    kind, _, what = (text or "").partition(":")
    if not what:
        return (text or "").strip().lower()
    prefix = CAUSES.get(kind.upper(), kind.lower())
    return f"{prefix} {what.strip().lower()}".strip()


def minutes(text: str) -> int:
    """Minutes in a duration: "2 hours and 18 minutes" 138."""
    hours = re.search(r"(\d+)\s*hour", text or "")
    mins = re.search(r"(\d+)\s*minute", text or "")
    return (int(hours.group(1)) * 60 if hours else 0) + (int(mins.group(1)) if mins else 0)


def airport_status(xml: str, min_delay: int = 45) -> list[dict[str, Any]]:
    """Ground stops, ground delay programs, and departure or arrival delays of at least
    ``min_delay`` minutes, one item each."""
    root = ET.fromstring(xml)
    found = []
    for program in root.iter("Program"):
        code = program.findtext("ARPT") or ""
        reason = _reason(program.findtext("Reason") or "")
        until = program.findtext("End_Time") or ""
        found.append(
            {
                "kind": "ground stop",
                "airport": code,
                "reason": reason,
                "title": f"Ground stop at {_airport(code)}: {reason}"
                + (f", until {until}" if until else ""),
            }
        )
    for delay in root.iter("Ground_Delay"):
        code = delay.findtext("ARPT") or ""
        average, most = delay.findtext("Avg") or "", delay.findtext("Max") or ""
        reason = _reason(delay.findtext("Reason") or "")
        found.append(
            {
                "kind": "ground delay",
                "airport": code,
                "reason": reason,
                "title": f"Ground delays at {_airport(code)}: {reason}"
                + (f", average {average}" if average else "")
                + (f", up to {most}" if most else ""),
            }
        )
    for delay in root.iter("Delay"):
        code = delay.findtext("ARPT") or ""
        for way in delay.iter("Arrival_Departure"):
            low, high = way.findtext("Min") or "", way.findtext("Max") or ""
            if minutes(high) < min_delay:
                continue
            direction = (way.get("Type") or "Departure").lower()
            trend = (way.findtext("Trend") or "").lower()
            reason = _reason(delay.findtext("Reason") or "")
            found.append(
                {
                    "kind": f"{direction} delay",
                    "airport": code,
                    "reason": reason,
                    "title": f"{direction.capitalize()} delays at {_airport(code)}: {low} to "
                    f"{high}" + (f", {trend}" if trend else "") + f" ({reason})",
                }
            )
    return found


class Faa(Source):
    """US airport ground stops and delays, from the FAA's National Airspace System status.

    `airports` lists every ground stop, every ground delay program (with the average and
    longest delay) and departure or arrival delays of at least --min-delay minutes, at the
    moment of reading. The FAA updates it every minute. One item per airport, kind and
    reason a day: a stop that ends and starts again the same day is not listed twice.
    """

    name = "faa"
    examples = ("unlimited faa", "unlimited faa --min-delay 60")

    min_delay: int = opt(
        "Only departure or arrival delays of at least this many minutes", default=45
    )
    timeout: float = opt("Seconds to wait for the FAA", default=20.0)

    async def collect(self, ctx: Context):
        try:
            response = await ctx.http.get(STATUS, timeout=self.timeout, robots=True, cache=False)
            found = airport_status(response.text, self.min_delay)
        except FetchError as exc:
            if (error := ctx.fail(exc, source=self.name, url=exc.url)) is not None:
                yield error
            return
        except ET.ParseError as exc:
            ctx.warn(f"faa: the FAA's answer could not be read ({exc})")
            return
        now = datetime.now(UTC)
        day = now.strftime("%Y-%m-%d")
        for item in found:
            key = f"{day}:{item['airport']}:{item['kind']}:{item['reason']}"
            yield Event(
                source=self.name,
                type="airport-status",
                source_url=PAGE,
                key=key,
                timestamp=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                data={
                    **item,
                    "summary": f"{item['title']}. FAA National Airspace System status, "
                    f"{now:%Y-%m-%d %H:%M} UTC.",
                    "link": f"{PAGE}#{item['airport']}",
                    "published_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                metadata={"method": "faa-nas-status"},
            )
