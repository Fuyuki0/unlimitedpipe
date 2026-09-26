"""Word meanings learned by a fruit-fly circuit, against ordinary word vectors.

Liang et al. ("Can a Fruit Fly Learn Word Embeddings?", ICLR 2021) fed a mushroom body a word
with its neighbours, and let its Kenyon cells compete: for each window of text, only the
most excited cell learns, moving its connections towards that window (a local rule, no
backpropagation). A word's meaning is then the few cells it excites most: a sparse binary
code, cheap to store and compare.

Here the circuit learns from public-domain Federal Register text, and is compared with
ordinary word vectors from the same text (co-occurrence counts, reweighted with PPMI and
compressed with SVD) on:

1. nearest words for probe words (to read);
2. usefulness: the 41-feed task from `experiment.py`, with each item as the average of its
   words' vectors, and a learned readout.

    research/.venv/bin/python research/fly/words.py FR_FOLDER research/data
"""

from __future__ import annotations

import collections
import io
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
from scipy import sparse
from sklearn.decomposition import TruncatedSVD
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import corpus  # noqa: E402

VOCAB, WINDOW, CELLS, TOP = 20000, 5, 400, 25  # as in the paper: 400 cells, a 25-cell code
WORD = re.compile(r"[a-z][a-z'-]+")
PROBES = ("tariff", "aircraft", "pesticide", "medicare", "sanctions", "wildlife", "bank",
          "hurricane", "vaccine", "bitcoin", "oil", "court")


def read_texts(folder: Path, words_limit: int):
    import zstandard

    total = 0
    for path in sorted(folder.glob("federal-register-*.jsonl.zst")):
        with path.open("rb") as raw:
            for line in io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(raw),
                                         encoding="utf-8"):
                tokens = WORD.findall(json.loads(line)["text"].lower())
                total += len(tokens)
                yield tokens
                if total >= words_limit:
                    return


def vocabulary(documents):
    counts = collections.Counter()
    for tokens in documents:
        counts.update(tokens)
    words = [w for w, _ in counts.most_common(VOCAB)]
    return {w: i for i, w in enumerate(words)}, np.array([counts[w] for w in words], float)


def id_arrays(documents, index):
    for tokens in documents:
        ids = np.fromiter((index.get(t, -1) for t in tokens), dtype=np.int64, count=len(tokens))
        if len(ids) > 2 * WINDOW:
            yield ids


def window_batches(docs, index, batch):
    """Batches of (contexts, targets): for every known word, the WINDOW word ids on each side
    (-1 for unknown words)."""
    from numpy.lib.stride_tricks import sliding_window_view

    contexts, targets, size = [], [], 0
    for ids in id_arrays(docs(), index):
        win = sliding_window_view(ids, 2 * WINDOW + 1)
        keep = win[:, WINDOW] >= 0
        contexts.append(np.delete(win[keep], WINDOW, axis=1))
        targets.append(win[keep, WINDOW])
        size += int(keep.sum())
        if size >= batch:
            c, t = np.concatenate(contexts), np.concatenate(targets)
            for i in range(0, len(t), batch):
                yield c[i:i + batch], t[i:i + batch]
            contexts, targets, size = [], [], 0
    if size:
        yield np.concatenate(contexts), np.concatenate(targets)


def train_fly(docs, index, freq, epochs=2, batch=2000, rate=0.05, seed=0):
    """Mushroom body over [context words ; target word], with the paper's local rule: for each
    window v (divided by word frequency), only the most excited cell mu learns,
    dW_mu = rate * (v - <W_mu, v> W_mu). Applied per batch as the sum of each window's own
    update (all computed with the batch's starting weights), with the rate falling to zero."""
    rng = np.random.default_rng(seed)
    v = len(index)
    weights = rng.normal(size=(CELLS, 2 * v)).astype(np.float32)
    weights /= np.linalg.norm(weights, axis=1, keepdims=True)
    scale = freq.mean() / freq  # rare words count more; 1 for a word of average frequency
    scale = np.concatenate([scale, scale]).astype(np.float32)
    total = sum(len(t) for t in docs()) * epochs
    seen = 0
    for _ in range(epochs):
        for contexts, targets in window_batches(docs, index, batch):
            n = len(targets)
            rows = np.repeat(np.arange(n), contexts.shape[1])
            cols = contexts.ravel()
            known = cols >= 0
            rows = np.concatenate([rows[known], np.arange(n)])
            cols = np.concatenate([cols[known], v + targets])
            x = sparse.csr_matrix((scale[cols], (rows, cols)), shape=(n, 2 * v))
            drive = np.asarray(x @ weights.T)
            winner = drive.argmax(1)
            step = rate * max(0.0, 1 - seen / total) / n
            for cell in np.unique(winner):
                mine = winner == cell
                pull = np.asarray(x[mine].sum(0)).ravel()
                weights[cell] += step * (pull - drive[mine, cell].sum() * weights[cell])
            seen += n
    return weights, seen


