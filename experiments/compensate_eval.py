"""The compensation loop: turning a flag into a reversal that cannot double-fire.

Retraction reaches an already-executed side effect and marks it
`needs_compensation`. That is a claim until something watches the flag fire.
This eval is the control for that claim.

SUCCESS CRITERION, written from the task before the handler existed:

    After retract(M1) leaves the executed refund flagged,
    compensate(refund) must, and compensate(unknown_tool) must not:

      * move the refund  needs_compensation -> compensated
      * write a reversal row (tool=refund_reversed) whose payload points back
        at the original, with idempotency key `comp:<original key>`
      * record that reversal's id on the original as compensated_by
      * produce ONE reversal when compensate(refund) is called a second time
        (the UNIQUE constraint is the backstop; the second call is a no-op)
      * leave an executed effect whose tool has no registered handler in
        needs_compensation — silently greening it would be the failure mode
      * leave an unrelated customer's effects untouched

The "no handler" arm is the control. A test that only checks the happy path
passes when the registry is a wildcard that marks everything done.

UNRUN against the live CockroachDB Cloud cluster (no credentials in this
environment). Offline verification, if any, uses a local single-node store and
synthetic unit vectors — never a claim about embedding semantics.
"""

from __future__ import annotations

import json
import os
import sys
import uuid

import numpy as np
import psycopg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from retract.compensate import COMPENSATIONS, compensation_key  # noqa: E402
from retract.embed import DIM  # noqa: E402
from retract.engine import MemoryEngine  # noqa: E402


def unit(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=DIM)
    return v / np.linalg.norm(v)


def write(eng: MemoryEngine, emb, content, subject, predicate, derived_from=()) -> uuid.UUID:
    eng.read(emb)
    res = eng.commit(emb, content, subject, predicate, derived_from=derived_from)
    if res.memory_id is None:
        raise RuntimeError(f"unexpected {res.outcome} writing {content!r}")
    return res.memory_id


def add_effect(url, scope, memory_id, tool, key, status) -> uuid.UUID:
    with psycopg.connect(url, autocommit=True) as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO effect (scope, justified_by, tool, payload, idempotency_key, status, "
            "executed_at) VALUES (%s,%s,%s,%s,%s,%s, "
            "CASE WHEN %s='executed' THEN now() END) RETURNING id",
            (scope, memory_id, tool, json.dumps({"key": key}), key, status, status),
        )
        return cur.fetchone()[0]


def main() -> int:
    url = os.environ["CRDB_URL"]
    scope = f"compensate-{uuid.uuid4().hex[:8]}"
    eng = MemoryEngine(url, scope, "support-agent")

    m1 = write(eng, unit(1), "Customer 4471 verified their identity via passport.",
               "Customer 4471", "identity verified")
    m2 = write(eng, unit(2), "Customer 4471 is eligible for instant refunds.",
               "Customer 4471", "refund eligibility", [m1])
    m3 = write(eng, unit(3), "Refund of $1,240 to customer 4471 is approved.",
               "Customer 4471", "refund approval", [m2])
    m4 = write(eng, unit(4), "Customer 4471 qualifies for priority support.",
               "Customer 4471", "support tier", [m1])
    m5 = write(eng, unit(5), "Customer 9902 verified their identity.",
               "Customer 9902", "identity verified")

    # Happy-path tool (has a handler), control tool (does not), unrelated pending.
    e_refund = add_effect(url, scope, m3, "refund_issued", "rf-4471-1240", "executed")
    e_unknown = add_effect(url, scope, m3, "card_charge", "cc-4471-99", "executed")
    e_tier = add_effect(url, scope, m4, "tier_upgrade", "tu-4471", "pending")
    e_other = add_effect(url, scope, m5, "welcome_email", "we-9902", "pending")

    assert "card_charge" not in COMPENSATIONS, (
        "control is broken: card_charge must not have a registered handler"
    )

    print(f"scope {scope}: retracting M1, then compensating\n")
    eng.retract(m1, "passport confirmed forged by fraud team")

    r1 = eng.compensate(e_refund)
    r1_again = eng.compensate(e_refund)          # must not double-fire
    r_unknown = eng.compensate(e_unknown)        # control: no handler

    with psycopg.connect(url, autocommit=True) as c, c.cursor() as cur:
        cur.execute(
            "SELECT id, tool, status, idempotency_key, compensated_by, payload "
            "FROM effect WHERE scope=%s ORDER BY tool, idempotency_key",
            (scope,),
        )
        rows = {row[0]: {
            "tool": row[1], "status": row[2], "key": row[3],
            "compensated_by": row[4], "payload": row[5],
        } for row in cur.fetchall()}
        cur.execute(
            "SELECT count(*) FROM effect WHERE scope=%s AND tool='refund_reversed'",
            (scope,),
        )
        n_reversals = cur.fetchone()[0]
        cur.execute(
            "SELECT status FROM memory WHERE id=%s", (m5,),
        )
        m5_status = cur.fetchone()[0]

    refund = rows[e_refund]
    unknown = rows[e_unknown]
    reversal = rows.get(refund["compensated_by"]) if refund["compensated_by"] else None

    checks = [
        ("refund ends compensated",
         refund["status"] == "compensated"),
        ("reversal row exists and points back",
         reversal is not None
         and reversal["tool"] == "refund_reversed"
         and reversal["payload"].get("reverses") == str(e_refund)),
        ("compensated_by records the reversal id",
         refund["compensated_by"] == (reversal and rows[e_refund]["compensated_by"])
         and refund["compensated_by"] is not None),
        ("reversal idempotency key is comp:<original>",
         reversal is not None
         and reversal["key"] == compensation_key("rf-4471-1240")),
        ("second compensate produced ONE reversal, not two",
         n_reversals == 1
         and r1.outcome == "compensated"
         and r1_again.outcome == "already_compensated"
         and r1_again.reversal_id == r1.reversal_id),
        ("unregistered tool stays needs_compensation (control)",
         unknown["status"] == "needs_compensation"
         and r_unknown.outcome == "no_handler"
         and unknown["compensated_by"] is None),
        ("pending tier upgrade still cancelled (untouched by compensate)",
         rows[e_tier]["status"] == "cancelled"),
        ("unrelated customer's email still pending",
         rows[e_other]["status"] == "pending" and m5_status == "active"),
    ]

    width = max(len(n) for n, _ in checks)
    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<{width}}")

    print(f"\nfirst compensate:  {r1.outcome}  {r1.reason}")
    print(f"second compensate: {r1_again.outcome}  (same reversal={r1_again.reversal_id})")
    print(f"control (no handler): {r_unknown.outcome}  {r_unknown.reason}")

    failed = [n for n, ok in checks if not ok]
    print("\nALL PASS" if not failed else f"\nFAILED: {failed}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
