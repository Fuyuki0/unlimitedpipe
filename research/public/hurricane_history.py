"""Atlantic (since 1851) and eastern and central Pacific (since 1949) tropical storms and
hurricanes, one item per storm at its peak, as items of the hurricanes feed, from the US
National Hurricane Center's best track data (HURDAT2; public domain). The NHC's server turns
this machine away, so the files are read from the Internet Archive's copies:

    https://web.archive.org/web/20260922070007id_/https://www.nhc.noaa.gov/data/hurdat/hurdat2-1851-2025-091226.txt
    https://web.archive.org/web/20260925023324id_/https://www.nhc.noaa.gov/data/hurdat/hurdat2-nepac-1949-2025-091426.txt

    research/.venv/bin/python research/public/hurricane_history.py OUT.jsonl HURDAT2.txt...
"""

from __future__ import annotations

import json
import sys
from datetime import datetime

BASINS = {"AL": "Atlantic", "EP": "eastern Pacific", "CP": "central Pacific"}
STRONG = {"TS", "HU", "SS"}  # tropical or subtropical storm strength or more
LINK = "https://www.nhc.noaa.gov/data/#hurdat"


def category(knots: int) -> int:
    """Saffir-Simpson category of a wind speed in knots (0 below hurricane strength)."""
    for low, number in ((137, 5), (113, 4), (96, 3), (83, 2), (64, 1)):
        if knots >= low:
            return number
    return 0


def storms(text: str):
    storm = None
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3 and parts[0][:2].isalpha() and len(parts[0]) == 8:
            if storm:
                yield storm
            storm = {"id": parts[0], "name": parts[1].title(), "track": []}
        elif storm is not None and len(parts) >= 8:
            when = datetime.strptime(parts[0] + parts[1], "%Y%m%d%H%M")
            storm["track"].append(
                (when, parts[2], parts[3], parts[4], parts[5], int(parts[6]), int(parts[7]))
            )
    if storm:
        yield storm


def item(storm: dict) -> dict | None:
    strong = [p for p in storm["track"] if p[2] in STRONG]
    if not strong:
        return None
    peak = max(strong, key=lambda p: (p[5], -(p[6] if p[6] > 0 else 9999)))
    wind = peak[5]
    pressures = [p[6] for p in strong if p[6] > 0]
    low = min(pressures) if pressures else None
    number = category(wind)
    kind = "Hurricane" if number else "Tropical storm"
    basin = BASINS.get(storm["id"][:2], "")
    year = int(storm["id"][4:])
    name = storm["name"] if storm["name"] != "Unnamed" else f"{storm['id'][2:4]} of {year}"
    landfalls = sum(1 for p in storm["track"] if p[1] == "L")
    size = f"Category {number}, " if number else ""
    title = f"{kind} {name} ({year}) peaked at {size}{wind}-knot winds" + (
        f" and {low} hPa" if low else ""
    )
    if landfalls:
        title += (
            f", making landfall {landfalls} times" if landfalls > 1 else ", making landfall once"
        )
    first, last = strong[0][0], strong[-1][0]
    summary = (
        f"{kind} {name}, {basin} storm {storm['id']}, was a tropical storm or stronger from "
        f"{first.day} {first:%B %Y} to {last.day} {last:%B %Y}. At its peak on "
        f"{peak[0].day} {peak[0]:%B %Y} near {peak[3]} {peak[4]} it had maximum sustained "
        f"winds of {wind} knots"
        + (f" and a lowest pressure of {low} hPa" if low else "")
        + "."
        + (f" Landfalls: {landfalls}." if landfalls else "")
        + " US National Hurricane Center best track (HURDAT2)."
    )
    return {
        "feed": "hurricanes",
        "title": title,
        "summary": summary,
        "link": LINK,
        "date": peak[0].strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def main(out: str, *files: str) -> None:
    written = 0
    with open(out, "w", encoding="utf-8") as lines:
        for file in files:
            with open(file, encoding="ascii", errors="replace") as text:
                for storm in storms(text.read()):
                    if entry := item(storm):
                        lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
                        written += 1
    print(written, "storms")


if __name__ == "__main__":
    main(*sys.argv[1:])
