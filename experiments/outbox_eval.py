"""Can the ledger say `compensated` without an external receipt?

THE INVARIANT
No path reaches `effect.status='compensated'` on an original, or `'executed'` on
a reversal, unless a provider returned an identifier this process did not
generate. Everything short of that is a recorded intent.

WHY IT NEEDS A CONTROL RATHER THAN A COMMENT
An earlier version of this project wrote the reversal row as `executed` and the
original as `compensated` in the same transaction that decided a reversal was
owed, with no provider anywhere in the repository. The docs were then edited to
explain that carefully. That is a comments-only honesty patch over a false state
machine, and it fails the moment a judge queries the table instead of reading
the page.

THE THREE ARMS

  absent    NoProvider raises. The request stays recorded-and-undelivered, the
            original stays needs_compensation, and NOTHING is executed or
            compensated.
  failing   A provider that is reached and refuses. Same ledger outcome as
            absent, different reason recorded. This arm exists because a
            compensation path that has never been watched failing is the same
            class of claim as a test that has never been red.
  settling  A provider that returns a receipt. This is the ONLY arm allowed to
            produce compensated/executed, and the receipt must land on the row.

The settling arm uses a local fake, and that is stated rather than hidden: it
proves the transition is reachable and correctly gated. It is NOT evidence that
money moved, and no surface may claim so on its strength. A real provider is
one credential away and named in the report.

    CRDB_URL=... RETRACT_EMBEDDER=bedrock uv run python experiments/outbox_eval.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from retract.compensate import (  # noqa: E402
    CompensateResult,
    DispatchFailed,
    NoProvider,
    compensate_effect,
    settle,
)
from retract.embed import get_embedder  # noqa: E402
from retract.engine import MemoryEngine  # noqa: E402


class RefusingProvider:
    """Reached, and refuses. The failure arm."""

    name = "refusing-test-double"

    def dispatch(self, **_: object) -> str:
        raise DispatchFailed("provider returned 502 (test double)")


class CountingProvider:
    """Idempotent on the key, and counts how many times it was actually called.

    The two arms below need different things from it: the concurrency arm needs
    to know how many CALLS happened, and the retry arm needs the same key to
    return the same receipt. A real provider is expected to have exactly this
    property; this double is how the code path that depends on it gets exercised
    at all before one exists.
    """

    name = "counting-test-double"

    def __init__(self) -> None:
        self.calls = 0
        self.by_key: dict[str, str] = {}

    def dispatch(self, *, idempotency_key: str, **_: object) -> str:
        self.calls += 1
        if idempotency_key not in self.by_key:
            self.by_key[idempotency_key] = f"tdbl_{uuid.uuid4().hex[:16]}"
        return self.by_key[idempotency_key]


class ReceiptProvider:
    """Returns a receipt. A LOCAL FAKE, and the report says so.

    It proves the settle transition is reachable and correctly gated. It proves
    nothing about money. The identifier is shaped like an external one and is
    not one.
    """

    name = "receipt-test-double"

    def dispatch(self, **_: object) -> str:
        return f"tdbl_{uuid.uuid4().hex[:16]}"


def rows(url: str, scope: str) -> dict:
    with psycopg.connect(url, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute("SELECT tool, status, payload FROM effect WHERE scope=%s "
                    "ORDER BY created_at", (scope,))
        return {r["tool"]: r for r in cur.fetchall()}


def build(url: str, scope: str, emb) -> tuple[MemoryEngine, uuid.UUID]:
    """One belief, one executed refund, retracted so the refund is flagged."""
    eng = MemoryEngine(url, scope, "outbox-eval", emb.name)
    text = "Customer 4471 has verified their identity via passport."
    r = eng.commit(emb.embed(text), text, "Customer 4471", "identity verified")
    with psycopg.connect(url, autocommit=True) as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO effect (scope, justified_by, tool, payload, idempotency_key,"
            " status, executed_at) VALUES (%s,%s,'refund_issued',%s,%s,'executed', now())"
            " RETURNING id",
            (scope, r.memory_id, json.dumps({"label": "$1,240 sent"}), f"rf-{scope}"),
        )
        eid = cur.fetchone()[0]
    eng.retract(r.memory_id, "test: forged passport")
    return eng, eid


def main() -> int:
    url = os.environ["CRDB_URL"]
    emb = get_embedder(os.environ.get("RETRACT_EMBEDDER", "bedrock"))
    bad = 0

    print("Can the ledger say compensated without an external receipt?\n")

    for label, provider, may_settle in (
        ("absent",   NoProvider(),       False),
        ("failing",  RefusingProvider(), False),
        ("settling", ReceiptProvider(),  True),
    ):
        scope = f"outbox-{label}-{uuid.uuid4().hex[:8]}"
        eng, eid = build(url, scope, emb)

        res = eng.compensate(eid)
        after_record = rows(url, scope)
        req = next((r for r in after_record.values()
                    if r["tool"].endswith("_requested")), None)

        problems = []
        if res.outcome != "recorded":
            problems.append(f"compensate() returned {res.outcome!r}, expected 'recorded'")
        if req is None:
            problems.append("no request row written")
        elif req["status"] != "pending":
            problems.append(f"request row is {req['status']!r}, expected 'pending'")
        if after_record["refund_issued"]["status"] != "needs_compensation":
            problems.append(f"original is {after_record['refund_issued']['status']!r} "
                            f"before any dispatch")

        settled = settle(url, scope, res.reversal_id, provider=provider)
        final = rows(url, scope)
        orig, rev = final["refund_issued"], next(
            r for r in final.values() if r["tool"].endswith("_requested"))

        if may_settle:
            if settled.outcome != "compensated":
                problems.append(f"settle() returned {settled.outcome!r}")
            if orig["status"] != "compensated":
                problems.append(f"original is {orig['status']!r}, expected compensated")
            if rev["status"] != "executed":
                problems.append(f"request is {rev['status']!r}, expected executed")
            if not rev["payload"].get("external_receipt"):
                problems.append("settled with no external receipt on the row")
        else:
            # THE ASSERTION THIS FILE EXISTS FOR.
            if orig["status"] == "compensated":
                problems.append("ORIGINAL MARKED COMPENSATED WITH NO RECEIPT")
            if rev["status"] == "executed":
                problems.append("REQUEST MARKED EXECUTED WITH NO RECEIPT")
            if settled.outcome == "compensated":
                problems.append("settle() reported compensated with no receipt")
            if rev["payload"].get("external_receipt"):
                problems.append("a receipt appeared from nowhere")

        bad += bool(problems)
        print(f"  {'PASS' if not problems else 'FAIL'}  provider={label:<9} "
              f"original={orig['status']:<19} request={rev['status']:<8} "
              f"receipt={rev['payload'].get('external_receipt') or '—'}")
        for p in problems:
            print(f"          {p}")

    bad += exactly_once(url, emb)

    print()
    if bad:
        print("A ledger that can say compensated without a receipt is bookkeeping "
              "that flatters itself.")
        return 1
    print("compensated/executed is reachable only through a provider receipt.")
    print()
    print("UNVERIFIED, and stated rather than implied:")
    print("  * External exactly-once. Every arm above used a LOCAL test double.")
    print("    They prove this side threads a stable key and does not dispatch")
    print("    twice from two workers. They prove NOTHING about a real provider")
    print("    deduping, because no real provider has ever been called.")
    print("  * That any money moved. No payment system exists in this repository.")
    return 0


def exactly_once(url: str, emb) -> int:
    """Two workers, and a crash between the provider call and the DB commit.

    The database's UNIQUE key protects the outbox ROW. It cannot protect the
    external ACTION, so the two failure shapes that matter are:

      concurrent  two workers read the same `pending` request and both call out.
                  Guarded on this side: the first claims the row, the second
                  sees `in_flight` and returns without dispatching.
      crash       the provider succeeded and this process died before writing
                  the receipt. Nothing on this side can prevent the retry, so
                  the retry MUST carry the same idempotency key and the provider
                  MUST return the same receipt. That is the contract, and this
                  arm exercises the code path that depends on it.
    """
    print("\nExactly-once: two workers, and a crash after dispatch\n")
    bad = 0

    # --- concurrent ---
    scope = f"outbox-concurrent-{uuid.uuid4().hex[:8]}"
    eng, eid = build(url, scope, emb)
    res = eng.compensate(eid)
    prov = CountingProvider()

    # A worker that raises must appear in the results, not vanish. A bare
    # thread that dies still lets join() return, and the assertion below would
    # then be counting one survivor rather than two participants -- which is
    # the exact defect race.py had this morning.
    out: list = []
    lock = threading.Lock()
    def worker():
        try:
            r = settle(url, scope, res.reversal_id, provider=prov)
        except Exception as exc:  # noqa: BLE001
            r = CompensateResult(f"error:{type(exc).__name__}", None, None, None, str(exc))
        with lock:
            out.append(r)
    t1, t2 = threading.Thread(target=worker), threading.Thread(target=worker)
    t1.start(); t2.start(); t1.join(); t2.join()

    outcomes = sorted(r.outcome for r in out)
    problems = []
    if len(out) != 2:
        problems.append(f"{len(out)} workers reported, expected 2 -- one died silently")
    if any(o.startswith("error:") for o in outcomes):
        problems.append(f"a worker raised: {[o for o in outcomes if o.startswith('error:')]}")
    if prov.calls != 1:
        problems.append(f"provider was called {prov.calls} times, expected 1")
    if outcomes.count("compensated") != 1:
        problems.append(f"outcomes {outcomes}, expected exactly one 'compensated'")
    bad += bool(problems)
    print(f"  {'PASS' if not problems else 'FAIL'}  concurrent   provider_calls="
          f"{prov.calls} outcomes={outcomes}")
    for pr in problems:
        print(f"          {pr}")

    # --- crash after dispatch, before the DB write ---
    scope = f"outbox-crash-{uuid.uuid4().hex[:8]}"
    eng, eid = build(url, scope, emb)
    res = eng.compensate(eid)
    prov = CountingProvider()

    class Crashing(CountingProvider):
        name = "crashing-test-double"
        def __init__(self, inner): self.inner = inner; self.armed = True
        def dispatch(self, **kw):
            r = self.inner.dispatch(**kw)
            if self.armed:
                self.armed = False
                raise RuntimeError("process died after the provider succeeded")
            return r

    crashing = Crashing(prov)
    try:
        settle(url, scope, res.reversal_id, provider=crashing)
    except RuntimeError:
        pass  # the crash

    # The row is still `in_flight` from the dead worker. A fresh lease must be
    # refused, and a stale one must be reclaimed BY THE PRODUCTION PATH.
    #
    # An earlier version of this arm deleted `payload.dispatch` with raw SQL
    # before retrying, which routed around the branch under test and would have
    # passed against a build with no reclaim at all -- the crash would strand
    # the reversal forever in production and this arm would still be green.
    blocked = settle(url, scope, res.reversal_id, provider=crashing)
    if blocked.outcome != "dispatch_in_flight":
        problems_pre = [f"a fresh lease was not refused: {blocked.outcome!r}"]
    else:
        problems_pre = []

    # Backdate the claim. Moving the clock is fair; removing the guard is not.
    with psycopg.connect(url, autocommit=True) as c, c.cursor() as cur:
        cur.execute(
            "UPDATE effect SET payload = payload || jsonb_build_object("
            "'dispatch_started_at', (now() - INTERVAL '1 hour')::STRING) "
            "WHERE id=%s AND scope=%s", (res.reversal_id, scope))
    second = settle(url, scope, res.reversal_id, provider=crashing)
    final = rows(url, scope)
    rev = next(r for r in final.values() if r["tool"].endswith("_requested"))

    problems = list(problems_pre)
    if prov.calls != 2:
        problems.append(f"provider saw {prov.calls} calls; the retry is expected "
                        f"to re-present the key")
    if len(set(prov.by_key.values())) != 1:
        problems.append(f"two different receipts issued: {set(prov.by_key.values())}")
    if rev["payload"].get("external_receipt") not in prov.by_key.values():
        problems.append("settled receipt is not the provider's")
    if second.outcome != "compensated":
        problems.append(f"retry returned {second.outcome!r}")
    if rev["payload"].get("attempt", 0) < 2:
        problems.append(f"attempt counter is {rev['payload'].get('attempt')}, "
                        f"so the reclaim branch did not run")
    bad += bool(problems)
    print(f"  {'PASS' if not problems else 'FAIL'}  crash+retry  provider_calls="
          f"{prov.calls} distinct_receipts={len(set(prov.by_key.values()))} "
          f"attempt={rev['payload'].get('attempt')} fresh_lease_refused="
          f"{'yes' if blocked.outcome == 'dispatch_in_flight' else 'NO'} "
          f"outcome={second.outcome}")
    for pr in problems:
        print(f"          {pr}")
    print("\n  Two calls on the retry is CORRECT and is the point: this side "
          "cannot\n  know the first succeeded. One receipt survives only because "
          "the provider\n  deduped on the key. A provider without that property "
          "double-refunds.")
    return bad


if __name__ == "__main__":
    raise SystemExit(main())
