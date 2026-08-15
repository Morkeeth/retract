"""BEFORE RETRACT vs AFTER RETRACT, measured on the same case.

Every other eval in this directory measures RETRACT against itself: does the
cascade hit the right rows, does the lock hold, does the reversal get written.
None of them answers the question the pitch actually makes, which is a
comparison:

    A wrong belief has already moved money. What does correcting it reach
    WITHOUT RETRACT, and what does it reach WITH RETRACT, on the same case?

Without that pair the claim is a description of a feature, not a measurement.

THE CONTROL ARM, AND WHY IT IS THE STRONG VERSION
-------------------------------------------------
Arm A is a MODEL of what a normal agent memory does when a stored fact turns
out to be false. It is not a run of a competitor product and this file will not
pretend otherwise. It is implemented as the single strongest thing such a
memory can do: mark the one belief that was found to be wrong as retracted.

That is deliberately generous. Most memory products expose `delete(id)`, which
is weaker -- it destroys the audit trail too. Arm A keeps the audit trail and
still does nothing about the derivations or the effects, because there is
nothing in a memory-only API that COULD: across the products surveyed in
RELATED-WORK.md, none attaches an action to a memory, so none has a handle on
the money. If the generous control leaves the wrong state standing, the weaker
one does too.

THREE TIERS, NOT TWO, BECAUSE THE LEDGER HAS THREE
---------------------------------------------------
Counting "reversed" as one number would repeat the overclaim commit 671be37
removed. On this branch a reversal is RECORDED (a request row, with its own
idempotency key, inside the same transaction) and never DISPATCHED, because no
payment provider is wired. So each arm is measured on all three:

    reached    the wrong belief's descendants and effects were found and stopped
    recorded   a reversal request exists, once, with an id
    settled    a provider was called and returned a receipt

WHAT IS ASSERTED, WRITTEN BEFORE THE ENGINE WAS OPENED
-------------------------------------------------------
Same five beliefs, same four effects, same cluster, same run, two scopes:

    1. derived beliefs still active after the correction   A: 3    B: 0
    2. pending effects still live (they will run)          A: 1    B: 0
    3. executed effects nobody reached                     A: 2    B: 0
    4. already-spent dollars with a reversal RECORDED      A: $0   B: $1,240
    5. already-spent dollars unreachable AND NAMED         A: $0   B: $89
    6. already-spent dollars SETTLED with a provider       A: $0   B: $0
    7. collateral damage to the unrelated customer 9902    A: 0    B: 0

Line 5 is not a win and is asserted anyway: `card_charge` has no registered
handler, so RETRACT reaches it, cannot reverse it, and says so. A run where the
$89 silently went green is a FAIL here.

Line 6 is $0 on BOTH arms and is the line most likely to be dropped by someone
quoting this file. It is the difference between a ledger and a bank.

Line 7 is the guard that stops the eval flattering itself: a cascade that
retracted everything would score perfectly on 1-3 and be worse than useless.

WHAT THIS NUMBER IS NOT
-----------------------
Architectural, not statistical. One scenario, deterministic, n=1. It says what
the two designs reach on this case; it does not say what fraction of real-world
wrong beliefs get reached, and no run of this file will ever say that.

BRANCH-SENSITIVE. On `origin/main` (0bcbaef, what the deployed demo serves as
of 15 Aug) `compensate()` marks the original `compensated` and the eval's
line 4/6 split does not exist there -- that branch reports the money reversed.
Commit 671be37 removed that claim. Run this on the branch you are quoting.

Run:  uv run python experiments/reach_eval.py        # needs CRDB_URL
      uv run python experiments/reach_eval.py --json
"""

from __future__ import annotations

import json
import os
import sys
import uuid

import numpy as np
import psycopg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from retract.embed import DIM  # noqa: E402
from retract.engine import MemoryEngine  # noqa: E402

