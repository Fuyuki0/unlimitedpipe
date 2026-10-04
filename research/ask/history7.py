"""Build 7's new examples, questions about the past, from a catalog snapshot with its archive;
build 7 is build 6's examples plus these.

    research/.venv/bin/python research/ask/history7.py SNAPSHOT research/ask/data-history7
    research/.venv/bin/python research/ask/history7.py --merge research/ask/data-decide6 \\
        research/ask/data-history7 research/ask/data-decide7

Build 8 adds the history of 2026-10-04 to build 7:
    research/.venv/bin/python research/ask/history7.py SNAPSHOT research/ask/data-history8 new
    research/.venv/bin/python research/ask/history7.py --merge research/ask/data-decide7 \\
        research/ask/data-history8 research/ask/data-decide8
"""

from __future__ import annotations

import collections
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build


def capped(items: list[dict], per_feed: int, seed: int = 7) -> list[dict]:
    """At most ``per_feed`` items of each feed (a sample of the larger ones), in date order."""
    rng = random.Random(seed)
    by_feed = collections.defaultdict(list)
    for item in items:
        by_feed[item["feed"]].append(item)
    kept = [i for group in by_feed.values() for i in rng.sample(group, min(per_feed, len(group)))]
    return sorted(kept, key=lambda i: i["date"])


def make(snapshot: str, out: str, only: str = "") -> None:
    """ONLY: "new" for build 8, the feeds whose history was added on 2026-10-04."""
    past = build.history_items(snapshot)
    if only == "new":
        past = [i for i in past if i["feed"] in build.NEW_HISTORY_FEEDS]
    past = capped(past, build.WORLD_PER_FEED)
    print(f"history world: {len(past)} items", flush=True)
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
        make(*sys.argv[1:4])
