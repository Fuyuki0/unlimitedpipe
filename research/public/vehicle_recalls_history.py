"""Every NHTSA vehicle and equipment recall campaign as items of the vehicle-recalls feed, with
its titles, from the Department of Transportation's open data (public domain).

    research/.venv/bin/python research/public/vehicle_recalls_history.py OUT.jsonl
"""

from __future__ import annotations

import json
import sys
import time

import httpx

API = "https://data.transportation.gov/resource/6axg-epim.json"
AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
PAGE = 5000


def affected(value: object) -> str:
    try:
        return f" ({int(float(str(value))):,} affected)"
    except ValueError:
        return ""


def main(out: str) -> None:
    written, offset = 0, 0
    with open(out, "w", encoding="utf-8") as lines:
        while True:
            response = httpx.get(
                API,
                params={"$order": "report_received_date", "$limit": PAGE, "$offset": offset},
                headers=AGENT,
                timeout=120,
            )
            response.raise_for_status()
            rows = response.json()
            if not rows:
                break
            for row in rows:
                if not (row.get("report_received_date") and row.get("subject")):
                    continue
                item = {
                    "feed": "vehicle-recalls",
                    "title": f"{row.get('manufacturer')}: {row['subject']}"
                    + affected(row.get("potentially_affected")),
                    "summary": row.get("defect_summary") or "",
                    "link": (row.get("recall_link") or {}).get("url"),
                    "date": row["report_received_date"] + "Z",
                }
                lines.write(json.dumps(item, ensure_ascii=False) + "\n")
                written += 1
            offset += len(rows)
            time.sleep(1)
    print(written, "recalls")


if __name__ == "__main__":
    main(sys.argv[1])