# The scenario is the live demo's, copied from app/main.py:_story_events, so the
# number here and the number on camera describe the same five beliefs.
CHAIN = [
    ("Customer 4471 has verified their identity via passport.", "Customer 4471", "identity verified", None),
    ("Customer 4471 is eligible for instant refunds.", "Customer 4471", "refund eligibility", 0),
    ("Refund of $1,240 to customer 4471 is approved.", "Customer 4471", "refund approval", 1),
    ("Customer 4471 qualifies for priority support.", "Customer 4471", "support tier", 0),
    ("Customer 9902 has verified their identity.", "Customer 9902", "identity verified", None),
]
# (belief index, tool, idempotency key, status, label, dollars already spent)
EFFECTS = [
    (2, "refund_issued", "rf-4471-1240", "executed", "$1,240 sent to customer 4471", 1240),
    (2, "card_charge", "cc-4471-89", "executed", "$89 processed for customer 4471", 89),
    (3, "tier_upgrade", "tu-4471", "pending", "priority support queued", 0),
    (4, "welcome_email", "we-9902", "pending", "welcome email to customer 9902", 0),
]
DERIVED = (1, 2, 3)      # beliefs downstream of the forged passport
UNRELATED = 4            # customer 9902 -- must survive both arms
SPENT = sum(usd for _, _, _, s, _, usd in EFFECTS if s == "executed")


def unit(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=DIM)
    return v / np.linalg.norm(v)


def seed_case(url: str, tag: str):
    """Build the identical scenario in a fresh scope. Both arms call this."""
    scope = f"reach-{tag}-{uuid.uuid4().hex[:8]}"
    eng = MemoryEngine(url, scope, "support-agent")
    ids = []
    for i, (text, subj, pred, parent) in enumerate(CHAIN):
        eng.read(unit(i + 1))                       # READ phase, as a real turn would
        r = eng.commit(unit(i + 1), text, subj, pred,
                       derived_from=[ids[parent]] if parent is not None else ())
        if r.memory_id is None:
            raise RuntimeError(f"unexpected {r.outcome} seeding {text!r}")
        ids.append(r.memory_id)

    with psycopg.connect(url, autocommit=True) as c, c.cursor() as cur:
        for idx, tool, key, status, label, _usd in EFFECTS:
            cur.execute(
                "INSERT INTO effect (scope, justified_by, tool, payload, idempotency_key,"
                " status, executed_at) VALUES (%s,%s,%s,%s,%s,%s,"
                " CASE WHEN %s='executed' THEN now() END)",
                (scope, ids[idx], tool, json.dumps({"label": label}), key, status, status),
            )
    return scope, ids, eng


