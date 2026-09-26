"""Does a fruit-fly mushroom body help understand news items?

The fly's mushroom body turns ~50 smell inputs into a sparse code over ~2,000 Kenyon cells:
each cell sums a handful of random inputs, and only the most active few percent fire. Its
output neurons then learn which codes matter. Dasgupta, Stevens and Navlakha (Science, 2017)
showed the same circuit works as a similarity search ("FlyHash").

Here the same circuit reads UnlimitedPipe's catalog, against ordinary text models, on three
tasks with the same train/test split:

1. Which feed does an unseen item come from? (a learned readout, like the output neurons)
2. Nearest neighbours: do an item's most similar items come from its feed? (no learning)
3. Duplicates: is the same story from another feed its nearest neighbour?

    research/.venv/bin/python research/fly/experiment.py research/data
"""

from __future__ import annotations

import collections
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import corpus  # noqa: E402

INPUTS = 100  # the fly has ~50 projection neurons per side; 100 dense inputs here


def mushroom_body(x: np.ndarray, cells: int, fan_in: int, active: float, seed: int = 1):
    """Kenyon cells: each sums `fan_in` random inputs; only the top `active` share fires."""
    rng = np.random.default_rng(seed)
    wiring = np.zeros((x.shape[1], cells), dtype=np.float32)
    for cell in range(cells):
        wiring[rng.choice(x.shape[1], fan_in, replace=False), cell] = 1
    drive = x.astype(np.float32) @ wiring
    k = max(1, int(cells * active))
    winners = np.argpartition(-drive, k, axis=1)[:, :k]
    code = np.zeros_like(drive)
    np.put_along_axis(code, winners, 1.0, axis=1)
    return code


def unit(rows: np.ndarray) -> np.ndarray:
    return rows / (np.linalg.norm(rows, axis=1, keepdims=True) + 1e-9)


def neighbours(queries: np.ndarray, pool: np.ndarray, k: int) -> tuple[np.ndarray, float]:
    """The k most similar pool rows for each query (cosine), and the seconds it took."""
    start = time.perf_counter()
    sims = unit(queries) @ unit(pool).T
    top = np.argpartition(-sims, k, axis=1)[:, :k]
    return top, time.perf_counter() - start


def main(folder: str) -> None:
    items = corpus.load(folder)
    counts = collections.Counter(i["feed"] for i in items)
    items = [i for i in items if counts[i["feed"]] >= 30]  # feeds with enough examples
    texts = [f"{i['title']} {i['summary']}" for i in items]
    labels = np.array([i["feed"] for i in items])
    train, test = train_test_split(
        np.arange(len(items)), test_size=0.25, random_state=0, stratify=labels
    )
    feeds = len(set(labels))
    print(f"{len(items)} items from {feeds} feeds; {len(train)} to learn from, {len(test)} to test")
    biggest = collections.Counter(labels[test]).most_common(1)[0][1] / len(test)
    print(f"guessing the biggest feed: {biggest:.1%}\n")

    tfidf = TfidfVectorizer(max_features=20000, sublinear_tf=True)
    words = tfidf.fit_transform([texts[i] for i in train])
    all_words = tfidf.transform(texts)
    svd = TruncatedSVD(INPUTS, random_state=0).fit(words)
    dense = svd.transform(all_words)
    dense = (dense - dense[train].mean(0)) / (dense[train].std(0) + 1e-9)

    def readout(features, c=1.0):
        model = LogisticRegression(max_iter=3000, C=c).fit(features[train], labels[train])
        return float(np.mean(model.predict(features[test]) == labels[test]))

    def knn(features, k=5):
        pool = features[train]
        top, secs = neighbours(features[test], pool, k)
        votes = [collections.Counter(labels[train][row]).most_common(1)[0][0] for row in top]
        return float(np.mean(np.array(votes) == labels[test])), secs

    rows = []
    rows.append(("Words (TF-IDF), readout", readout(all_words, 10), all_words.shape[1] * feeds))
    rows.append((f"{INPUTS} inputs, readout (no fly)", readout(dense), INPUTS * feeds))
    best = None
    sweep = []
    for cells, fan_in, active in [
        (2000, 6, 0.05),
        (2000, 6, 0.10),
        (5000, 6, 0.05),
        (10000, 6, 0.02),
        (10000, 12, 0.05),
        (20000, 6, 0.05),
    ]:
        code = mushroom_body(dense, cells, fan_in, active)
        accuracy = readout(code)
        near, secs = knn(code)
        sweep.append((cells, fan_in, active, accuracy, near, secs))
        if best is None or accuracy > best[3]:
            best = (cells, fan_in, active, accuracy, near, secs, code)
    cells, fan_in, active, accuracy, _, _, best_code = best
    rows.append((f"Fly ({cells:,} cells), readout", accuracy, cells * feeds))

    print(f"1. Which feed? ({feeds} feeds)")
    print(f"   {'model':34} {'accuracy':>8} {'learned params':>15}")
    for name, acc, params in rows:
        print(f"   {name:34} {acc:8.1%} {params:15,}")

    word_knn, word_secs = knn(all_words.toarray())
    dense_knn, dense_secs = knn(dense)
    fly_knn, fly_secs = knn(best_code)
    word_bytes = all_words.nnz / len(items) * 8  # a stored weight and its index per word
    print("\n2. Nearest neighbours (no learning)")
    print(f"   {'model':34} {'accuracy':>8} {'search s':>9} {'bytes/item':>11}")
    print(f"   {'Words (TF-IDF)':34} {word_knn:8.1%} {word_secs:9.2f} {word_bytes:11.0f}")
    print(f"   {f'{INPUTS} inputs':34} {dense_knn:8.1%} {dense_secs:9.2f} {INPUTS * 4:11.0f}")
    print(f"   {'Fly code (bits)':34} {fly_knn:8.1%} {fly_secs:9.2f} {cells / 8:11.0f}")

    print("\n   Fly sizes tried:")
    print(f"   {'cells':>7} {'fan-in':>6} {'active':>6} {'readout':>8} {'neighbours':>10}")
    for cells_, fan, act, acc, near, _ in sweep:
        print(f"   {cells_:7,} {fan:6} {act:6.0%} {acc:8.1%} {near:10.1%}")

    by_link = collections.defaultdict(list)
    for index, item in enumerate(items):
        if item["link"]:
            by_link[item["link"]].append(index)
    pairs = [
        group[:2]
        for group in by_link.values()
        if len(group) > 1 and items[group[0]]["feed"] != items[group[1]]["feed"]
    ]
    print(f"\n3. Duplicates: {len(pairs)} stories listed by two feeds; is the other copy nearest?")
    for name, features in [
        ("Words (TF-IDF)", all_words.toarray()),
        (f"{INPUTS} inputs", dense),
        ("Fly code", best_code),
    ]:
        hits = 0
        for a, b in pairs:
            sims = unit(features[[a]]) @ unit(features).T
            sims[0, a] = -np.inf
            hits += int(np.argmax(sims) == b)
        print(f"   {name:34} {hits}/{len(pairs)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "research/data")
