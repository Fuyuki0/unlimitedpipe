"""Write examples/explore.ipynb for the Hugging Face dataset unlimitedpipe/feed-history: a few
questions the data answers in a few lines of pandas. Run it before publishing it:

    python research/public/make_example_notebook.py OUT.ipynb
    jupyter nbconvert --execute --to notebook OUT.ipynb
"""

from __future__ import annotations

import sys

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

CELLS = [
    new_markdown_cell(
        "# Exploring feed-history\n\n"
        "[unlimitedpipe/feed-history](https://huggingface.co/datasets/unlimitedpipe/feed-history) "
        "holds dated public-record events, each with a title, a summary and a link to the record "
        "at its official source, one Parquet file per feed. A few questions it answers in a few "
        "lines of pandas."
    ),
    new_code_cell(
        "import pandas as pd\n"
        "from huggingface_hub import hf_hub_download\n\n"
        "def feed(name):\n"
        '    """One feed\'s events, with their dates as dates."""\n'
        "    path = hf_hub_download(\"unlimitedpipe/feed-history\", f\"data/{name}.parquet\",\n"
        '                           repo_type="dataset")\n'
        "    frame = pd.read_parquet(path)\n"
        '    frame["date"] = pd.to_datetime(frame["date"], utc=True, format="ISO8601")\n'
        "    return frame\n\n"
        'quakes = feed("earthquakes")\n'
        "quakes.tail(3)"
    ),
    new_markdown_cell(
        "## Great earthquakes by decade\n\nTitles start with the magnitude (\"M 9.1 - ...\")."
    ),
    new_code_cell(
        'quakes["magnitude"] = quakes["title"].str.extract(r"^M ([\\d.]+)", expand=False).astype(float)\n'
        'great = quakes[quakes["magnitude"] >= 7]\n'
        'great.groupby(great["date"].dt.year // 10 * 10).size().plot.bar(\n'
        '    title="Earthquakes of magnitude 7 or more, by decade", xlabel="decade")'
    ),
    new_markdown_cell(
        "## Money lost to crypto hacks, by year\n\n"
        "Titles say how much was lost (\"Ronin Bridge: $624M lost (key compromise)\")."
    ),
    new_code_cell(
        'hacks = feed("crypto-hacks")\n'
        "scale = {\"K\": 1e3, \"M\": 1e6, \"B\": 1e9}\n"
        'amount = hacks["title"].str.extract(r"\\$([\\d.]+)([KMB])? lost")\n'
        'hacks["lost"] = amount[0].astype(float) * amount[1].map(scale).fillna(1)\n'
        'by_year = hacks.groupby(hacks["date"].dt.year)["lost"].sum() / 1e9\n'
        'by_year.plot.bar(title="Crypto hacks: billions of dollars lost a year", xlabel="year")'
    ),
    new_code_cell(
        '# the biggest ones\n'
        'hacks.nlargest(5, "lost")[["date", "title", "link"]]'
    ),
    new_markdown_cell(
        "## Insiders buying and selling\n\n"
        "Open-market trades of $100,000 or more by company insiders (SEC Form 4): "
        "\"... (CEO) bought 4,285 shares at $24.50 ...\"."
    ),
    new_code_cell(
        'trades = feed("insider-trades")\n'
        'trades["side"] = trades["title"].str.extract(r"\\) (bought|sold) ", expand=False)\n'
        'counts = trades.groupby([trades["date"].dt.year, "side"]).size().unstack()\n'
        'counts.plot(title="Insider trades of $100K+ a year", xlabel="year")'
    ),
    new_markdown_cell(
        "## Strong hurricanes by decade\n\n"
        "One item per storm, Atlantic since 1851 and eastern Pacific since 1949 (\"Hurricane "
        "Katrina (2005) peaked at Category 5, ...\"). Early decades are undercounted: before "
        "aircraft and satellites, many storms at sea were never measured."
    ),
    new_code_cell(
        'storms = feed("hurricanes")\n'
        'storms["category"] = storms["title"].str.extract(r"Category (\\d)", expand=False).astype(float)\n'
        'strong = storms[storms["category"] >= 4]\n'
        'strong.groupby(strong["date"].dt.year // 10 * 10).size().plot.bar(\n'
        '    title="Category 4 and 5 hurricanes, by decade", xlabel="decade")'
    ),
    new_markdown_cell(
        "Every row links to its source, so any number here can be checked against the record. "
        "Feeds keep what crosses their bar (earthquakes of magnitude 4.5 or more, insider trades "
        "of $100,000 or more): see the dataset card before comparing counts across decades."
    ),
]


def main(out: str) -> None:
    notebook = new_notebook(cells=CELLS)
    notebook.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3"}
    nbformat.write(notebook, out)


if __name__ == "__main__":
    main(sys.argv[1])