def observe(url: str, scope: str, ids: list) -> dict:
    """The same seven measurements, taken the same way, on both arms."""
    with psycopg.connect(url, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT id, status FROM memory WHERE scope=%s", (scope,))
        mem = dict(cur.fetchall())
        cur.execute("SELECT tool, status, idempotency_key FROM effect WHERE scope=%s", (scope,))
        rows = cur.fetchall()
    status_of = {t: s for t, s, _ in rows}
    keys = {k for _, _, k in rows}

    def usd_where(pred) -> int:
        return sum(usd for _, tool, key, st, _, usd in EFFECTS
                   if st == "executed" and pred(tool, key))

    return {
        "derived_still_active": sum(1 for i in DERIVED if mem[ids[i]] == "active"),
        "pending_still_live": sum(
            1 for _, tool, _, st, _, _ in EFFECTS
            if st == "pending" and tool != "welcome_email" and status_of.get(tool) == "pending"),
        "executed_unreached": sum(
            1 for _, tool, _, st, _, _ in EFFECTS
            if st == "executed" and status_of.get(tool) == "executed"),
        # A reversal REQUEST row exists under the derived idempotency key.
        "usd_reversal_recorded": usd_where(lambda t, k: f"comp:{k}" in keys),
        # Reached, flagged, and no handler can undo it. Named, not hidden.
        "usd_unreachable_named": usd_where(
            lambda t, k: status_of.get(t) == "needs_compensation" and f"comp:{k}" not in keys),
        # Only settle() with a provider receipt may produce this.
        "usd_settled": usd_where(lambda t, k: status_of.get(t) == "compensated"),
        "collateral_9902": 0 if (mem[ids[UNRELATED]] == "active"
                                 and status_of.get("welcome_email") == "pending") else 1,
        "_effects": status_of,
    }


def arm_a(url: str) -> dict:
    """Control: correct exactly the belief that was found to be wrong."""
    scope, ids, _ = seed_case(url, "naive")
    with psycopg.connect(url, autocommit=True) as c, c.cursor() as cur:
        cur.execute("UPDATE memory SET status='retracted' WHERE id=%s", (ids[0],))
    out = observe(url, scope, ids)
    out["_scope"] = scope
    out["_compensation_outcomes"] = {}
    return out


def arm_b(url: str) -> dict:
    """RETRACT: cascade, cancel, flag, then run compensation on what it flagged."""
    scope, ids, eng = seed_case(url, "retract")
    eng.retract(ids[0], "passport confirmed forged by fraud team")
    outcomes = {}
    with psycopg.connect(url, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT id, tool FROM effect WHERE scope=%s AND status='needs_compensation'",
                    (scope,))
        flagged = cur.fetchall()
    for eid, tool in flagged:
        outcomes[tool] = eng.compensate(eid).outcome
    out = observe(url, scope, ids)
    out["_scope"] = scope
    out["_compensation_outcomes"] = outcomes
    return out


CHECKS = [
    # (label, key, expected A, expected B, is_money)
    ("derived beliefs still active",          "derived_still_active",   3, 0, False),
    ("pending effects still live",            "pending_still_live",     1, 0, False),
    ("executed effects nobody reached",       "executed_unreached",     2, 0, False),
    ("spent $ with a reversal RECORDED",      "usd_reversal_recorded",  0, 1240, True),
    ("spent $ unreachable AND named",         "usd_unreachable_named",  0, 89, True),
    ("spent $ SETTLED with a provider",       "usd_settled",            0, 0, True),
    ("collateral damage to 9902",             "collateral_9902",        0, 0, False),
]


def main() -> int:
    url = os.environ.get("CRDB_URL")
    if not url:
        print("CRDB_URL is not set. This eval measures against a real cluster, "
              "because the claim is about what the database reaches.")
        return 2

    a, b = arm_a(url), arm_b(url)

    if "--json" in sys.argv:
        print(json.dumps({"arm_a_no_retract": a, "arm_b_retract": b},
                         indent=2, default=str))

    w = max(len(lbl) for lbl, *_ in CHECKS)
    print(f"\nsame case, same cluster, two scopes.")
    print(f"  A (no RETRACT) {a['_scope']}")
    print(f"  B (RETRACT)    {b['_scope']}\n")
    print(f"  {'':<{w}}   {'no RETRACT':>12} {'RETRACT':>10}")
    failed = []
    for lbl, key, exp_a, exp_b, money in CHECKS:
        got_a, got_b = a[key], b[key]
        ok = (got_a == exp_a) and (got_b == exp_b)
        if not ok:
            failed.append(f"{lbl} (A={got_a} want {exp_a}, B={got_b} want {exp_b})")
        fmt = (lambda v: f"${v:,}") if money else str
        print(f"  {lbl:<{w}}   {fmt(got_a):>12} {fmt(got_b):>10}   "
              f"{'PASS' if ok else 'FAIL'}")

    print(f"\n  ON THE SAME CASE, ${SPENT:,} had already been spent when the passport "
          f"came back forged.")
    print(f"    no RETRACT: 3 of 3 derived beliefs stay active, 1 pending effect "
          f"still runs,")
    unreached_a = SPENT - a['usd_reversal_recorded'] - a['usd_unreachable_named']
    print(f"                and ${unreached_a:,} of ${SPENT:,} is reached by nothing. "
          f"Nobody is even told.")
    print(f"    RETRACT:    3 of 3 retracted, the pending effect cancelled, both "
          f"executed effects reached;")
    print(f"                ${b['usd_reversal_recorded']:,} has a reversal recorded "
          f"under one idempotency key,")
    print(f"                ${b['usd_unreachable_named']:,} is named as unreachable, "
          f"and ${b['usd_settled']:,} is settled --")
    print(f"                no payment provider is wired, and the ledger refuses "
          f"to say otherwise.")
    print(f"\n  effects, no RETRACT: {a['_effects']}")
    print(f"  effects, RETRACT:    {b['_effects']}")
    print(f"  compensation outcomes: {b['_compensation_outcomes']}")

    print("\nALL PASS" if not failed else "\nFAILED: " + "; ".join(failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
