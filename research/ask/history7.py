"""Build 7's new examples, questions about the past, from a catalog snapshot with its archive;
build 7 is build 6's examples plus these.

    research/.venv/bin/python research/ask/history7.py SNAPSHOT research/ask/data-history7
    research/.venv/bin/python research/ask/history7.py --merge research/ask/data-decide6 \\
        research/ask/data-history7 research/ask/data-decide7
"""

from __future__ import annotations

import collections
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build


def make(snapshot: str, out: str) -> None:
    past = build.history_items(snapshot)
    described = json.loads((Path(snapshot) / "feeds.json").read_text(encoding="utf-8"))["feeds"]
    feeds = [f for f in described if f.get("name") in {i["feed"] for i in past}]
    world = build.World(past, feeds)
    builder = build.Builder(world, seed=7, decide=True)
    sample = [" ".join(builder.keywords(i, 2) or ["x"]) for i in past[::997]]
    for year in ("2019", "2023", "2025"):
        world.check_period(sample[:40], f"{year}-01", f"{year}-12-31T23:59:59Z")
    made = build.build_history(builder, past, build.HISTORY_PER_FEED)
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    for name, examples in made.items():
        with (folder / f"{name}.jsonl").open("w", encoding="utf-8") as lines:
            for example in examples:
                lines.write(json.dumps(example, ensure_ascii=False) + "\n")
        kinds = collections.Counter(e["kind"] for e in examples)
        print(f"{name}: {len(examples)} examples {dict(kinds)}")


def merge(first: str, second: str, out: str) -> None:
    rng = random.Random(7)
    folder = Path(out)
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("train", "test"):
        rows = [
            line
            for part in (first, second)
            for line in (Path(part) / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        rng.shuffle(rows)
        (folder / f"{name}.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
        print(name, len(rows))


if __name__ == "__main__":
    if sys.argv[1] == "--merge":
        merge(*sys.argv[2:5])
    else:
        make(*sys.argv[1:3])
