"""Does the adjudicator's verdict change what the system does?

THE QUESTION A JUDGE ASKS
"If I invert Claude's answer, does the product behave differently?" Everything
this project argues rests on the answer being yes. The page shows a model
deciding; the claim is that the decision is load-bearing.

WHY THIS FILE EXISTS BEFORE ANY FIX
`MemoryEngine.resolve()` is implemented at engine.py:215 and handles all three
verdicts. Nothing calls it -- `grep -rn 'resolve(' --include='*.py'` returns
only `Path.resolve()`. `app/main.py` asks the adjudicator for a verdict, puts it
on the stream, and then retracts the incumbent unconditionally on the next
statement. So today the answer is no, and the demo does not do what the demo
says.

This is written to FAIL against that. It is the control for a fix that has not
been made yet, and running it now is what turns "Codex says the verdict is
inert" into something observed. When resolve() is wired in, the same file
without a line changed should go green -- that is the only honest way to know
the fix did anything.

TWO OPERATIONS, AND THE FIRST DRAFT OF THIS FILE CONFLATED THEM
Reading the engine rather than assuming: `resolve()` and `retract()` are
different acts and the schema has different statuses for them.

  resolve(superseded)  replaces a belief. The incumbent closes with
                       status='superseded', the challenger is written, the
                       contradiction resolves. It does NOT cascade.
  retract()            takes a belief back AND everything built on it --
                       descendants, their pending effects cancelled, their
                       executed effects flagged for compensation.

So "superseded" does not mean "retracted", and an early version of this file
asserted that it did and reported the engine broken. It is not. The expectations
below are read off `engine.py:215` and the schema's own CHECK constraint.

WHAT EACH VERDICT MUST MEAN FOR resolve()
  rejected    the incumbent stands: still active, no new memory written,
              contradiction closed rather than left open
  duplicate   it was a rephrasing: same as rejected -- nothing new is believed
  superseded  the challenger wins: incumbent status='superseded', exactly one
              new memory written, contradiction closed

AND THE PART THAT IS ACTUALLY BROKEN
`app/main.py` never calls resolve() at all. It asks for a verdict, prints it,
and calls retract() on the next statement unconditionally -- the stronger of the
two operations, on every verdict including the two that mean "the original
belief was fine". The second section below is that claim as a test.

    CRDB_URL=... RETRACT_EMBEDDER=bedrock uv run python experiments/verdict_eval.py
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from retract.embed import get_embedder  # noqa: E402
from retract.engine import MemoryEngine  # noqa: E402

INCUMBENT = "Customer 4471 has verified their identity via passport."
CHALLENGER = "Customer 4471 FAILED identity verification - passport is forged."
SUBJECT, PREDICATE = "Customer 4471", "identity verified"


def state(url: str, scope: str) -> dict:
    """Read the world back out of the cluster, not out of the return value.

    A method can report what it intended while the rows say otherwise, and the
    rows are what a judge queries.
    """
    with psycopg.connect(url, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM memory WHERE scope=%s AND valid_to IS NULL "
                    "AND status='active'", (scope,))
        active = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM memory WHERE scope=%s AND status='retracted'",
                    (scope,))
        retracted = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM memory WHERE scope=%s AND status='superseded'",
                    (scope,))
        superseded = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM contradiction WHERE scope=%s "
                    "AND resolution='open'", (scope,))
        open_contra = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM effect WHERE scope=%s "
                    "AND status IN ('needs_compensation','compensated')", (scope,))
        touched = cur.fetchone()["n"]
    return {"active": active, "retracted": retracted, "superseded": superseded,
            "open_contradictions": open_contra, "effects_touched": touched}


def build(url: str, scope: str, emb) -> tuple[MemoryEngine, uuid.UUID]:
    """One belief, one executed effect hanging off it, one contradiction raised."""
    eng = MemoryEngine(url, scope, "verdict-eval", emb.name)
    r = eng.commit(emb.embed(INCUMBENT), INCUMBENT, SUBJECT, PREDICATE)
    with psycopg.connect(url, autocommit=True) as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO effect (scope, justified_by, tool, payload, idempotency_key,"
            " status, executed_at) VALUES (%s,%s,%s,%s,%s,'executed', now())",
            (scope, r.memory_id, "refund_issued", '{"label": "$1,240 sent"}',
             f"rf-{scope}"),
        )
    c2 = eng.commit(emb.embed(CHALLENGER), CHALLENGER, SUBJECT, PREDICATE)
    if c2.outcome != "contradiction":
        raise SystemExit(f"setup failed: expected a contradiction, got {c2.outcome!r}")
    return eng, c2.contradiction_id


def main() -> int:
    url = os.environ["CRDB_URL"]
    emb = get_embedder(os.environ.get("RETRACT_EMBEDDER", "bedrock"))

    expected = {
        "rejected":   {"active": 1, "superseded": 0, "open_contradictions": 0},
        "duplicate":  {"active": 1, "superseded": 0, "open_contradictions": 0},
        "superseded": {"active": 1, "superseded": 1, "open_contradictions": 0},
    }

    print("Does the verdict change the outcome? Each arm is a fresh scope.\n")
    failures = 0
    for verdict, want in expected.items():
        scope = f"verdict-{verdict}-{uuid.uuid4().hex[:8]}"
        eng, cid = build(url, scope, emb)
        before = state(url, scope)

        try:
            eng.resolve(cid, verdict, emb.embed(CHALLENGER))
            called = True
            err = ""
        except Exception as exc:  # noqa: BLE001 - an unwired path is the result
            called, err = False, f"{type(exc).__name__}: {exc}"

        after = state(url, scope)
        bad = {k: (after[k], v) for k, v in want.items() if after[k] != v}
        ok = called and not bad

        print(f"  {'PASS' if ok else 'FAIL'}  verdict={verdict}")
        print(f"          before {before}")
        print(f"          after  {after}")
        if not called:
            print(f"          resolve() did not run -- {err}")
        for k, (got, wanted) in bad.items():
            print(f"          {k}: got {got}, expected {wanted}")
        if not ok:
            failures += 1

    print(f"\nresolve(): {3 - failures}/3 verdicts behave correctly when called directly.")

    # --- the actual defect ------------------------------------------------
    # resolve() works. Nothing calls it. This is that sentence as a check, and
    # it is the one that must go green before the demo does what it says.
    # A SOURCE check, and weaker than a behavioural one -- say so rather than
    # let it read as proof. It also has to be precise: the first version matched
    # `.resolve(` and went green on `Path(__file__).resolve()` two lines into the
    # imports. That is the same false positive as a grep that cannot see a
    # wrapped phrase, in a file written to catch exactly that class.
    src = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text()
    wired = re.search(r"\b(eng|engine)\.resolve\(", src) is not None
    after_adj = src.split("act 4")[-1][:800]
    gated = bool(re.search(r"if\s+v\.resolution|resolution\s*==|verdict\s*==", after_adj))
    print("\nIs the verdict load-bearing in the demo?  (source check, not behavioural)")
    print(f"  {'PASS' if wired else 'FAIL'}  app/main.py calls engine.resolve()")
    print(f"  {'PASS' if gated else 'FAIL'}  the cascade is gated on the verdict")
    if not (wired and gated):
        print("\n  app/main.py asks for a verdict, prints it, and retracts")
        print("  unconditionally on the next statement. Invert Claude's answer and")
        print("  the product behaves identically. A verdict that does not change")
        print("  the outcome is a verdict on a screen.")
        failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
