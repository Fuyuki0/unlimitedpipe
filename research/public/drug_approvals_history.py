"""New molecular entities the FDA approved before 2022 (original NDAs of chemical type 1), as
items of the drug-approvals feed, from the Drugs@FDA data files (public domain). The feed's own
pages (novel drug approvals, with what each drug is for) cover 2022 on.

    curl -L -o drugsatfda.zip https://www.fda.gov/media/89850/download
    research/.venv/bin/python research/public/drug_approvals_history.py drugsatfda.zip OUT.jsonl
"""

from __future__ import annotations

import json
import sys
import zipfile

PAGE = "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo={}"
NEW_MOLECULE = {"7", "8"}  # Type 1, and Type 1/4


def _rows(archive: zipfile.ZipFile, name: str) -> list[list[str]]:
    lines = archive.read(name).decode("latin-1").splitlines()
    return [line.split("\t") for line in lines[1:]]


def _name(text: str) -> str:
    return " ".join(
        w.capitalize() if len(w) > 3 or not w.isalpha() else w.title() for w in text.split()
    )


def main(source: str, out: str) -> None:
    with zipfile.ZipFile(source) as archive:
        products: dict[str, tuple[str, str]] = {}
        for row in _rows(archive, "Products.txt"):
            products.setdefault(row[0], (row[5].strip(), row[6].strip()))
        applications = {row[0]: row for row in _rows(archive, "Applications.txt")}
        submissions = _rows(archive, "Submissions.txt")
    written = 0
    with open(out, "w", encoding="utf-8") as lines:
        for row in submissions:
            number, kind, submission, status, when = row[0], row[1], row[2], row[4], row[5]
            if kind not in NEW_MOLECULE or submission != "ORIG" or status != "AP":
                continue
            if not when or when[:4] >= "2022" or number not in products:
                continue
            drug, ingredient = products[number]
            name, ingredient = _name(drug), ingredient.lower()
            day = when[:10]
            application = applications.get(number) or ["", "NDA", "", ""]
            kind_of, sponsor = application[1].strip() or "NDA", _name(application[3].strip())
            entry = {
                "feed": "drug-approvals",
                "title": f"FDA approves {name} ({ingredient}), a new molecular entity",
                "summary": f"Novel drug approval of {day}: {name} ({ingredient}), {kind_of} "
                f"{number.lstrip('0')}"
                + (f" from {sponsor}" if sponsor else "")
                + ", a new molecular entity (Drugs@FDA).",
                "link": PAGE.format(number),
                "date": f"{day}T00:00:00Z",
            }
            lines.write(json.dumps(entry, ensure_ascii=False) + "\n")
            written += 1
    print(written, "approvals")


if __name__ == "__main__":
    main(*sys.argv[1:3])
