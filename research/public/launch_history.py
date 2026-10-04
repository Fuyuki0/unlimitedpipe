"""Every past orbital launch attempt since 1957, as items of the space-launches feed, from The
Space Devs' Launch Library 2 (free API, 15 requests an hour without a key: about 5 hours).

    research/.venv/bin/python research/public/launch_history.py OUT.jsonl
"""

from __future__ import annotations

import json
import sys
import time

import httpx

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
FIRST = "https://ll.thespacedevs.com/2.3.0/launches/previous/?limit=100&mode=normal&ordering=net"
PAUSE = 245  # seconds between requests: under 15 an hour


def item(launch: dict) -> dict:
    net = launch.get("net") or ""
    status = (launch.get("status") or {}).get("name") or "status unknown"
    provider = (launch.get("launch_service_provider") or {}).get("name")
    pad = launch.get("pad") or {}
    place = ", ".join(p for p in (pad.get("name"), (pad.get("location") or {}).get("name")) if p)
    mission = launch.get("mission") or {}
    orbit = (mission.get("orbit") or {}).get("name")
    parts = [f"Launched {net[:16].replace('T', ' ')} UTC"]
    if provider:
        parts.append(f"by {provider}")
    if place:
        parts.append(f"from {place}")
    summary = " ".join(parts) + f": {status}."
    if mission.get("type") or orbit:
        summary += " Mission: " + ", ".join(p for p in (mission.get("type"), orbit) if p) + "."
    return {
        "feed": "space-launches",
        "title": launch["name"],
        "summary": summary + " Launch Library 2 (The Space Devs).",
        "link": f"https://spacelaunchnow.app/launch/{launch['slug']}/",
        "date": net,
    }


def main(out: str) -> None:
    url, written = FIRST, 0
    with (
        httpx.Client(headers=AGENT, timeout=120) as http,
        open(out, "a", encoding="utf-8") as lines,
    ):
        while url:
            response = http.get(url)
            if response.status_code == 429:
                time.sleep(900)
                continue
            response.raise_for_status()
            document = response.json()
            for launch in document.get("results") or []:
                if launch.get("net") and launch.get("slug"):
                    lines.write(json.dumps(item(launch), ensure_ascii=False) + "\n")
                    written += 1
            lines.flush()
            print(written, "of", document.get("count"), url, flush=True)
            url = document.get("next")
            if url:
                time.sleep(PAUSE)
    print(written, "launches")


if __name__ == "__main__":
    main(sys.argv[1])
