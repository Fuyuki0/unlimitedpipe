"""Historical tsunamis and volcanic eruptions from NOAA NCEI's hazards database (public domain),
as items of the tsunami-alerts and volcanoes feeds, since 1900. NCEI's robots.txt asks for a
minute between requests.

    research/.venv/bin/python research/public/ncei_history.py OUT.jsonl
"""

from __future__ import annotations

import json
import sys
import time

import httpx

API = "https://www.ngdc.noaa.gov/hazel/hazard-service/api/v1/{}"  # tsunamis/events, volcanoes
VIEW = "https://www.ngdc.noaa.gov/hazel/view/hazards/{}/event-more-info/{}"
AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
FIRST_YEAR = 1900
PAUSE = 61  # NCEI's Crawl-delay


def pages(kind: str):
    page = 1
    while True:
        response = httpx.get(
            API.format(kind),
            params={"minYear": FIRST_YEAR, "page": page},
            headers=AGENT,
            timeout=120,
        )
        response.raise_for_status()
        body = response.json()
        yield from body.get("items", [])
        if page >= int(body.get("totalPages") or 1):
            return
        page += 1
        time.sleep(PAUSE)


def day(event: dict) -> str | None:
    if not event.get("year"):
        return None
    return f"{event['year']:04d}-{event.get('month') or 1:02d}-{event.get('day') or 1:02d}"


def place(event: dict) -> str:
    name = (event.get("locationName") or event.get("name") or "").title()
    country = (event.get("country") or "").title()
    return ", ".join(part for part in (name, country) if part and part not in name)


def deaths(event: dict) -> str:
    total = event.get("deathsTotal") or event.get("deaths")
    return f", {int(total):,} deaths" if total else ""


def tsunami(event: dict) -> dict | None:
    when = day(event)
    if not when or (event.get("eventValidity") or 0) < 3:  # probable or definite only
        return None
    height = event.get("maxWaterHeight")
    size = f"waves up to {height:g} m" if height else "height unknown"
    cause = f" after an M{event['eqMagnitude']:g} earthquake" if event.get("eqMagnitude") else ""
    return {
        "feed": "tsunami-alerts",
        "title": f"Historical tsunami: {size}, {place(event)}{deaths(event)} ({when})",
        "summary": f"A tsunami on {when}{cause}, from NOAA NCEI's global historical tsunami "
        "database.",
        "link": VIEW.format("tsunami", event["id"]),
        "date": f"{when}T00:00:00Z",
    }


def eruption(event: dict) -> dict | None:
    when = day(event)
    if not when:
        return None
    vei = f"VEI {event['vei']}" if event.get("vei") is not None else "VEI unknown"
    return {
        "feed": "volcanoes",
        "title": f"Historical eruption: {vei}, {place(event)}{deaths(event)} ({when})",
        "summary": f"A significant volcanic eruption on {when}, from NOAA NCEI's significant "
        "volcanic eruptions database (VEI: the volcanic explosivity index, 0 to 8).",
        "link": VIEW.format("volcano", event["id"]),
        "date": f"{when}T00:00:00Z",
    }


def main(out: str, *kinds: str) -> None:
    with open(out, "w", encoding="utf-8") as lines:
        for kind, shape in (("tsunamis/events", tsunami), ("volcanoes", eruption)):
            if kinds and kind.split("/")[0] not in kinds:
                continue
            count = 0
            for event in pages(kind):
                if item := shape(event):
                    lines.write(json.dumps(item, ensure_ascii=False) + "\n")
                    count += 1
            print(kind, count, flush=True)
            time.sleep(PAUSE)


if __name__ == "__main__":
    main(sys.argv[1], *sys.argv[2:])  # optionally only: tsunamis, volcanoes
