"""Pick (k, L) for the semantic lock from data, not from arithmetic.

Two rates decide it, and they are not symmetric:

  TRUE  collision rate -- same-fact pairs that share a bucket. A miss here means
                          two agents write the same fact. This is corruption.
  FALSE collision rate -- different-fact pairs that share a bucket. A hit here
                          means two unrelated agents serialise briefly. This is
                          only latency.

So the target is true >= 0.99 with false as low as that allows. Anything that
trades true-rate for speed is trading correctness for speed.

Run:  uv run python experiments/probe_lsh.py
"""

from __future__ import annotations

import itertools
import sys, os

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from retract.lsh import DIM  # noqa: E402

PARAPHRASE_SPREAD = 0.02   # matches the observed 0.46-0.54 L2 for same-fact pairs
FACTS = 40
PARAPHRASES = 8


def make_corpus(seed: int = 3) -> list[list[np.ndarray]]:
    rng = np.random.default_rng(seed)
    corpus = []
    for _ in range(FACTS):
        base = rng.normal(size=DIM)
        base /= np.linalg.norm(base)
        group = []
        for _ in range(PARAPHRASES):
            v = base + rng.normal(scale=PARAPHRASE_SPREAD, size=DIM)
            group.append(v / np.linalg.norm(v))
        corpus.append(group)
    return corpus


def rates(corpus, k: int, L: int, seed: int = 20260812) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    planes = rng.normal(size=(L, k, DIM))
    weights = (1 << np.arange(k - 1, -1, -1)).astype(np.int64)
    offsets = np.arange(L, dtype=np.int64) * (1 << k)

    def sig(v):
        bits = (planes @ v) > 0
        return set(int(x) for x in ((bits * weights).sum(axis=1) + offsets))

    sigs = [[sig(v) for v in group] for group in corpus]

    same_hit = same_n = 0
    for group in sigs:
        for a, b in itertools.combinations(group, 2):
            same_n += 1
            same_hit += bool(a & b)

    diff_hit = diff_n = 0
    for gi, gj in itertools.combinations(range(len(sigs)), 2):
        for a in sigs[gi][:3]:
            for b in sigs[gj][:3]:
                diff_n += 1
                diff_hit += bool(a & b)

    return same_hit / same_n, diff_hit / diff_n


def main() -> int:
    corpus = make_corpus()
    d_same = [float(np.linalg.norm(g[0] - g[1])) for g in corpus]
    d_diff = [float(np.linalg.norm(corpus[i][0] - corpus[j][0]))
              for i, j in itertools.combinations(range(len(corpus)), 2)]
    print(f"geometry: same-fact L2 mean {np.mean(d_same):.3f} | "
          f"different-fact L2 mean {np.mean(d_diff):.3f}")
    print(f"suggested dup_threshold (midpoint): {(max(d_same) + min(d_diff)) / 2:.2f}\n")

    print(f"{'k':>3} {'L':>4} {'locks':>6} {'TRUE':>8} {'FALSE':>8}   verdict")
    best = None
    for k in (6, 8, 10, 12):
        for L in (4, 8, 16, 32):
            t, f = rates(corpus, k, L)
            ok = t >= 0.99
            if ok and (best is None or f < best[3] or (f == best[3] and L < best[1])):
                best = (k, L, t, f)
            print(f"{k:>3} {L:>4} {L:>6} {t:>7.1%} {f:>8.1%}   {'ok' if ok else 'MISSES DUPLICATES'}")

    print()
    if best:
        k, L, t, f = best
        print(f"CHOSEN: BITS_PER_TABLE={k}, NUM_TABLES={L}")
        print(f"  true collision {t:.1%} (duplicates caught), false {f:.1%} (needless waits)")
        print(f"  cost: {L} lock rows per commit")
    else:
        print("NO CONFIGURATION REACHES 99% TRUE COLLISION.")
        print("Do not ship the lock on this geometry -- widen the search or change approach.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
