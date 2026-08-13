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
import uuid
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

# tool that caused the damage -> tool that undoes it.
# Keep this small and obvious. A missing entry is a control, not an error:
# the original effect stays `needs_compensation` and is surfaced.
COMPENSATIONS: dict[str, str] = {
    "refund_issued": "refund_reversed",
    "tier_upgrade": "tier_downgrade",
    "welcome_email": "correction_email",
}


@dataclass
class CompensateResult:
    outcome: str  # 'compensated' | 'already_compensated' | 'no_handler' | 'not_eligible'
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
                "already_compensated", row["id"], row["compensated_by"],
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
        }

        # INSERT ... ON CONFLICT so a retry after a crash that wrote the
        # reversal but missed the status update finds the existing row rather
        # than failing the UNIQUE constraint and leaving the original flagged.
        cur.execute(
            "INSERT INTO effect (id, scope, justified_by, tool, payload, "
            "idempotency_key, status, executed_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,'executed', now()) "
            "ON CONFLICT (scope, idempotency_key) DO NOTHING "
            "RETURNING id",
            (rev_id, scope, row["justified_by"], compensating_tool,
             json.dumps(payload), rev_key),
        )
        inserted = cur.fetchone()
        if inserted is None:
            cur.execute(
                "SELECT id FROM effect WHERE scope=%s AND idempotency_key=%s",
                (scope, rev_key),
            )
            rev_id = cur.fetchone()["id"]

        cur.execute(
            "UPDATE effect SET status='compensated', compensated_by=%s "
            "WHERE id=%s AND scope=%s",
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
        "compensated", row["id"], rev_id, compensating_tool,
        f"{row['tool']} -> {compensating_tool}",
    )
