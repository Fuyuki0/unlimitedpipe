"""Many small fly brains and one main network: accurate, cheap, and able to keep learning?

A brain is not one network: it is many specialised circuits, and only a few are active at a
time, which is how a human brain runs on about 20 watts. This tests that idea on the catalog:

- dense: one ordinary model over 100 inputs;
- one fly: a single 10,000-cell mushroom body with a learned readout;
- fly modules: a main network (the router) sends each item to one of 8 small flies
  (2,000 cells each), each trained only on the items routed to it;
- dense modules: the same router with 8 ordinary models, to see what the fly part adds.

Measured: accuracy on unseen items, the work per item (and the energy that work costs on a
chip), and continual learning: learning 11 new feeds after 30, without retraining on the
old ones, and how much of the old knowledge survives.

    research/.venv/bin/python research/fly/modules.py research/data
"""

from __future__ import annotations

import collections
import sys
import warnings
from pathlib import Path

import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402
from experiment import mushroom_body  # noqa: E402

warnings.filterwarnings("ignore")
INPUTS, MODULES = 100, 8
# Energy per operation on a 45 nm chip (Horowitz, ISSCC 2014): a 32-bit float multiply and
# add, against an 8-bit integer add, which is all a binary fly synapse needs.
PJ_FLOAT_MAC, PJ_INT_ADD = 3.7 + 0.9, 0.03
PJ_INT8_MAC = 0.2 + 0.03  # an 8-bit multiply and add


class FlyModule:
    """A small mushroom body with its own readout."""

    def __init__(self, cells: int, fan_in: int, seed: int) -> None:
        self.cells, self.fan_in, self.seed = cells, fan_in, seed
        self.readout = LogisticRegression(max_iter=2000, C=1)

    def code(self, x):
        return mushroom_body(x, self.cells, self.fan_in, 0.05, seed=self.seed)

    def fit(self, x, y):
        if len(set(y)) == 1:  # one feed only: nothing to choose
            self.only = y[0]
            return self
        self.only = None
        self.readout.fit(self.code(x), y)
        return self

    def predict(self, x):
        if self.only is not None:
            return np.array([self.only] * len(x))
        return self.readout.predict(self.code(x))

    def work(self, feeds: int) -> tuple[int, int]:
        """(integer adds, float multiply-adds) per item: each cell sums its inputs, and the
        readout adds up the weights of the 5% of cells that fire."""
        active = int(self.cells * 0.05)
        return self.cells * self.fan_in + active * feeds, 0


def routed(train_x, train_y, test_x, make, router: KMeans):
    """The main network picks one module per item; each module learns only its items."""
    lanes_train, lanes_test = router.predict(train_x), router.predict(test_x)
    prediction = np.empty(len(test_x), dtype=object)
    modules = {}
    for lane in range(router.n_clusters):
        mine = lanes_train == lane
        if not mine.any():
            continue
        modules[lane] = make(lane).fit(train_x[mine], train_y[mine])
        here = lanes_test == lane
        if here.any():
            prediction[here] = modules[lane].predict(test_x[here])
    empty = prediction == None  # noqa: E711 (items routed to a lane with no training items)
    prediction[empty] = collections.Counter(train_y).most_common(1)[0][0]
    return prediction, modules


class Dense:
    def __init__(self) -> None:
        self.model = LogisticRegression(max_iter=3000)

    def fit(self, x, y):
        self.only = y[0] if len(set(y)) == 1 else None
        if self.only is None:
            self.model.fit(x, y)
        return self

    def predict(self, x):
        return np.array([self.only] * len(x)) if self.only is not None else self.model.predict(x)


