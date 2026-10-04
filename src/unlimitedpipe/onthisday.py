"""On this day: for each day of the year, the biggest events of that date in a site's archive,
across every year it holds, written as one small JSON file per day (on-this-day/10-04.json)
and a page that shows today's (on-this-day.html).

Only plainly big events are kept: earthquakes of magnitude 7 or more, category 4 and 5
hurricanes, typhoons of 120 knots or more, eruptions of VEI 4 or more, extreme solar storms,
hacks of $100M or more, breaches of 100M accounts or more, Fed rate decisions, Hacker News
stories of 2,500 points or more, and the world's events that killed 100 or more or were about
$1B or more.
"""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path
from typing import Any

from unlimitedpipe.archive import _month_files, _text, lines_of
from unlimitedpipe.sources.ask import notable_size, size_of

FOLDER = "on-this-day"
PAGE = "on-this-day.html"
PER_DAY = 60
_DATE = re.compile(r"^\d{4}-(\d\d)-(\d\d)")
_VEI = re.compile(r"VEI (\d)")
_POINTS = re.compile(r"^(\d+) points")
WIKIPEDIA = "From Wikipedia's"


def notable(item: dict[str, Any]) -> bool:
    """Whether an archive item is a big enough event for the day's page."""
    feed = str(item.get("feed") or "")
    title = str(item.get("title") or "")
    summary = str(item.get("summary") or "")
    if feed == "world-events" or (feed.endswith("-news") and WIKIPEDIA in summary):
        return (notable_size(title) or 0) >= 1e9  # 100 deaths (at $10M each), or $1B
    if feed == "earthquakes":
        return (notable_size(title) or 0) >= 7.0
    if feed == "hurricanes":
        return "Category 4" in title or "Category 5" in title
    if feed == "typhoons":
        return (size_of(title) or 0) >= 120
    if feed == "volcanoes":
        match = _VEI.search(title)
        return bool(match) and int(match[1]) >= 4
    if feed == "space-weather":
        return title.startswith("Geomagnetic storm G5")
    if feed == "crypto-hacks":
        return (notable_size(title) or 0) >= 100e6
    if feed == "data-breaches":
        return (size_of(title) or 0) >= 100e6
    if feed == "fed-funds-target":
        return True
    if feed == "hn-top":
        match = _POINTS.match(summary)
        return bool(match) and int(match[1]) >= 2500
    return False


def build(site: Path) -> int:
    """Write a file for each day of the year that has events; returns how many."""
    days: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for path in _month_files(site / "archive"):
        for line in lines_of(_text(path)):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            date = str(item.get("date") or "")
            match = _DATE.match(date)
            if not match or not notable(item):
                continue
            days[f"{match[1]}-{match[2]}"].append(
                {k: item.get(k) for k in ("title", "link", "date", "feed")}
            )
    folder = site / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    for day, items in days.items():
        # the newest first; at most PER_DAY, keeping every kind of event in
        items.sort(key=lambda i: str(i["date"]), reverse=True)
        kept = items[:PER_DAY]
        text = json.dumps({"day": day, "items": kept}, ensure_ascii=False, indent=0)
        target = folder / f"{day}.json"
        if not target.exists() or target.read_text(encoding="utf-8") != text:
            target.write_text(text, encoding="utf-8")
    return len(days)


def page(title: str, style: str) -> str:
    """The page that shows a day's events, today's by default (the reader's own date)."""
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>On this day</title>
    <meta name="description" content="The biggest events of this date in past years, from {title}.">
    <style>{style}
      .day {{ display: flex; gap: .5rem; align-items: center; flex-wrap: wrap; margin: 1rem 0; }}
      .day button, .day input {{ font: inherit; padding: .35rem .7rem; border-radius: .5rem;
        border: 1px solid var(--line); background: var(--card); color: var(--ink); }}
      .year {{ margin-top: 1.4rem; }}
      .year h2 {{ font-size: 1.05rem; margin: 0 0 .4rem; }}
      .event {{ margin: .3rem 0; line-height: 1.45; }}
      .event a {{ color: var(--ink); }}
      .event small {{ color: var(--muted); }}
    </style>
  </head>
  <body>
    <div class="wrap">
    <header class="top"><a class="brand" href="./">{title}</a>
      <nav><a href="./">All feeds</a></nav></header>
    <section class="hero">
      <h1 id="heading">On this day</h1>
      <p class="lede">The biggest events of this date in past years: great earthquakes and
        storms, deadly disasters and conflicts, record hacks, rate decisions. Each links to its
        source.</p>
      <div class="day"><button id="prev" type="button">← Day before</button>
        <input id="pick" type="date" aria-label="Pick a day">
        <button id="next" type="button">Day after →</button></div>
      <div id="events"><p>Loading…</p></div>
    </section>
    </div>
    <script>
      const names = {{"world-events": "World", "earthquakes": "Earthquake",
        "hurricanes": "Hurricane", "typhoons": "Typhoon", "volcanoes": "Eruption",
        "space-weather": "Solar storm",
        "crypto-hacks": "Crypto hack", "data-breaches": "Data breach",
        "fed-funds-target": "Federal Reserve", "hn-top": "Hacker News"}};
      const months = ["January", "February", "March", "April", "May", "June", "July", "August",
        "September", "October", "November", "December"];
      const pick = document.getElementById("pick");
      let shown = new Date();
      const pad = (n) => String(n).padStart(2, "0");
      const label = (feed) =>
        names[feed] || String(feed || "").replace(/-news$/, "").replace(/-/g, " ");
      const esc = (t) => String(t ?? "").replace(/[&<>"]/g,
        (c) => ({{"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}}[c]));
      async function show(date) {{
        shown = date;
        const key = `${{pad(date.getMonth() + 1)}}-${{pad(date.getDate())}}`;
        pick.value = `${{date.getFullYear()}}-${{key}}`;
        document.getElementById("heading").textContent =
          `On this day: ${{date.getDate()}} ${{months[date.getMonth()]}}`;
        const box = document.getElementById("events");
        let items = [];
        try {{
          const answer = await fetch(`{FOLDER}/${{key}}.json`);
          if (answer.ok) items = (await answer.json()).items || [];
        }} catch (e) {{}}
        if (!items.length) {{
          box.innerHTML = "<p>Nothing big on this date in the archive yet.</p>";
          return;
        }}
        const years = {{}};
        for (const item of items) (years[item.date.slice(0, 4)] ||= []).push(item);
        box.innerHTML = Object.keys(years).sort().reverse().map((year) =>
          `<div class="year"><h2>${{year}}</h2>` + years[year].map((i) =>
            `<p class="event"><small>${{esc(label(i.feed))}}</small> ` +
            `<a href="${{esc(i.link)}}">${{esc(i.title)}}</a></p>`).join("") + "</div>").join("");
      }}
      const shift = (days) => {{
        const d = new Date(shown);
        d.setDate(d.getDate() + days);
        show(d);
      }};
      document.getElementById("prev").onclick = () => shift(-1);
      document.getElementById("next").onclick = () => shift(1);
      pick.onchange = () => {{ if (pick.value) show(new Date(pick.value + "T12:00:00")); }};
      const asked = new URLSearchParams(location.search).get("day");
      const valid = asked && /^\\d\\d-\\d\\d$/.test(asked);
      show(valid ? new Date(`2000-${{asked}}T12:00:00`) : new Date());
    </script>
  </body>
</html>
"""
