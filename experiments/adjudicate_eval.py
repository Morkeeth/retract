"""Does the adjudicator actually separate paraphrase from contradiction?

The whole design rests on this: embedding distance provably cannot make this
call, so something else must. If the adjudicator cannot either, RETRACT surfaces
noise instead of signal and the product does not work.

The cases are fixed here with their expected verdicts, written from the TASK --
what a competent human reviewer would say -- not from whatever the adjudicator
happens to output. Each case also carries the measured L2 distance so the report
shows the thing distance gets wrong.

Run:  RETRACT_ADJUDICATOR=heuristic uv run python experiments/adjudicate_eval.py
      RETRACT_ADJUDICATOR=bedrock   uv run python experiments/adjudicate_eval.py
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from retract.adjudicate import get_adjudicator  # noqa: E402
from retract.embed import get_embedder  # noqa: E402

SUBJ, PRED = "customer:4471", "identity_verified"

# (incumbent, challenger, expected, why it is hard)
CASES = [
    # --- true paraphrases: must be 'duplicate' ---
    ("Customer 4471 has verified their identity via passport.",
     "ID verification complete for customer 4471 (passport).",
     "duplicate", "same fact, reworded"),
    ("Customer 4471 has verified their identity via passport.",
     "Cust 4471 identity confirmed, passport on file.",
     "duplicate", "same fact, abbreviated"),
    ("Customer 4471: identity verified.",
     "Identity of customer 4471 established via passport.",
     "duplicate", "same fact, more detail"),

    # --- real changes: must NOT be 'duplicate' ---
    ("Customer 4471 has verified their identity via passport.",
     "Customer 4471 FAILED identity verification via passport.",
     "not-duplicate", "negation; distance 0.532, closer than some paraphrases"),
    ("The refund of $1,240 to customer 4471 was approved.",
     "The refund of $1,240 to customer 4471 was declined.",
     "not-duplicate", "approved vs declined"),
    ("The refund of $1,240 to customer 4471 was approved.",
     "The refund of $2,140 to customer 4471 was approved.",
     "not-duplicate", "digits transposed; distance 0.317"),
    ("Customer 9902 lives in Berlin.",
     "Customer 9902 used to live in Berlin.",
     "not-duplicate", "tense; distance 0.296, BELOW the paraphrase minimum"),
    ("Customer 4471 has verified their identity via passport.",
     "Customer 4471 has verified their identity via driving licence.",
     "not-duplicate", "same outcome, different evidence"),
]


def main() -> int:
    adj = get_adjudicator()
    emb = get_embedder(os.environ.get("RETRACT_EMBEDDER", "local"))
    print(f"adjudicator: {adj.name}")
    print(f"is a model:  {adj.is_model}")
    if not adj.is_model:
        print("NOTE: this is a stand-in, not reasoning. Results below are not a")
        print("      claim about the product's adjudication quality.")
    print()

    passed = 0
    for incumbent, challenger, expected, why in CASES:
        d = float(np.linalg.norm(emb.embed(incumbent) - emb.embed(challenger)))
        v = adj.judge(SUBJ, PRED, incumbent, challenger)
        ok = (v.resolution == "duplicate") if expected == "duplicate" else (v.resolution != "duplicate")
        passed += ok
        print(f"  {'PASS' if ok else 'FAIL'}  L2={d:.3f}  expected={expected:<13} got={v.resolution:<11} {why}")
        if not ok:
            print(f"          reasoning: {v.reasoning}")

    print(f"\n{passed}/{len(CASES)} correct")
    if passed == len(CASES):
        print("Adjudication separates the cases distance cannot.")
    else:
        print("Adjudication is NOT reliable on these cases. Do not claim it is.")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