def main(folder: str) -> None:
    items = corpus.load(folder)
    counts = collections.Counter(i["feed"] for i in items)
    items = [i for i in items if counts[i["feed"]] >= 30]
    texts = [f"{i['title']} {i['summary']}" for i in items]
    labels = np.array([i["feed"] for i in items])
    train, test = train_test_split(
        np.arange(len(items)), test_size=0.25, random_state=0, stratify=labels
    )
    tfidf = TfidfVectorizer(max_features=20000, sublinear_tf=True).fit([texts[i] for i in train])
    svd = TruncatedSVD(INPUTS, random_state=0).fit(tfidf.transform([texts[i] for i in train]))
    x = svd.transform(tfidf.transform(texts))
    x = (x - x[train].mean(0)) / (x[train].std(0) + 1e-9)
    feeds = sorted(set(labels))
    n = len(feeds)
    xtr, xte, ytr, yte = x[train], x[test], labels[train], labels[test]
    router = KMeans(MODULES, n_init=5, random_state=0).fit(xtr)
    router_macs = INPUTS * MODULES

    def accuracy(prediction):
        return float(np.mean(prediction == yte))

    rows = []
    dense = LogisticRegression(max_iter=3000).fit(xtr, ytr)
    rows.append(("One ordinary model", accuracy(dense.predict(xte)), 0, INPUTS * n))
    # The same model on 8-bit integers (weights and inputs), as phones and chips run models.
    w_scale = np.abs(dense.coef_).max() / 127
    x_scale = np.abs(xtr).max() / 127
    w8 = np.round(dense.coef_ / w_scale).astype(np.int32)
    x8 = np.clip(np.round(xte / x_scale), -127, 127).astype(np.int32)
    scores = x8 @ w8.T + np.round(dense.intercept_ / (w_scale * x_scale)).astype(np.int32)
    int8_rows = (
        "One ordinary model, 8-bit",
        accuracy(dense.classes_[scores.argmax(1)]),
        INPUTS * n,
    )
    big = FlyModule(10000, 12, seed=1).fit(xtr, ytr)
    adds, _ = big.work(n)
    rows.append(("One big fly (10,000 cells)", accuracy(big.predict(xte)), adds, 0))
    prediction, _ = routed(xtr, ytr, xte, lambda lane: FlyModule(2000, 6, seed=10 + lane), router)
    adds, _ = FlyModule(2000, 6, 0).work(n)
    rows.append((f"Main network + {MODULES} small flies", accuracy(prediction), adds, router_macs))
    prediction, _ = routed(xtr, ytr, xte, lambda lane: Dense(), router)
    rows.append(
        (
            f"Main network + {MODULES} ordinary models",
            accuracy(prediction),
            0,
            router_macs + INPUTS * n,
        )
    )

    print(f"{len(items)} items, {n} feeds; energy per operation from Horowitz (ISSCC 2014)\n")
    print(f"{'model':38} {'accuracy':>8} {'int adds':>9} {'float MACs':>10} {'energy/item':>12}")
    for name, acc, adds, macs in rows:
        energy = adds * PJ_INT_ADD + macs * PJ_FLOAT_MAC
        print(f"{name:38} {acc:8.1%} {adds:9,} {macs:10,} {energy / 1000:9.1f} nJ")
    name, acc, macs8 = int8_rows
    print(
        f"{name:38} {acc:8.1%} {'':>9} {f'{macs8:,} int8':>10} {macs8 * PJ_INT8_MAC / 1000:9.1f} nJ"
    )

    # Continual learning: 30 feeds first, then 11 new ones, without the old items again.
    rng = np.random.default_rng(0)
    order = rng.permutation(feeds)
    old, new = set(order[:30]), set(order[30:])
    is_old_tr = np.isin(ytr, list(old))
    is_old_te = np.isin(yte, list(old))

    def old_and_new(predict):
        p = predict(xte)
        return float(np.mean(p[is_old_te] == yte[is_old_te])), float(
            np.mean(p[~is_old_te] == yte[~is_old_te])
        )

    print("\nKeep learning: 30 feeds first, then 11 new feeds without the old items")
    print(f"{'model':38} {'old feeds':>10} {'new feeds':>10}")
    sgd = SGDClassifier(loss="log_loss", random_state=0, max_iter=50, tol=None)
    sgd.partial_fit(xtr[is_old_tr], ytr[is_old_tr], classes=feeds)
    before = old_and_new(sgd.predict)[0]
    for _ in range(20):
        sgd.partial_fit(xtr[~is_old_tr], ytr[~is_old_tr])
    after = old_and_new(sgd.predict)
    print(f"{'One ordinary model (before new)':38} {before:10.1%} {'-':>10}")
    print(f"{'One ordinary model (after new)':38} {after[0]:10.1%} {after[1]:10.1%}")

    # Modules: the old router and flies stay as they are; the new feeds get new flies and
    # a new router lane each time a new item is closer to them than to the old lanes.
    old_router = KMeans(MODULES, n_init=5, random_state=0).fit(xtr[is_old_tr])
    new_router = KMeans(3, n_init=5, random_state=0).fit(xtr[~is_old_tr])
    centres = np.vstack([old_router.cluster_centers_, new_router.cluster_centers_])
    lanes_tr = np.argmin(((xtr[:, None, :] - centres[None]) ** 2).sum(-1), axis=1)
    lanes_te = np.argmin(((xte[:, None, :] - centres[None]) ** 2).sum(-1), axis=1)
    prediction = np.empty(len(xte), dtype=object)
    dense_prediction = np.empty(len(xte), dtype=object)
    for lane in range(len(centres)):
        taught = (lanes_tr == lane) & (is_old_tr if lane < MODULES else ~is_old_tr)
        here = lanes_te == lane
        if not here.any():
            continue
        if not taught.any():
            prediction[here] = dense_prediction[here] = collections.Counter(ytr).most_common(1)[0][
                0
            ]
            continue
        module = FlyModule(2000, 6, seed=10 + lane).fit(xtr[taught], ytr[taught])
        prediction[here] = module.predict(xte[here])
        dense_prediction[here] = Dense().fit(xtr[taught], ytr[taught]).predict(xte[here])
    for name, p in (
        ("Main network + fly modules", prediction),
        ("Main network + ordinary modules", dense_prediction),
    ):
        old_acc = float(np.mean(p[is_old_te] == yte[is_old_te]))
        new_acc = float(np.mean(p[~is_old_te] == yte[~is_old_te]))
        print(f"{name:38} {old_acc:10.1%} {new_acc:10.1%}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "research/data")
