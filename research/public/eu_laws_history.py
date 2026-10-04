"""EU regulations, directives and decisions (delegated and implementing acts included, merger
clearances left out) month by month, as items of the eu-laws feed, from the EU Publications
Office's public SPARQL endpoint (EUR-Lex metadata, reuse authorised with the source named).

    research/.venv/bin/python research/public/eu_laws_history.py OUT.jsonl 1990-01 2026-09
"""

from __future__ import annotations

import calendar
import json
import re
import sys
import time

import httpx

AGENT = {
    "User-Agent": "UnlimitedPipe (+https://github.com/Fuyuki0/unlimitedpipe)",
    "Accept": "application/sparql-results+json",
}
ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
TYPES = ["REG", "DIR", "DEC", "REG_IMPL", "DEC_IMPL", "REG_DEL", "DIR_IMPL", "DIR_DEL", "DEC_DEL"]
AUTHORITY = "http://publications.europa.eu/resource/authority"
QUERY = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?celex ?date ?title WHERE {{
  ?work cdm:resource_legal_id_celex ?celex ;
        cdm:work_date_document ?date ;
        cdm:work_has_resource-type ?type .
  FILTER(?type IN ({types}))
  FILTER(?date >= "{start}"^^xsd:date && ?date <= "{end}"^^xsd:date)
  ?expr cdm:expression_belongs_to_work ?work ;
        cdm:expression_title ?title ;
        cdm:expression_uses_language <{authority}/language/ENG> .
}}"""
ACT = re.compile(r"^3\d{4}[RLD]\d+$")  # regulations (R), directives (L), decisions (D)


def main(out: str, first: str, last: str) -> None:
    types = ", ".join(f"<{AUTHORITY}/resource-type/{t}>" for t in TYPES)
    year, month = map(int, first.split("-"))
    end = tuple(map(int, last.split("-")))
    written = 0
    with (
        httpx.Client(headers=AGENT, timeout=180) as http,
        open(out, "w", encoding="utf-8") as lines,
    ):
        while (year, month) <= end:
            days = calendar.monthrange(year, month)[1]
            query = QUERY.format(
                types=types,
                start=f"{year}-{month:02d}-01",
                end=f"{year}-{month:02d}-{days}",
                authority=AUTHORITY,
            )
            for attempt in range(5):
                try:
                    response = http.post(ENDPOINT, data={"query": query})
                    if response.status_code < 500 and response.status_code != 429:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(20 * (attempt + 1))
            response.raise_for_status()
            seen, count = set(), 0
            for row in response.json()["results"]["bindings"]:
                celex = row["celex"]["value"]
                if not ACT.match(celex) or celex in seen:
                    continue
                seen.add(celex)
                title = " ".join(row["title"]["value"].split())
                if re.search(r"(?i)corrigendum|rectificatif", title):
                    continue
                short = re.sub(r"^(.{200}[^ ,]*)[ ,].+$", r"\1…", title)
                entry = {
                    "feed": "eu-laws",
                    "title": short,
                    "summary": title,
                    "link": f"https://eur-lex.europa.eu/legal-content/AUTO/?uri=CELEX:{celex}",
                    "date": row["date"]["value"][:10] + "T00:00:00Z",
                }
                lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
                count += 1
            written += count
            print(year, month, count, flush=True)
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
            time.sleep(1)
    print(written, "acts")


if __name__ == "__main__":
    main(*sys.argv[1:4])
