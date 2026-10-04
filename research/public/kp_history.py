"""Strong geomagnetic storms since 1932 (G3 or more on NOAA's scale: the planetary Kp index
reaching 7- or more), one item a day, as items of the space-weather feed, from GFZ Potsdam's Kp
index (CC BY 4.0; Matzka et al. 2021, doi:10.1029/2020SW002641).

    curl -L -O https://kp.gfz.de/app/files/Kp_ap_since_1932.txt
    research/.venv/bin/python research/public/kp_history.py Kp_ap_since_1932.txt OUT.jsonl
"""

from __future__ import annotations

import json
import sys
from datetime import date

SCALE = ((8.667, "G5", "extreme"), (7.667, "G4", "severe"), (6.667, "G3", "strong"))
LINK = "https://kp.gfz.de/en/"


def kp_text(value: float) -> str:
    thirds = round(value * 3)
    whole = (thirds + 1) // 3
    return f"{whole}{ {-1: '-', 0: '', 1: '+'}[thirds - whole * 3] }"


def main(source: str, out: str) -> None:
    days: dict[date, list[tuple[float, int, int]]] = {}
    with open(source, encoding="ascii") as text:
        rows = text.read().splitlines()
    for line in rows:
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        day = date(int(parts[0]), int(parts[1]), int(parts[2]))
        days.setdefault(day, []).append((float(parts[7]), int(float(parts[3])), int(parts[8])))
    written = 0
    with open(out, "w", encoding="utf-8") as lines:
        for day, readings in sorted(days.items()):
            kp, hour, _ = max(readings)
            level = next(((g, word) for low, g, word in SCALE if kp >= low - 0.001), None)
            if level is None:
                continue
            article = "an" if level[1] == "extreme" else "a"
            ap = round(sum(r[2] for r in readings) / len(readings))
            when = f"{day.day} {day:%B %Y}"
            entry = {
                "feed": "space-weather",
                "title": f"Geomagnetic storm {level[0]} ({level[1]}) on {when}: Kp reached "
                f"{kp_text(kp)}",
                "summary": f"Solar storm: the planetary Kp index reached {kp_text(kp)} at "
                f"{hour:02d}:00-{hour + 3:02d}:00 UTC on {when}, {article} {level[1]} "
                "geomagnetic storm "
                f"({level[0]} on NOAA's scale); daily Ap {ap}. Kp index from GFZ Potsdam "
                "(CC BY 4.0, Matzka et al. 2021).",
                "link": LINK,
                "date": f"{day.isoformat()}T{hour:02d}:00:00Z",
            }
            lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
            written += 1
    print(written, "storm days")


if __name__ == "__main__":
    main(*sys.argv[1:3])
