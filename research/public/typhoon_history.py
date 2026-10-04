"""Western North Pacific tropical storms and typhoons since 1951, one item per storm at its
peak, as items of the typhoons feed, from the Japan Meteorological Agency's RSMC Tokyo best
track data (public, credited to JMA).

    curl -O https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/Besttracks/bst_all.zip
    research/.venv/bin/python research/public/typhoon_history.py bst_all.zip OUT.jsonl
"""

from __future__ import annotations

import json
import sys
import zipfile
from datetime import datetime

PAGE = "https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/besttrack.html"
STORM = "https://agora.ex.nii.ac.jp/digital-typhoon/summary/wnp/s/{year}{number}.html.en"
# Rough boxes (south, north, west, east) for "passed near"; a track point of tropical storm
# strength or more inside one counts.
PLACES = {
    "the Philippines": (5.0, 19.5, 117.0, 126.5),
    "Taiwan": (21.8, 25.4, 119.9, 122.1),
    "Okinawa": (24.0, 28.5, 123.0, 131.0),
    "Japan": (30.0, 45.6, 129.5, 146.0),
    "South Korea": (33.0, 38.6, 125.0, 129.6),
    "Vietnam": (8.5, 22.0, 102.0, 109.5),
    "Hong Kong": (21.8, 22.8, 113.5, 114.6),
    "southern China": (20.0, 27.0, 108.5, 120.0),
    "eastern China": (27.0, 38.0, 117.0, 123.0),
    "Guam": (12.9, 14.0, 144.2, 145.4),
}
GRADES = {3: "Tropical storm", 4: "Severe tropical storm", 5: "Typhoon"}


def _year(two: str) -> int:
    return 1900 + int(two) if int(two) >= 50 else 2000 + int(two)


def _listed(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _day(when: datetime) -> str:
    return f"{when.day} {when:%B %Y}"


def storms(text: str):
    """Each storm: its number, name and track points (time, grade, lat, lon, hPa, knots)."""
    storm = None
    for line in text.splitlines():
        if line.startswith("66666"):
            if storm:
                yield storm
            storm = {"number": line[6:10], "name": line[30:50].strip().title(), "track": []}
        elif storm is not None and line.strip():
            parts = line.split()
            stamp = parts[0]
            when = datetime(_year(stamp[:2]), int(stamp[2:4]), int(stamp[4:6]), int(stamp[6:8]))
            wind = int(parts[6]) if len(parts) > 6 and parts[6].isdigit() else 0
            storm["track"].append(
                (when, int(parts[2]), int(parts[3]) / 10, int(parts[4]) / 10, int(parts[5]), wind)
            )
    if storm:
        yield storm


def item(storm: dict) -> dict | None:
    strong = [p for p in storm["track"] if p[1] in GRADES]
    if not strong:
        return None
    grade = max(p[1] for p in strong)
    peak = min(strong, key=lambda p: (p[4], -p[5]))  # lowest pressure, then strongest wind
    wind = max(p[5] for p in strong)
    year = strong[0][0].year
    kind = GRADES[grade]
    name = f"{kind} {storm['name']}" if storm["name"] else f"{kind} {storm['number']}"
    near = [
        place
        for place, (south, north, west, east) in PLACES.items()
        if any(south <= p[2] <= north and west <= p[3] <= east for p in strong)
    ]
    peak_text = f"{wind}-knot winds and {peak[4]} hPa" if wind else f"{peak[4]} hPa"
    title = f"{name} ({year}) peaked at {peak_text}"
    if near:
        title += ", passing near " + _listed(near[:3])
    first, last = strong[0][0], strong[-1][0]
    summary = (
        f"{name}, number {storm['number']} of the western North Pacific season, was a "
        f"tropical storm or stronger from {_day(first)} to {_day(last)}. At its peak on "
        f"{_day(peak[0])} near {peak[2]:.1f}N {peak[3]:.1f}E it had "
        + (f"maximum sustained winds of {wind} knots and " if wind else "")
        + f"a central pressure of {peak[4]} hPa."
        + (f" Its track passed near {_listed(near)}." if near else "")
        + " Japan Meteorological Agency, RSMC Tokyo best track data."
    )
    return {
        "feed": "typhoons",
        "title": title,
        "summary": summary,
        "link": STORM.format(year=year, number=storm["number"][2:]),
        "date": peak[0].strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main(source: str, out: str) -> None:
    with zipfile.ZipFile(source) as archive:
        text = archive.read(archive.namelist()[0]).decode("ascii", "replace")
    found = [i for i in map(item, storms(text)) if i]
    with open(out, "w", encoding="utf-8") as lines:
        for entry in found:
            lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(len(found), "storms")


if __name__ == "__main__":
    main(*sys.argv[1:3])
