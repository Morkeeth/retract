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

AND THE PART THAT WAS ACTUALLY BROKEN
`app/main.py` never called resolve() at all. It asks for a verdict, prints it,
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
        cur.execute("SELECT count(*) AS n FROM memory WHERE scope=%s", (scope,))
        rows = cur.fetchone()["n"]
    return {"active": active, "retracted": retracted, "superseded": superseded,
            "rows": rows, "open_contradictions": open_contra,
            "effects_touched": touched}


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
    # A SOURCE check, kept but demoted. It is the weaker kind and must not read
    # as proof -- and it has to be precise: an earlier version matched
    # `.resolve(` and went green on `Path(__file__).resolve()` two lines into
    # the imports, which is the wrapped-phrase grep failure in another costume.
    src = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text()
    wired = re.search(r"\b(eng|engine)\.resolve\(", src) is not None
    # NOT "gated on the resolution" -- that was the previous design and it is
    # exactly what must not be true now. The cascade must hang off the external
    # event, and the retraction must not carry the model's verdict.
    gated = "EXTERNAL_RETRACTION" in src and "if event is None:" in src
    uncoupled = not re.search(r"put\(type=\"retracting\"[^)]*(resolution|authorised_by)", src, re.S)
    print("\nSource check (weak, kept for signal only)")
    print(f"  {'PASS' if wired else 'FAIL'}  app/main.py calls engine.resolve()")
    print(f"  {'PASS' if gated else 'FAIL'}  the cascade hangs off the external event")
    print(f"  {'PASS' if uncoupled else 'FAIL'}  the retraction event does not carry the verdict")
    if not (wired and gated and uncoupled):
        failures += 1

    failures += behavioural()
    return 1 if failures else 0


def behavioural() -> int:
    """The 3x2 matrix: every verdict, with the external retraction event absent
    and present.

    The point is that these are two independent inputs. An earlier version of
    this arm tested only the verdict and passed a build in which `superseded`
    triggered the cascade -- which is the model authorising compensation one step
    removed. A matrix is what makes the independence observable rather than
    asserted:

      event ABSENT   no retraction and no compensation, on ALL THREE verdicts.
                     The model deciding a belief is wrong does not entitle it to
                     move money.
      event PRESENT  the cascade runs on ALL THREE verdicts, on the event's own
                     authority and receipt. The resolution is not consulted.
      either way     the verdict still changes what the memory believes --
                     `superseded` closes the incumbent and writes the challenger,
                     the other two do not.

    `_story_events` is a plain function pushing dicts onto a queue, so it runs
    directly with the adjudicator and the external-event seam stubbed. No HTTP,
    no stream parsing, and no reimplementation of the logic under test.
    """
    import queue
    import app.main as M

    class Stub:
        is_model = False
        name = "stub"

        def __init__(self, resolution): self.resolution = resolution

        def judge(self, *a, **k):
            from retract.adjudicate import Verdict
            return Verdict(self.resolution, 1.0, "stubbed for the eval", self.name)

    original, original_emb = M._adjudicator, M._embedder
    original_event = M.EXTERNAL_RETRACTION
    if M._embedder is None:
        M._embedder = get_embedder(os.environ.get("RETRACT_EMBEDDER", "bedrock"))

    print("\nBehavioural 3x2: verdict x external retraction event")
    print("  the two axes must be independent, or the model is authorising money\n")
    bad = 0
    try:
        for verdict in ("rejected", "duplicate", "superseded"):
            for present in (False, True):
                M._adjudicator = Stub(verdict)
                M.EXTERNAL_RETRACTION = original_event if present else (lambda scope: None)

                q: "queue.Queue[dict]" = queue.Queue()
                M._story_events(q)
                events = []
                while not q.empty():
                    events.append(q.get())
                scope = next(e["scope"] for e in events if e["type"] == "done")
                st = state(os.environ["CRDB_URL"], scope)
                cascade = any(e["type"] == "retracting" for e in events)
                retracting = next((e for e in events if e["type"] == "retracting"), {})

                problems = []
                if present:
                    if not cascade:            problems.append("no cascade")
                    if st["retracted"] == 0:   problems.append("nothing retracted")
                    if st["effects_touched"] == 0: problems.append("no effect touched")
                    # The event must be recorded by ITS authority, not the model's.
                    if retracting.get("authority") != "fraud-team":
                        problems.append("retraction not attributed to the external authority")
                    if not retracting.get("receipt"):
                        problems.append("retraction carries no receipt")
                    if "resolution" in retracting or "authorised_by" in retracting:
                        problems.append("retraction event carries the model's resolution")
                else:
                    if cascade:                problems.append("cascade ran with no external event")
                    if st["retracted"]:        problems.append(f"{st['retracted']} retracted with no event")
                    if st["effects_touched"]:  problems.append(f"{st['effects_touched']} effects touched with no event")

                # The verdict axis, which must hold on BOTH sides of the matrix.
                # Measured as ROWS, not as the incumbent's status: resolve()
                # writes the challenger, and a later cascade overwrites the
                # incumbent's status from 'superseded' to 'retracted' -- the
                # first draft asserted the status and failed a correct build.
                # The extra row is what the verdict durably did.
                want_rows = 6 if verdict == "superseded" else 5
                if st["rows"] != want_rows:
                    problems.append(f"memory rows={st['rows']}, expected {want_rows} "
                                    f"-- the verdict did not change what is believed")
                if st["open_contradictions"]:
                    problems.append(f"{st['open_contradictions']} contradiction left OPEN")

                bad += bool(problems)
                tag = "event" if present else "no event"
                print(f"  {'PASS' if not problems else 'FAIL'}  {verdict:<11} {tag:<9} "
                      f"retracted={st['retracted']} effects={st['effects_touched']} "
                      f"rows={st['rows']} cascade={'yes' if cascade else 'no'}")
                for pr in problems:
                    print(f"          {pr}")
    finally:
        M._adjudicator, M._embedder = original, original_emb
        M.EXTERNAL_RETRACTION = original_event

    if bad:
        print("\n  The model's verdict and the authority to take money back are not"
              "\n  separated. That is the defect, whichever cell failed.")
    return bad


if __name__ == "__main__":
    raise SystemExit(main())
