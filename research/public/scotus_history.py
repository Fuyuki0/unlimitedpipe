"""Past Supreme Court opinions for the court-rulings feed's archive, from the Court's own
opinion lists (https://www.supremecourt.gov/opinions/slipopinion/23, one page per term): each
opinion with its date, docket, author and the one-sentence holding the Court gives it, titled
as the feed titles them ("Supreme Court: Corner Post, Inc. v. Board of Governors").

    research/.venv/bin/python research/public/scotus_history.py OUT.jsonl 17 18 19 ... 25
"""

from __future__ import annotations

import html
import json
import re
import sys
import time
from datetime import datetime

import httpx

TERM = "https://www.supremecourt.gov/opinions/slipopinion/{}"
AUTHORS = {
    "JR": "Chief Justice Roberts",
    "CT": "Justice Thomas",
    "SA": "Justice Alito",
    "SS": "Justice Sotomayor",
    "EK": "Justice Kagan",
    "NG": "Justice Gorsuch",
    "BK": "Justice Kavanaugh",
    "AB": "Justice Barrett",
    "KJ": "Justice Jackson",
    "KBJ": "Justice Jackson",
    "RG": "Justice Ginsburg",
    "SB": "Justice Breyer",
    "AK": "Justice Kennedy",
    "PC": "the Court (per curiam)",
    # Terms before 2020 name some justices by one letter.
    "R": "Chief Justice Roberts",
    "T": "Justice Thomas",
    "A": "Justice Alito",
    "B": "Justice Breyer",
    "G": "Justice Ginsburg",
    "K": "Justice Kennedy",
    "D": "the Court (decree)",
}
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)
LINK = re.compile(r"<a ([^>]*href='[^']+\.pdf(?:#[^']*)?'[^>]*)>(.*?)</a>", re.DOTALL)
HREF = re.compile(r"href='([^']+)'")
HOLDING = re.compile(r'title="([^"]*)"')


def text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def opinions(page: str) -> list[dict]:
    found = []
    for row in ROW.findall(page):
        cells = CELL.findall(row)
        link = LINK.search(row)
        if len(cells) < 5 or not link:
            continue
        try:
            day = datetime.strptime(text(cells[1]), "%m/%d/%y").strftime("%Y-%m-%d")
        except ValueError:
            continue
        docket, author = text(cells[2]), text(cells[4])
        citation = text(cells[5]) if len(cells) > 5 else ""
        attributes = link.group(1)
        holding = text(m.group(1)) if (m := HOLDING.search(attributes)) else ""
        by = AUTHORS.get(author, author)
        facts = f"No. {docket}, opinion by {by}" + (f"; {citation}" if citation else "")
        found.append(
            {
                "feed": "court-rulings",
                "title": f"Supreme Court: {text(link.group(2))}",
                "summary": (f"{holding} ({facts})." if holding else f"{facts}."),
                "link": "https://www.supremecourt.gov" + HREF.search(attributes).group(1),
                "date": f"{day}T00:00:00Z",
            }
        )
    return found


def main(out: str, terms: list[str]) -> None:
    with open(out, "w", encoding="utf-8") as lines:
        for term in terms:
            page = httpx.get(TERM.format(term), headers={"User-Agent": "UnlimitedPipe"}, timeout=60)
            page.raise_for_status()
            found = opinions(page.text)
            for item in found:
                lines.write(json.dumps(item, ensure_ascii=False) + "\n")
            print(term, len(found), "opinions")
            time.sleep(1.5)  # the Court's robots.txt asks for a second between requests


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
