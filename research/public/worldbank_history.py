"""Tenders in World Bank-financed projects (invitations for bids and requests for expressions
of interest), every one the World Bank's procurement notices API lists, as items of the
world-bank-tenders feed, written as the feed writes them.

    research/.venv/bin/python research/public/worldbank_history.py OUT.jsonl
"""

from __future__ import annotations

import json
import sys
import time

import httpx

AGENT = {"User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)"}
API = "https://search.worldbank.org/api/v2/procnotices"
KINDS = ("Invitation for Bids", "Request for Expression of Interest")
FIELDS = (
    "id,notice_type,noticedate,project_ctry_name,project_name,bid_description,submission_date,"
    "submission_deadline_date"
)
ROWS = 500


def main(out: str) -> None:
    written = 0
    with (
        httpx.Client(headers=AGENT, timeout=120) as http,
        open(out, "w", encoding="utf-8") as lines,
    ):
        for kind in KINDS:
            offset = 0
            while True:
                params = {"format": "json", "rows": ROWS, "os": offset, "srt": "noticedate",
                          "order": "desc", "notice_type_exact": kind, "fl": FIELDS}  # fmt: skip
                for attempt in range(5):
                    try:
                        response = http.get(API, params=params)
                        if response.status_code < 500:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(20 * (attempt + 1))
                response.raise_for_status()
                notices = response.json().get("procnotices") or []
                for notice in notices:
                    what = " ".join(str(notice.get("bid_description") or "").split())
                    if not (what and notice.get("submission_date") and notice.get("id")):
                        continue
                    deadline = str(notice.get("submission_deadline_date") or "")[:10]
                    entry = {
                        "feed": "world-bank-tenders",
                        "title": f"{notice.get('project_ctry_name')}: {what}",
                        "summary": f"{notice.get('notice_type')} for the "
                        f"{notice.get('project_name')} project. Deadline: {deadline}.",
                        "link": "https://projects.worldbank.org/en/projects-operations/"
                        f"procurement-detail/{notice['id']}",
                        "date": notice["submission_date"][:19] + "Z",
                    }
                    lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    written += 1
                print(kind, offset, len(notices), flush=True)
                if len(notices) < ROWS:
                    break
                offset += ROWS
                time.sleep(1)
    print(written, "tenders")


if __name__ == "__main__":
    main(sys.argv[1])
