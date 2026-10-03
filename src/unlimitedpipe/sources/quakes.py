"""Earthquakes as soon as the first agency reports them: GFZ, JMA and USGS (public)."""

from __future__ import annotations

import asyncio
import json
import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from unlimitedpipe.component import Source, opt
from unlimitedpipe.context import Context
from unlimitedpipe.errors import FetchError
from unlimitedpipe.event import Event
from unlimitedpipe.state import state_path, write_json_atomic

USGS = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/{level}_day.geojson"
GFZ = "https://geofon.gfz.de/fdsnws/event/1/query"
GFZ_EVENT = "https://geofon.gfz.de/eqinfo/event.php?id={id}"
JMA = "https://www.jma.go.jp/bosai/quake/data/list.json"
JMA_MAP = "https://www.jma.go.jp/bosai/map.html?contents=earthquake_map&lang=en#{id}"
SAME_SECONDS = 120  # JMA gives the minute only; agencies' origin times differ by seconds
SAME_KM = 400  # first locations of a remote quake can be far apart
STRONG = {"5-", "5+", "6-", "6+", "7"}  # JMA intensities that matter whatever the magnitude
# when two agencies first list a quake in the same run, the one whose report reads best
PRIORITY = {"JMA": 0, "USGS": 1, "GFZ": 2}


def _epoch(text: str) -> float:
    when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return (when if when.tzinfo else when.replace(tzinfo=UTC)).timestamp()


