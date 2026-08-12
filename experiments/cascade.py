"""The retraction cascade: what happens when a belief was already acted on.

Concurrency control stops a bad fact being WRITTEN. It does nothing about a bad
fact that was written correctly, believed reasonably, and has already moved
money. That is the failure this half of RETRACT exists for.

THE SCENARIO
    M1  "Customer 4471 verified their identity via passport."
    M2  "Customer 4471 is eligible for instant refunds."      (derived from M1)
    M3  "Refund of $1,240 to customer 4471 is approved."      (derived from M2)
        -> effect: refund_issued   EXECUTED. The money is gone.
    M4  "Customer 4471 qualifies for priority support."       (derived from M1)
        -> effect: tier_upgrade    PENDING. Not yet run.
    M5  "Customer 9902 verified their identity."              (unrelated)
        -> effect: welcome_email   PENDING. Must survive untouched.

Then the passport comes back forged. M1 is false.

SUCCESS CRITERION, written before the code:
    retract(M1) must, in ONE transaction:
      * retract exactly M1, M2, M3, M4  -- and NOT M5
      * cancel the pending tier_upgrade
      * flag the executed refund as needs_compensation, NOT silently cancel it
        (the money already moved; pretending otherwise is the actual failure)
      * leave customer 9902's pending email alone

The blast radius is the assertion. A cascade that retracts everything is as
wrong as one that retracts nothing -- it just fails in the safer direction.
"""

from __future__ import annotations

import json
import os
import sys
import uuid

import numpy as np
import psycopg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from retract.engine import MemoryEngine, vec_literal  # noqa: E402
from retract.lsh import DIM, primary_bucket  # noqa: E402

rng = np.random.default_rng(42)


def unit(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=DIM)
    return v / np.linalg.norm(v)


def write(eng: MemoryEngine, emb, content, derived_from=()) -> uuid.UUID:
    rr = eng.read(emb)
    res = eng.commit(emb, content, rr, derived_from=derived_from)
    if res.memory_id is None:
        raise RuntimeError(f"unexpected conflict writing {content!r}")
    return res.memory_id


def add_effect(url, scope, memory_id, tool, key, status) -> uuid.UUID:
    with psycopg.connect(url, autocommit=True) as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO effect (scope, justified_by, tool, payload, idempotency_key, status, executed_at) "
            "VALUES (%s,%s,%s,%s,%s,%s, CASE WHEN %s='executed' THEN now() END) RETURNING id",
            (scope, memory_id, tool, json.dumps({"key": key}), key, status, status),
        )
        return cur.fetchone()[0]


def main() -> int:
    url = os.environ["CRDB_URL"]
    scope = f"cascade-{uuid.uuid4().hex[:8]}"
    eng = MemoryEngine(url, scope, "support-agent")

    m1 = write(eng, unit(1), "Customer 4471 verified their identity via passport.")
    m2 = write(eng, unit(2), "Customer 4471 is eligible for instant refunds.", [m1])
    m3 = write(eng, unit(3), "Refund of $1,240 to customer 4471 is approved.", [m2])
    m4 = write(eng, unit(4), "Customer 4471 qualifies for priority support.", [m1])
    m5 = write(eng, unit(5), "Customer 9902 verified their identity.")

    e_refund = add_effect(url, scope, m3, "refund_issued", "rf-4471-1240", "executed")
    e_tier = add_effect(url, scope, m4, "tier_upgrade", "tu-4471", "pending")
    e_other = add_effect(url, scope, m5, "welcome_email", "we-9902", "pending")

    print(f"scope {scope}: 5 beliefs, 3 effects (1 executed, 2 pending)")
    print("\nthe passport was forged. retracting M1.\n")

    out = eng.retract(m1, "passport confirmed forged by fraud team")

    with psycopg.connect(url, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT id, status FROM memory WHERE scope=%s", (scope,))
        mem = dict(cur.fetchall())
        cur.execute("SELECT id, status FROM effect WHERE scope=%s", (scope,))
        eff = dict(cur.fetchall())

    checks = [
        ("M1 retracted", mem[m1] == "retracted"),
        ("M2 retracted (derived)", mem[m2] == "retracted"),
        ("M3 retracted (derived x2)", mem[m3] == "retracted"),
        ("M4 retracted (sibling branch)", mem[m4] == "retracted"),
        ("M5 UNTOUCHED (unrelated customer)", mem[m5] == "active"),
        ("executed refund -> needs_compensation", eff[e_refund] == "needs_compensation"),
        ("pending tier upgrade -> cancelled", eff[e_tier] == "cancelled"),
        ("unrelated email still pending", eff[e_other] == "pending"),
    ]

    width = max(len(n) for n, _ in checks)
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<{width}}")

    print(f"\nblast radius: {len(out['retracted'])} beliefs, "
          f"{len(out['cancelled'])} effects cancelled, "
          f"{len(out['needs_compensation'])} needing compensation")
    for row in out["needs_compensation"]:
        print(f"  COMPENSATE: {row['tool']} {row['payload']}")

    failed = [n for n, ok in checks if not ok]
    print("\nALL PASS" if not failed else f"\nFAILED: {failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