def fly_codes(weights, v):
    """A word's code: the TOP cells its target half excites most (a 400-bit code)."""
    drive = weights[:, v:].T  # each word alone, as the target
    codes = np.zeros_like(drive)
    top = np.argpartition(-drive, TOP, axis=1)[:, :TOP]
    np.put_along_axis(codes, top, 1.0, axis=1)
    return codes


def ppmi_svd(docs, index, dims=300):
    """Ordinary word vectors: co-occurrence counts, PPMI, compressed by SVD."""
    v = len(index)
    m = sparse.csr_matrix((v, v), dtype=np.float32)
    rows, cols = [], []
    for ids in id_arrays(docs(), index):
        for offset in range(1, WINDOW + 1):
            a, b = ids[:-offset], ids[offset:]
            both = (a >= 0) & (b >= 0)
            rows += [a[both], b[both]]
            cols += [b[both], a[both]]
        if sum(len(r) for r in rows) > 5_000_000:
            r, c = np.concatenate(rows), np.concatenate(cols)
            m = m + sparse.csr_matrix((np.ones(len(r), np.float32), (r, c)), shape=(v, v))
            rows, cols = [], []
    if rows:
        r, c = np.concatenate(rows), np.concatenate(cols)
        m = m + sparse.csr_matrix((np.ones(len(r), np.float32), (r, c)), shape=(v, v))
    total = m.sum()
    row, col = np.asarray(m.sum(1)).ravel(), np.asarray(m.sum(0)).ravel()
    m = m.tocoo()
    pmi = np.log(m.data * total / (row[m.row] * col[m.col] + 1e-9))
    keep = pmi > 0
    ppmi = sparse.csr_matrix((pmi[keep], (m.row[keep], m.col[keep])), shape=(v, v))
    return TruncatedSVD(dims, random_state=0).fit_transform(ppmi)


def nearest(vectors, index, word, k=6):
    if word not in index:
        return "-"
    words = list(index)
    unit = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-9)
    sims = unit @ unit[index[word]]
    order = [i for i in np.argsort(-sims) if i != index[word]][:k]
    return ", ".join(words[i] for i in order)


def feeds_task(vectors, index, catalog):
    items = corpus.load(catalog)
    counts = collections.Counter(i["feed"] for i in items)
    items = [i for i in items if counts[i["feed"]] >= 30]
    labels = np.array([i["feed"] for i in items])
    x = np.zeros((len(items), vectors.shape[1]), np.float32)
    for n, item in enumerate(items):
        ids = [index[t] for t in WORD.findall(f"{item['title']} {item['summary']}".lower())
               if t in index]
        if ids:
            x[n] = vectors[ids].mean(0)
    train, test = train_test_split(np.arange(len(items)), test_size=0.25, random_state=0,
                                   stratify=labels)
    model = LogisticRegression(max_iter=3000).fit(x[train], labels[train])
    return float(np.mean(model.predict(x[test]) == labels[test]))


def main(fr_folder: str, catalog: str, words_limit: int = 20_000_000) -> None:
    folder = Path(fr_folder)
    docs = lambda: read_texts(folder, words_limit)  # noqa: E731
    start = time.time()
    index, freq = vocabulary(docs())
    total = sum(len(t) for t in docs())
    print(f"{total:,} words of Federal Register text, vocabulary {len(index):,}")
    weights, seen = train_fly(docs, index, freq)
    fly = fly_codes(weights, len(index))
    print(f"fly: {seen:,} windows learned in {time.time() - start:.0f} s")
    start = time.time()
    ordinary = ppmi_svd(docs, index)
    print(f"ordinary (PPMI + SVD, 300 dims): {time.time() - start:.0f} s\n")
    print("Nearest words")
    for word in PROBES:
        print(f"  {word:10} fly:      {nearest(fly, index, word)}")
        print(f"  {'':10} ordinary: {nearest(ordinary, index, word)}")



if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "research/data",
         int(sys.argv[3]) if len(sys.argv) > 3 else 20_000_000)