def usgs_reports(document: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for feature in document.get("features") or []:
        p = feature.get("properties") or {}
        lon, lat = (feature.get("geometry") or {}).get("coordinates", [None, None])[:2]
        if p.get("mag") is None or lat is None or p.get("type", "earthquake") != "earthquake":
            continue
        found.append(
            {
                "agency": "USGS",
                "id": feature.get("id"),
                "t": p["time"] / 1000,
                "lat": lat,
                "lon": lon,
                "mag": float(p["mag"]),
                "title": p.get("title") or f"M {p['mag']:.1f} - {p.get('place')}",
                "place": p.get("place") or "",
                "link": p.get("url") or "",
            }
        )
    return found


def gfz_reports(text: str) -> list[dict[str, Any]]:
    """GFZ's FDSN event service, text format: one pipe-separated line per event."""
    found = []
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        f = line.split("|")
        if len(f) < 14 or (f[13] and f[13] != "earthquake"):
            continue
        try:
            mag, lat, lon = float(f[10]), float(f[2]), float(f[3])
        except ValueError:
            continue
        found.append(
            {
                "agency": "GFZ",
                "id": f[0],
                "t": _epoch(f[1]),
                "lat": lat,
                "lon": lon,
                "mag": mag,
                "title": f"M {mag:.1f} - {f[12]}",
                "place": f[12],
                "link": GFZ_EVENT.format(id=f[0]),
            }
        )
    return found


def jma_reports(document: list[dict[str, Any]], min_magnitude: float) -> list[dict[str, Any]]:
    """JMA's list of quake reports for Japan: one per quake (its fullest report), with an
    English place name; strong shaking counts whatever the magnitude."""
    best: dict[str, dict[str, Any]] = {}
    for entry in document:
        title = entry.get("en_ttl") or ""
        if "Distant" in title or "Earthquake" not in title:
            continue
        where = re.match(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)", entry.get("cod") or "")
        try:
            mag = float(entry.get("mag") or "")
        except ValueError:
            continue
        intensity = entry.get("maxi") or ""
        if not where or not entry.get("at") or (mag < min_magnitude and intensity not in STRONG):
            continue
        eid = str(entry.get("eid"))
        if eid in best and not intensity:
            continue  # the report with intensities says more
        place = entry.get("en_anm") or "Japan"
        level = intensity.replace("-", " lower").replace("+", " upper")
        shaking = f" (JMA intensity {level})" if intensity else ""
        best[eid] = {
            "agency": "JMA",
            "id": eid,
            "t": _epoch(entry["at"]),
            "lat": float(where.group(1)),
            "lon": float(where.group(2)),
            "mag": mag,
            "title": f"M {mag:.1f} - {place}, Japan{shaking}",
            "place": f"{place}, Japan",
            "link": JMA_MAP.format(id=eid),
        }
    return list(best.values())


def km_between(a: dict[str, Any], b: dict[str, Any]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = (
        math.sin((la2 - la1) / 2) ** 2
        + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    )
    return 6371 * 2 * math.asin(math.sqrt(min(1.0, h)))


def merge(
    reports: list[dict[str, Any]], clusters: list[dict[str, Any]], now: float
) -> list[dict[str, Any]]:
    """Each report joins the quake it belongs to (close in time and place), or starts a new
    one, which keeps the first report's id, title and link for good."""
    reports = sorted(reports, key=lambda r: (PRIORITY.get(r["agency"], 9), r["t"]))
    for report in reports:
        match = next(
            (
                c
                for c in clusters
                if abs(c["t"] - report["t"]) <= SAME_SECONDS and km_between(c, report) <= SAME_KM
            ),
            None,
        )
        if match is None:
            match = {
                "key": f"{report['agency'].lower()}:{report['id']}",
                "first": report["agency"],
                "seen": now,
                **{k: report[k] for k in ("t", "lat", "lon", "mag", "title", "place", "link")},
                "reports": {},
            }
            clusters.append(match)
        match["reports"][report["agency"]] = {k: report[k] for k in ("id", "mag", "place", "link")}
    return clusters


class Quakes(Source):
    """Earthquakes as soon as the first of three agencies reports them, one item per quake.

    GFZ (Germany) usually locates quakes anywhere in the world within about ten minutes,
    JMA (Japan) reports Japan's within two or three, and USGS reports quakes in the US within
    minutes but many elsewhere only after 15 to 30. Each quake keeps its first report's title
    and link; the summary names every agency that has reported it. Reports of one quake are
    matched by time (two minutes) and place (400 km).
    """

    name = "quakes"
    examples = (
        "unlimited quakes",
        "unlimited quakes --min-magnitude 6 --agency JMA --agency USGS",
    )

    min_magnitude: float = opt("Only quakes of at least this magnitude", default=4.5)
    days: int = opt("Days back to read (1 to 7)", default=2)
    agency: list[str] = opt(
        "Agencies to read: USGS, GFZ, JMA (repeatable; default all)",
        default_factory=list,
        metavar="NAME",
    )
    namespace: str = opt("Name of the state that remembers which quake is which", default="quakes")
    timeout: float = opt("Seconds to wait for each agency", default=20.0)

    def __post_init__(self) -> None:
        self.agency = [a.upper() for a in self.agency] or ["USGS", "GFZ", "JMA"]
        unknown = [a for a in self.agency if a not in PRIORITY]
        if unknown:
            raise ValueError(f"unknown agency {unknown[0]!r}: use USGS, GFZ or JMA")
        if not 1 <= self.days <= 7:
            raise ValueError("--days must be 1 to 7")

    async def _read(self, ctx: Context, agency: str) -> list[dict[str, Any]]:
        start = datetime.now(UTC) - timedelta(days=self.days)
        if agency == "USGS":
            level = "4.5" if self.min_magnitude >= 4.5 else "2.5"
            url = USGS.format(level=level).replace("_day", "_week" if self.days > 1 else "_day")
            response = await ctx.http.get(url, timeout=self.timeout)
            found = usgs_reports(json.loads(response.text))
        elif agency == "GFZ":
            params = {
                "starttime": start.strftime("%Y-%m-%dT%H:%M:%S"),
                "minmagnitude": self.min_magnitude,
                "format": "text",
            }
            response = await ctx.http.get(GFZ, params=params, timeout=self.timeout, robots=True)
            found = gfz_reports(response.text)
        else:
            response = await ctx.http.get(JMA, timeout=self.timeout, robots=True)
            found = jma_reports(json.loads(response.text), self.min_magnitude)
        return [
            r
            for r in found
            if r["t"] >= start.timestamp()
            and (r["mag"] >= self.min_magnitude or r["agency"] == "JMA")
        ]

    async def collect(self, ctx: Context):
        results = await asyncio.gather(
            *(self._read(ctx, agency) for agency in self.agency), return_exceptions=True
        )
        reports = []
        for agency, result in zip(self.agency, results, strict=True):
            if isinstance(result, FetchError):
                if (error := ctx.fail(result, source=self.name, url=result.url)) is not None:
                    yield error
            elif isinstance(result, (ValueError, KeyError, TypeError)):
                ctx.warn(f"quakes: {agency}'s answer could not be read ({result})")
            elif isinstance(result, BaseException):
                raise result
            else:
                reports.extend(result)
        path = state_path(ctx, "quakes", self.namespace)
        try:
            clusters = json.loads(path.read_text(encoding="utf-8")).get("quakes", [])
        except (OSError, ValueError, AttributeError):
            clusters = []
        now = datetime.now(UTC).timestamp()
        oldest = now - (self.days + 2) * 86400
        clusters = merge(reports, [c for c in clusters if c["t"] >= oldest], now)
        write_json_atomic(path, {"version": 1, "quakes": clusters})
        listed = {(r["agency"], r["id"]) for r in reports}
        current = [
            c
            for c in clusters
            if any((agency, seen["id"]) in listed for agency, seen in c["reports"].items())
        ]
        for quake in sorted(current, key=lambda c: c["t"], reverse=True):
            others = [
                f"{agency} (M {seen['mag']:.1f}, {seen['place']})"
                for agency, seen in quake["reports"].items()
                if agency != quake["first"]
            ]
            when = datetime.fromtimestamp(quake["t"], UTC)
            summary = (
                f"Magnitude {quake['mag']:.1f}, {quake['place']}, at {when:%H:%M} UTC. "
                f"First reported by {quake['first']}"
                + (f"; also reported by {', '.join(others)}" if others else "")
                + "."
            )
            yield Event(
                source=self.name,
                type="record",
                source_url=quake["link"],
                key=quake["key"],
                timestamp=when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                data={
                    "title": quake["title"],
                    "summary": summary,
                    "link": quake["link"],
                    "published_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "magnitude": quake["mag"],
                    "first_report": quake["first"],
                    "agencies": sorted(quake["reports"]),
                },
                metadata={"method": "quakes"},
            )
