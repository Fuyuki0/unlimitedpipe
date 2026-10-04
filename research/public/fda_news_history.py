"""FDA press announcements from the FDA newsroom's listing pages, as items of the fda-news
feed (works of the US government). Thirty seconds between pages, as fda.gov asks of crawlers.

    research/.venv/bin/python research/public/fda_news_history.py OUT.jsonl
"""

from __future__ import annotations

import json
import sys
import time

import httpx
from bs4 import BeautifulSoup

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
LIST = "https://www.fda.gov/news-events/fda-newsroom/press-announcements?page={page}"
PAUSE = 30


def main(out: str) -> None:
    written, page = 0, 0
    with (
        httpx.Client(headers=AGENT, timeout=60) as http,
        open(out, "w", encoding="utf-8") as lines,
    ):
        while True:
            response = http.get(LIST.format(page=page))
            response.raise_for_status()
            found = 0
            for link in BeautifulSoup(response.text, "lxml").select(
                'a[href^="/news-events/press-announcements/"]'
            ):
                stamp = link.find("time")
                if stamp is None:
                    continue
                stamp.extract()
                title = " ".join(link.get_text().split()).lstrip("- ").strip()
                if not title:
                    continue
                entry = {
                    "feed": "fda-news",
                    "title": title,
                    "summary": "",
                    "link": "https://www.fda.gov" + str(link["href"]),
                    "date": str(stamp["datetime"])[:19] + "Z",
                }
                lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
                found += 1
            written += found
            print(page, found, flush=True)
            if not found:
                break
            page += 1
            time.sleep(PAUSE)
    print(written, "announcements")


if __name__ == "__main__":
    main(sys.argv[1])
