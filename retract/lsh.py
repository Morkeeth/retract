"""Semantic bucketing by multi-table random-hyperplane LSH.

This is the load-bearing piece of RETRACT's concurrency control, and the reason
the design does not depend on vector-index internals (see FINDINGS.md).

A transaction cannot be held open across LLM inference -- an agent's "think"
step takes seconds to minutes. So we cannot lock the neighbourhood by reading
it. Instead the neighbourhood gets a NAME, and agents lock the name.

WHY MULTIPLE TABLES
The first version used a single 12-bit signature. It failed, measurably: eight
paraphrases of one fact landed in eight different buckets, many bits apart, so
eight agents took disjoint locks and all eight duplicates committed. Paraphrase
embeddings sit ~0.5 apart in L2 on the unit sphere, which is far enough to flip
several sign bits.

The fix is standard LSH amplification. L independent tables of k bits each; two
vectors collide if they agree in ANY table. An agent locks all L of its bucket
rows, so a collision in one table is enough to serialise the pair.

The asymmetry that sets the parameters:
  MISSED collision -> two agents both write the same fact -> corruption. Fatal.
  FALSE collision  -> two unrelated agents serialise briefly -> slower. Harmless.
So we bias hard toward more tables. `experiments/probe_lsh.py` measures the true
and false collision rates on real paraphrase geometry and picks (k, L) from data
rather than from the arithmetic.

Measured at k=8, L=32 on a 40-fact x 8-paraphrase corpus: 100% true collision,
12.9% false. Note what that 100% is and is not -- it is an observed rate on one
corpus, not a proof. LSH is probabilistic by construction. We report the rate
and let it be audited rather than calling it a guarantee.
"""

from __future__ import annotations

import numpy as np

DIM = 384
BITS_PER_TABLE = 8
NUM_TABLES = 32
PLANE_SEED = 20260812  # fixed forever: changing it re-partitions all memory


def _planes() -> np.ndarray:
    rng = np.random.default_rng(PLANE_SEED)
    return rng.normal(size=(NUM_TABLES, BITS_PER_TABLE, DIM))


PLANES = _planes()
_WEIGHTS = (1 << np.arange(BITS_PER_TABLE - 1, -1, -1)).astype(np.int64)


def buckets_of(embedding: np.ndarray) -> list[int]:
    """The L lock ids for this embedding, one per table.

    Table index is folded into the id so two tables cannot alias onto the same
    row: table t occupies the id range [t * 2^k, (t+1) * 2^k).
    """
    if embedding.shape != (DIM,):
        raise ValueError(f"expected shape ({DIM},), got {embedding.shape}")
    bits = (PLANES @ embedding) > 0                      # (L, k)
    sigs = (bits * _WEIGHTS).sum(axis=1)                 # (L,)
    offsets = np.arange(NUM_TABLES, dtype=np.int64) * (1 << BITS_PER_TABLE)
    return sorted(int(x) for x in (sigs + offsets))


def primary_bucket(embedding: np.ndarray) -> int:
    """One stable id for the row's own `bucket` column (table 0's signature)."""
    return buckets_of(embedding)[0]


def collides(a: np.ndarray, b: np.ndarray) -> bool:
    """True if a and b share at least one bucket -- i.e. they would serialise."""
    return bool(set(buckets_of(a)) & set(buckets_of(b)))
