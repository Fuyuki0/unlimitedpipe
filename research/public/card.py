"""Write the dataset card (README.md) of unlimitedpipe/public-records from its stats.json."""

from __future__ import annotations

import collections
import json
from pathlib import Path

from huggingface_hub import HfApi

REPO = "unlimitedpipe/public-records"
TOKENS_PER_WORD = 1.3  # a rough average for English text with common tokenizers

HEADER = """---
license: other
license_name: public-records
license_link: https://github.com/Fuyuki0/unlimitedpipe/tree/main/research/public
language: [en]
pretty_name: UnlimitedPipe public records
task_categories: [text-generation]
size_categories: [100K<n<1M]
configs:
- config_name: federal_register
  data_files: federal_register/*.parquet
- config_name: sec_10k
  data_files: sec_10k/*.parquet
---

# UnlimitedPipe public records

Public-domain and public-record text from official US government sources, collected through
their bulk-data front doors, with every document traceable to where it came from. Built by
[UnlimitedPipe](https://github.com/Fuyuki0/unlimitedpipe) (code in `research/public`).

| Part | Source | Documents | Words | About tokens |
| --- | --- | --- | --- | --- |
"""

FOOTER = """
## Fields

Every record keeps its provenance: `id`, `url` (the document's page), `source_url` (the bulk
file or document it was read from), `license`, `fetched_at`, and the text.

- **federal_register**: `id` (FR document number), `date`, `type` (rule, proposed rule, notice,
  presidential document), `agency`, `title`, `text`. One Parquet file per year.
- **sec_10k**: `id` (accession number), `cik`, `company`, `form`, `filed`, `text` (the main
  document of the annual report, without its hidden XBRL data). One file per quarter.

```python
from datasets import load_dataset
fr = load_dataset("unlimitedpipe/public-records", "federal_register", split="train", streaming=True)
```

## License and use

- The Federal Register is published by the US government; works of the US government are in
  the public domain in the United States.
- SEC filings are public records on EDGAR; the text of a 10-K is written by the filing
  company. They are shared here as public records for research, as other EDGAR corpora are.

## How it was collected

Federal Register: the monthly bulk files at govinfo.gov/bulkdata/FR (allowed by robots.txt).
SEC 10-K: EDGAR's quarterly form index, each filing's index page, and its main document, with
a declared contact and at most five requests a second (the SEC allows ten). Nothing behind a
login or a paywall.

## Limits

Text is extracted from XML and HTML: tables become lines of text, and some layout is lost.
Token counts are estimates (words x 1.3). Documents are as published; no filtering for
content beyond dropping near-empty ones.
"""


def main() -> None:
    api = HfApi()
    stats = json.loads(
        Path(api.hf_hub_download(REPO, "stats.json", repo_type="dataset")).read_text()
    )
    parts = collections.defaultdict(lambda: {"documents": 0, "words": 0, "keys": []})
    for key, counts in stats.items():
        part = parts[key.split("/")[0]]
        part["documents"] += counts["documents"]
        part["words"] += counts["words"]
        part["keys"].append(key.split("/")[1])
    sources = {
        "federal_register": "Federal Register (govinfo bulk data)",
        "sec_10k": "SEC Form 10-K annual reports (EDGAR)",
    }
    rows, total = [], {"documents": 0, "words": 0}
    for name, part in sorted(parts.items()):
        span = f"{min(part['keys'])} to {max(part['keys'])}"
        rows.append(
            f"| `{name}` ({span}) | {sources.get(name, name)} | {part['documents']:,} | "
            f"{part['words']:,} | {part['words'] * TOKENS_PER_WORD / 1e9:.2f} billion |"
        )
        total["documents"] += part["documents"]
        total["words"] += part["words"]
    rows.append(
        f"| **Total** | | **{total['documents']:,}** | **{total['words']:,}** | "
        f"**{total['words'] * TOKENS_PER_WORD / 1e9:.2f} billion** |"
    )
    card = HEADER + "\n".join(rows) + "\n" + FOOTER
    api.upload_file(
        path_or_fileobj=card.encode(),
        path_in_repo="README.md",
        repo_id=REPO,
        repo_type="dataset",
        commit_message="Dataset card",
    )
    print("\n".join(rows))


if __name__ == "__main__":
    main()
