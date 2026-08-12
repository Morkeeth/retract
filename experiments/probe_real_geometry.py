"""Re-validate the lock parameters against REAL embeddings.

BITS_PER_TABLE, NUM_TABLES and dup_threshold were tuned on synthetic vectors --
a base direction plus Gaussian noise. Real sentence embeddings are not shaped
like that. Paraphrases of one fact sit much closer together than synthetic noise
suggests, and unrelated sentences sit much closer than random unit vectors do,
because a language model's output occupies a narrow cone of the sphere.

If the real same-fact and different-fact distributions OVERLAP, no distance
threshold can carry deduplication -- which is exactly what this measures, on
whichever embedder is configured.

This measures the real thing, on paraphrase groups and on adversarially SIMILAR
but genuinely different facts -- same customer, same topic, different claim --
which is the case that actually breaks a naive threshold.
"""

from __future__ import annotations

import itertools
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from retract.embed import get_embedder  # noqa: E402

# Same fact, different words. These MUST collide.
GROUPS = [
    [
        "Customer 4471 has verified their identity via passport.",
        "ID verification complete for customer 4471 (passport).",
        "Cust 4471 identity confirmed, passport on file.",
        "Passport check passed for customer 4471.",
        "Customer 4471: identity verified.",
    ],
    [
        "The refund of $1,240 to customer 4471 was approved.",
        "Approved a $1,240 refund for cust 4471.",
        "Customer 4471 refund ($1,240) has been authorised.",
        "$1,240 refund granted to customer 4471.",
    ],
    [
        "Customer 9902 lives in Berlin.",
        "Cust 9902 is based in Berlin, Germany.",
        "9902's address is in Berlin.",
        "The customer 9902 resides in Berlin.",
    ],
]

# The hard cases: near-identical wording, DIFFERENT fact. These must NOT collide.
# A threshold that cannot separate these is worse than no dedup at all -- it
# silently merges "verified" with "failed verification".
ADVERSARIAL = [
    ("Customer 4471 has verified their identity via passport.",
     "Customer 4471 FAILED identity verification via passport."),
    ("Customer 4471 has verified their identity via passport.",
     "Customer 4472 has verified their identity via passport."),
    ("The refund of $1,240 to customer 4471 was approved.",
     "The refund of $1,240 to customer 4471 was declined."),
    ("The refund of $1,240 to customer 4471 was approved.",
     "The refund of $2,140 to customer 4471 was approved."),
    ("Customer 9902 lives in Berlin.",
     "Customer 9902 used to live in Berlin."),
]


def main() -> int:
    emb = get_embedder(os.environ.get("RETRACT_EMBEDDER", "local"))
    print(f"embedder: {emb.name}\n")

    vecs = [emb.embed_many(g) for g in GROUPS]

    same = [float(np.linalg.norm(a - b))
            for g in vecs for a, b in itertools.combinations(g, 2)]
    diff = [float(np.linalg.norm(a - b))
            for gi, gj in itertools.combinations(range(len(vecs)), 2)
            for a in vecs[gi] for b in vecs[gj]]
    adv = [(x, y, float(np.linalg.norm(emb.embed(x) - emb.embed(y)))) for x, y in ADVERSARIAL]

    print(f"SAME fact      n={len(same):3d}  min {min(same):.3f}  mean {np.mean(same):.3f}  MAX {max(same):.3f}")
    print(f"DIFFERENT fact n={len(diff):3d}  MIN {min(diff):.3f}  mean {np.mean(diff):.3f}  max {max(diff):.3f}")
    print(f"\nADVERSARIAL pairs (same words, different fact) -- these must stay ABOVE threshold:")
    for x, y, d in sorted(adv, key=lambda t: t[2]):
        print(f"  {d:.3f}  {x[:44]:<44} || {y[:44]}")

    adv_min = min(d for _, _, d in adv)
    print(f"\nseparation: same-fact max {max(same):.3f} | adversarial min {adv_min:.3f} | different-fact min {min(diff):.3f}")

    ceiling = min(adv_min, min(diff))
    if max(same) >= ceiling:
        print("\nOVERLAP. No single threshold separates same-fact from different-fact.")
        print("A distance cutoff cannot carry dedup on this geometry -- do not ship one.")
        thresh = None
    else:
        thresh = (max(same) + ceiling) / 2
        print(f"\nSAFE THRESHOLD: {thresh:.2f}   (margin below {ceiling:.3f}, above {max(same):.3f})")

    if thresh:
        print(f"CHOSEN dup_threshold: {thresh:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
