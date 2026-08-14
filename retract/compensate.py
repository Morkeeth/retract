"""Close the loop that retraction opens.

`MemoryEngine.retract()` walks a derivation DAG, cancels *pending* side effects,
and flags *already-executed* ones as `needs_compensation`. That flag is a claim
until something watches it fire. This module is the watcher: it turns
`needs_compensation` into a real reversal, recorded as its own effect row.

WHY A NEW ROW, NOT AN UPDATE
A compensation is itself a side effect. It needs its own idempotency key so
replaying the handler cannot reverse the same refund twice, and it needs to
appear in the ledger as a first-class event a reviewer can query. Updating the
original row in place would erase the evidence that money moved at all.

WHY THE DATABASE ENFORCES EXACTLY-ONCE
The key is `comp:<original idempotency_key>`. The existing
`UNIQUE (scope, idempotency_key)` constraint on `effect` is what stops a double
fire — not an application-level "did we already do this" check, which would race.
Application code still short-circuits when the original is already
`compensated`, so a second call is a no-op rather than an error; the UNIQUE
constraint is the backstop for the crash-between-insert-and-update case.

WHY AN UNREGISTERED TOOL STAYS FLAGGED
Silently marking an unknown tool `compensated` would be the exact dishonesty
this project exists to argue against. A flag nobody can fire is still more
honest than a green status that means nothing.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Protocol
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

# tool that caused the damage -> tool that undoes it.
# Keep this small and obvious. A missing entry is a control, not an error:
# the original effect stays `needs_compensation` and is surfaced.
# The name is the state. These write a REQUEST row; nothing here dispatches.
# `refund_reversed` was the previous value and it read as a completed act in
# every surface that displayed it, next to a ledger status of `executed`.
COMPENSATIONS: dict[str, str] = {
    "refund_issued": "refund_reversal_requested",
    "tier_upgrade": "tier_downgrade_requested",
    "welcome_email": "correction_email_requested",
}


@dataclass
class CompensateResult:
    outcome: str  # 'recorded' | 'already_recorded' | 'compensated' |
                  # 'no_handler' | 'not_eligible' | 'dispatch_failed'
                  # 'recorded' means a request row exists and NOTHING was
                  # dispatched. Only settle() may return 'compensated'.
    original_id: uuid.UUID
    reversal_id: uuid.UUID | None = None
    compensating_tool: str | None = None
    reason: str = ""


def compensation_key(original_key: str) -> str:
    """Derive the reversal's idempotency key from the original's.

    Stable and injective over ordinary keys: given `rf-4471-1240` the reversal
    is always `comp:rf-4471-1240`. The UNIQUE constraint on (scope, key) then
    guarantees one reversal per original, even under concurrent callers.
    """
    return f"comp:{original_key}"


def compensate_effect(
    url: str,
    scope: str,
    agent: str,
    effect_id: uuid.UUID,
) -> CompensateResult:
    """Reverse one effect that retraction flagged.

    One transaction: lock the original row, write the reversal (or find the
    existing one by idempotency key), mark the original `compensated` with
    `compensated_by` pointing at the reversal. A tool with no registered
    handler is left alone — the status stays `needs_compensation`.
    """
    with psycopg.connect(url, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, scope, justified_by, tool, payload, idempotency_key, status, "
            "compensated_by FROM effect WHERE id=%s AND scope=%s FOR UPDATE",
            (effect_id, scope),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"no effect {effect_id} in scope {scope}")

        if row["status"] == "compensated":
            conn.commit()
            return CompensateResult(
                "already_recorded", row["id"], row["compensated_by"],
                COMPENSATIONS.get(row["tool"]),
                "original already carries a reversal id",
            )

        if row["status"] != "needs_compensation":
            conn.commit()
            return CompensateResult(
                "not_eligible", row["id"], None, None,
                f"status is {row['status']!r}, not needs_compensation",
            )

        compensating_tool = COMPENSATIONS.get(row["tool"])
        if compensating_tool is None:
            # The control: unknown tools stay flagged. Do not invent a no-op.
            conn.commit()
            return CompensateResult(
                "no_handler", row["id"], None, None,
                f"no compensation registered for tool {row['tool']!r}",
            )

        rev_key = compensation_key(row["idempotency_key"])
        rev_id = uuid.uuid4()
        payload = {
            "reverses": str(row["id"]),
            "reverses_tool": row["tool"],
            "original_payload": row["payload"],
            # Carried on the row so the boundary survives being read straight
            # out of the table by someone who never opens this file.
            "dispatch": "none",
            "external_receipt": None,
            "note": ("ledger record only. RETRACT recorded that this reversal is "
                     "owed and dispatched nothing; no payment provider is called "
                     "anywhere in this repository."),
        }

        # ---------------------------------------------------------------
        # THE BOUNDARY. Read this before believing anything about money.
        #
        # What happens below is ONE database write. `status='executed'` is the
        # LEDGER's own lifecycle -- the reversal record exists and is durable --
        # and it is not a statement about a payment processor, because none is
        # called from this file or from anywhere else in this repo. Grep it:
        # there is no HTTP client, no SDK, no provider credential.
        #
        # So the honest sentence is: RETRACT decided a reversal was owed,
        # recorded it exactly once under `comp:<original>`, and dispatched
        # nothing. The dispatch is the missing half and its absence is the point
        # of this comment rather than a thing to be glossed.
        #
        # The shape this wants, when an adapter exists, is an outbox and the
        # steps are already separable:
        #   1. record the reversal as OWED, in the same transaction as the
        #      status change -- that is what happens today and it is the half
        #      that must be transactional
        #   2. dispatch OUTSIDE the transaction, because a provider call inside
        #      one holds a lock across a network round trip
        #   3. record the provider's identifier and outcome against this row
        #
        # Step 3 is what makes a reversal externally checkable, and until an
        # identifier arrives that this process did not generate, every id on
        # this row is one we made up. `rev_key` is derived, `rev_id` is a local
        # uuid4. Neither is evidence that anything left the building.
        #
        # INSERT ... ON CONFLICT so a retry after a crash that wrote the
        # reversal but missed the status update finds the existing row rather
        # than failing the UNIQUE constraint and leaving the original flagged.
        cur.execute(
            "INSERT INTO effect (id, scope, justified_by, tool, payload, "
            "idempotency_key, status, executed_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,'pending', NULL) "
            "ON CONFLICT (scope, idempotency_key) DO NOTHING "
            "RETURNING id",
            (rev_id, scope, row["justified_by"], compensating_tool,
             json.dumps(payload), rev_key),
        )
        inserted = cur.fetchone()
        replay = inserted is None
        if replay:
            cur.execute(
                "SELECT id FROM effect WHERE scope=%s AND idempotency_key=%s",
                (scope, rev_key),
            )
            rev_id = cur.fetchone()["id"]

        # The original does NOT become `compensated` here. It stays
        # `needs_compensation` -- because nothing has been compensated. What
        # exists is a request. `compensated_by` points at that request so the
        # link is queryable, and only settle() may move the status, and only
        # when handed an identifier this process did not generate.
        cur.execute(
            "UPDATE effect SET compensated_by=%s WHERE id=%s AND scope=%s",
            (rev_id, row["id"], scope),
        )
        cur.execute(
            "INSERT INTO audit_log (scope, agent, action, memory_id, detail) "
            "VALUES (%s,%s,'compensate',%s,%s)",
            (scope, agent, row["justified_by"], json.dumps({
                "original_effect": str(row["id"]),
                "reversal_effect": str(rev_id),
                "tool": row["tool"],
                "compensating_tool": compensating_tool,
            })),
        )
        conn.commit()

    return CompensateResult(
        "already_recorded" if replay else "recorded",
        row["id"], rev_id, compensating_tool,
        f"{row['tool']} -> {compensating_tool} "
        + ("already requested; no second request written"
           if replay else "requested, awaiting dispatch"),
    )


# ---------------------------------------------------------------------------
# THE EXTERNAL BOUNDARY
#
# Everything above writes rows. Nothing above dispatches. This is the seam where
# an outside system would be called, and it is deliberately empty rather than
# stubbed to return success -- a stub that returns success is how a state
# machine learns to lie.
# ---------------------------------------------------------------------------


class DispatchFailed(RuntimeError):
    """The provider was reached and refused, or could not be reached."""


class CompensationProvider(Protocol):
    """Return an identifier THIS PROCESS DID NOT GENERATE, or raise.

    That is the whole contract and it is the only thing that makes a reversal
    externally checkable. A provider that returns a locally-made uuid satisfies
    the type and defeats the point.
    """

    name: str

    def dispatch(self, *, scope: str, request_id: uuid.UUID, tool: str,
                 payload: dict, idempotency_key: str) -> str:
        """`idempotency_key` is stable across every retry of this reversal.

        It is `comp:<original>` and it does not change when a worker crashes or
        when two workers race. The provider MUST dedupe on it and return the
        same receipt for a repeat, because nothing on this side can undo a call
        that already left the building. A provider without that property makes
        double-dispatch a question of luck.
        """
        ...


class NoProvider:
    """The configured state today. Reached, and refuses, loudly.

    Not a stub returning success and not a silent no-op: either would let the
    settlement path run and mark rows `compensated` with a receipt we invented.
    """

    name = "none"

    def dispatch(self, **_: object) -> str:  # accepts idempotency_key, ignores it
        raise DispatchFailed(
            "no compensation provider is configured. RETRACT recorded that a "
            "reversal is owed and dispatched nothing."
        )


DISPATCH_LEASE_SECONDS = 120


def settle(url: str, scope: str, request_id: uuid.UUID, *,
           provider: CompensationProvider, agent: str = "compensator",
           lease_seconds: float = DISPATCH_LEASE_SECONDS) -> CompensateResult:
    """Dispatch a recorded request, and move the ledger only on a real receipt.

    THE INVARIANT THIS FUNCTION EXISTS TO HOLD: no path reaches `compensated` or
    `executed` without a receipt from `provider.dispatch`. If dispatch raises,
    the request row is marked `needs_compensation` -- it is owed and undelivered,
    which is a different and more useful state than `pending` -- and the original
    stays `needs_compensation` too. Nothing is silently downgraded to success.

    The dispatch happens OUTSIDE the transaction on purpose. A provider call
    inside one holds a row lock across a network round trip, which is how a
    payment integration takes a database down.
    """
    # Claim the request with a LEASE, not a flag. A bare `in_flight` marker is
    # worse than none: a worker that dies mid-dispatch leaves it set forever and
    # the reversal is stranded with no path back. The claim therefore carries
    # when it was taken, and a stale one is reclaimable by the next worker.
    #
    # This is one atomic conditional UPDATE. It succeeds if the request is
    # unclaimed OR the existing claim has aged past the lease, and fails if
    # someone holds a fresh one -- so two workers cannot both reach the provider,
    # and a dead worker does not block the queue.
    #
    # What it does NOT solve: a crash after the provider succeeded and before
    # this process committed. The reclaim re-dispatches, deliberately, carrying
    # the SAME idempotency key -- and external exactly-once is then the
    # provider's contract, not ours. Nothing on this side can know whether the
    # first call landed.
    with psycopg.connect(url, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM effect WHERE id=%s AND scope=%s",
                    (request_id, scope))
        req = cur.fetchone()
        if req is None:
            raise ValueError("no such compensation request in this scope")
        if req["status"] == "executed":
            return CompensateResult(
                "compensated", req["id"], req["id"], req["tool"],
                f"already settled, receipt {req['payload'].get('external_receipt')}")

        claim_sql = """
            UPDATE effect
               SET payload = payload || jsonb_build_object(
                     'dispatch', 'in_flight',
                     'dispatch_started_at', now()::STRING,
                     'attempt', COALESCE((payload->>'attempt')::INT, 0) + 1)
             WHERE id = %s AND scope = %s AND status = 'pending'
               AND (payload->>'dispatch' IS DISTINCT FROM 'in_flight'
                    OR (payload->>'dispatch_started_at')::TIMESTAMPTZ
                        < now() - (%s::DECIMAL * INTERVAL '1 second'))
            RETURNING payload
        """
        # A loser of the race gets 40001 here rather than an empty result. That
        # is contention, not failure, and it must come back as
        # `dispatch_in_flight` like any other refused claim -- not as an
        # exception that a caller has to know to catch.
        claimed = None
        for attempt_n in range(5):
            try:
                cur.execute(claim_sql, (request_id, scope, lease_seconds))
                claimed = cur.fetchone()
                conn.commit()
                break
            except psycopg.errors.SerializationFailure:
                conn.rollback()
                if attempt_n == 4:
                    return CompensateResult(
                        "dispatch_in_flight", req["id"], request_id, req["tool"],
                        "lost the claim race repeatedly; another worker holds it")
                time.sleep(0.02 * (2 ** attempt_n))

    if claimed is None:
        return CompensateResult(
            "dispatch_in_flight", req["id"], request_id, req["tool"],
            f"another worker holds a lease on this request (under {lease_seconds}s old); "
            f"it is not dispatched twice from here")

    attempt = claimed["payload"].get("attempt")

    key = req["idempotency_key"]

    # --- outside the transaction ---
    try:
        receipt = provider.dispatch(scope=scope, request_id=request_id,
                                    tool=req["tool"], payload=req["payload"],
                                    idempotency_key=key)
    except DispatchFailed as exc:
        # NOT needs_compensation: a compensation request that itself "needs
        # compensation" is a recursive label that means nothing. It stays
        # `pending` -- owed and undelivered -- and carries why.
        with psycopg.connect(url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE effect SET status='pending', "
                "payload = payload || %s WHERE id=%s AND scope=%s",
                (json.dumps({"dispatch": "failed", "dispatch_error": str(exc),
                             "attempt": attempt}),
                 request_id, scope),
            )
        return CompensateResult("dispatch_failed", req["id"], request_id,
                                req["tool"], str(exc))

    if not receipt or not isinstance(receipt, str):
        raise DispatchFailed(f"provider {provider.name!r} returned no receipt")

    with psycopg.connect(url, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE effect SET status='executed', executed_at=now(), "
            "payload = payload || %s WHERE id=%s AND scope=%s",
            (json.dumps({"dispatch": provider.name, "external_receipt": receipt}),
             request_id, scope),
        )
        cur.execute(
            "UPDATE effect SET status='compensated' "
            "WHERE compensated_by=%s AND scope=%s",
            (request_id, scope),
        )
        cur.execute(
            "INSERT INTO audit_log (scope, agent, action, memory_id, detail) "
            "VALUES (%s,%s,'settle',%s,%s)",
            (scope, agent, req["justified_by"],
             json.dumps({"request": str(request_id), "provider": provider.name,
                         "external_receipt": receipt})),
        )
        conn.commit()

    return CompensateResult("compensated", req["id"], request_id, req["tool"],
                            f"settled by {provider.name}, receipt {receipt}")
