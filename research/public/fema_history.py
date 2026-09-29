"""Every US federal disaster declaration since 1953 as items of the us-disasters feed, with its
titles, from OpenFEMA (public domain).

    research/.venv/bin/python research/public/fema_history.py OUT.jsonl
"""

from __future__ import annotations

import json
import sys
import time

import httpx

from unlimitedpipe.names import readable_name

API = "https://www.fema.gov/api/open/v1/FemaWebDisasterDeclarations"
AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
KIND = {"Major Disaster": "Major disaster", "Fire Management": "Fire management"}
CODE = {"Major Disaster": "DR", "Emergency": "EM", "Fire Management": "FM"}


def item(row: dict) -> dict | None:
    declared = row.get("declarationDate")
    kind_of = row.get("declarationType")
    if not (declared and kind_of in CODE and row.get("disasterNumber")):
        return None
    kind = KIND.get(kind_of, kind_of)
    number = row["disasterNumber"]
    return {
        "feed": "us-disasters",
        "title": f"{kind} declared: {readable_name(row.get('disasterName') or '')}, "
        f"{row.get('stateName')} ({CODE[kind_of]}-{number})",
        "summary": f"FEMA {kind.lower()} declaration for {row.get('stateName')} "
        f"({str(row.get('incidentType') or '').lower()}), declared {declared[:10]}.",
        "link": f"https://www.fema.gov/disaster/{number}",
        "date": declared,
    }


def main(out: str) -> None:
    written, skip = 0, 0
    with open(out, "w", encoding="utf-8") as lines:
        while True:
            response = httpx.get(
                API,
                params={"$orderby": "declarationDate", "$top": 1000, "$skip": skip},
                headers=AGENT,
                timeout=120,
            )
            response.raise_for_status()
            rows = response.json().get("FemaWebDisasterDeclarations", [])
            if not rows:
                break
            for row in rows:
                if entry := item(row):
                    lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    written += 1
            skip += len(rows)
            time.sleep(1)
    print(written, "declarations")


if __name__ == "__main__":
    main(sys.argv[1])
