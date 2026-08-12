"""RETRACT's memory engine: three-phase commit, contradiction detection, and
the retraction cascade.

WHY THREE PHASES
An agent's turn spans LLM inference, which takes seconds to minutes. You cannot
hold a database transaction open across it -- you would either block every other
agent or abort constantly. So the turn is split:

    READ    ANN search at a recorded snapshot. No locks. Cheap.
    THINK   The LLM decides, and names the claim it wants to assert.
    COMMIT  A short serializable transaction: lock the claim key, look at what
            is already believed, then write or raise a contradiction.

WHAT THE DATABASE GUARANTEES, AND WHAT IT DOES NOT
It guarantees that exactly one agent adjudicates a given (subject, predicate)
at a time, and that the outcome is recorded atomically with the memory and the
side effects it touches. It does not guarantee the adjudication is correct --
that is the model's job.

That split exists because of a measurement. On real embeddings:

    "Customer 4471 verified"   vs "Customer 4472 verified"     L2 0.172
    "9902 lives in Berlin"     vs "9902 USED TO live in Berlin" L2 0.296
    paraphrases of one fact                                    L2 0.323 - 0.843

Different facts sit closer than paraphrases of the same fact. No threshold
separates them. So embedding distance is never allowed to decide identity here;
it is recorded alongside a contradiction as a hint for whoever resolves it.

We also measured whether the vector index alone would serialise concurrent
adjacent writes -- it does not, at any useful rate (FINDINGS.md). Hence the
explicit durable lock.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Sequence

import numpy as np
import psycopg
from psycopg.rows import dict_row

from .claim import claim_key


def vec_literal(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


@dataclass
class Neighbour:
    id: uuid.UUID
    content: str
    subject: str
    predicate: str
    distance: float


@dataclass
class ReadResult:
    neighbours: list[Neighbour]
    snapshot_ts: str


@dataclass
class CommitResult:
    outcome: str                       # 'inserted' | 'duplicate' | 'contradiction'
    memory_id: uuid.UUID | None = None
    incumbent_id: uuid.UUID | None = None
    incumbent_content: str | None = None
    contradiction_id: uuid.UUID | None = None
    distance: float | None = None


class MemoryEngine:
    # Below this L2 distance, two claims on the SAME key are treated as the same
    # wording and quietly dropped. It is deliberately tight: measured paraphrase
    # distances start at 0.323 and a genuine negation was seen at 0.296, so this
    # cutoff is set to catch only near-identical strings. Everything else goes to
    # adjudication. Erring toward surfacing is the correct bias for a memory.
    IDENTICAL = 0.15

    def __init__(self, url: str, scope: str, agent: str, embedder_name: str = "unknown"):
        self.url = url
        self.scope = scope
        self.agent = agent
        self.embedder_name = embedder_name

    def _connect(self, autocommit: bool = False) -> psycopg.Connection:
        conn = psycopg.connect(self.url, autocommit=autocommit, row_factory=dict_row)
        with conn.cursor() as cur:
            # Unreplicated FOR UPDATE locks are documented as best-effort and
            # explicitly "should not be relied upon for correctness" -- a lease
            # transfer or range split drops them. This makes them durable.
            cur.execute("SET enable_durable_locking_for_serializable = true")
        if not autocommit:
            conn.commit()
        return conn

    # ---------------------------------------------------------------- READ ---
    def read(self, embedding: np.ndarray, k: int = 10) -> ReadResult:
        """ANN search over the vector index. No locks survive this call."""
        with self._connect(autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("SELECT cluster_logical_timestamp()::STRING AS ts")
            snapshot_ts = cur.fetchone()["ts"]
            cur.execute(
                """
                SELECT id, content, subject, predicate,
                       embedding <-> %s::vector AS distance
                FROM memory
                WHERE scope = %s AND valid_to IS NULL AND status = 'active'
                ORDER BY embedding <-> %s::vector
                LIMIT %s
                """,
                (vec_literal(embedding), self.scope, vec_literal(embedding), k),
            )
            rows = cur.fetchall()
        return ReadResult(
            [Neighbour(r["id"], r["content"], r["subject"], r["predicate"], float(r["distance"]))
             for r in rows],
            snapshot_ts,
        )

    # -------------------------------------------------------------- COMMIT ---
    def commit(
        self,
        embedding: np.ndarray,
        content: str,
        subject: str,
        predicate: str,
        derived_from: Sequence[uuid.UUID] = (),
    ) -> CommitResult:
        """Assert a claim. Exactly one agent holds a given claim key at a time."""
        subj, pred = claim_key(subject, predicate)

        with self._connect() as conn, conn.cursor() as cur:
            # 1. Take the claim lock. Upsert first: a key nobody has asserted
            #    yet has no row to lock.
            cur.execute(
                "INSERT INTO claim_key (scope, subject, predicate) VALUES (%s,%s,%s) "
                "ON CONFLICT DO NOTHING",
                (self.scope, subj, pred),
            )
            cur.execute(
                "SELECT revision FROM claim_key WHERE scope=%s AND subject=%s AND predicate=%s "
                "FOR UPDATE",
                (self.scope, subj, pred),
            )

            # 2. What is already believed about this exact claim?
            cur.execute(
                """
                SELECT id, content, embedding <-> %s::vector AS distance
                FROM memory
                WHERE scope=%s AND subject=%s AND predicate=%s
                  AND valid_to IS NULL AND status='active'
                ORDER BY recorded_at DESC LIMIT 1
                """,
                (vec_literal(embedding), self.scope, subj, pred),
            )
            incumbent = cur.fetchone()

            if incumbent is not None:
                dist = float(incumbent["distance"])
                if dist <= self.IDENTICAL:
                    self._audit(cur, "duplicate", incumbent["id"],
                                {"distance": dist, "dropped": content})
                    conn.commit()
                    return CommitResult("duplicate", None, incumbent["id"],
                                        incumbent["content"], None, dist)

                # Not near-identical. Distance cannot tell us whether this is a
                # rephrasing or a negation, so it does not get to decide.
                cur.execute(
                    "INSERT INTO contradiction (scope, subject, predicate, incumbent_id, "
                    "challenger, challenger_by, distance) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                    "RETURNING id",
                    (self.scope, subj, pred, incumbent["id"], content, self.agent, dist),
                )
                cid = cur.fetchone()["id"]
                self._audit(cur, "contradiction", incumbent["id"],
                            {"distance": dist, "challenger": content, "contradiction": str(cid)})
                conn.commit()
                return CommitResult("contradiction", None, incumbent["id"],
                                    incumbent["content"], cid, dist)

            # 3. Nothing believed yet. Write it.
            new_id = uuid.uuid4()
            cur.execute(
                "INSERT INTO memory (id, scope, content, embedding, bucket, subject, predicate, "
                "embedder, author_agent, snapshot_ts) VALUES (%s,%s,%s,%s::vector,0,%s,%s,%s,%s,%s)",
                (new_id, self.scope, content, vec_literal(embedding), subj, pred,
                 self.embedder_name, self.agent, "0"),
            )
            if derived_from:
                cur.executemany(
                    "INSERT INTO derivation (child_id, parent_id) VALUES (%s,%s) "
                    "ON CONFLICT DO NOTHING",
                    [(new_id, p) for p in derived_from],
                )
            cur.execute(
                "UPDATE claim_key SET revision=revision+1, updated_at=now() "
                "WHERE scope=%s AND subject=%s AND predicate=%s",
                (self.scope, subj, pred),
            )
            self._audit(cur, "commit", new_id, {"subject": subj, "predicate": pred})
            conn.commit()

        return CommitResult("inserted", new_id)

    # ------------------------------------------------------------- RESOLVE ---
    def resolve(self, contradiction_id: uuid.UUID, verdict: str,
                embedding: np.ndarray | None = None) -> CommitResult:
        """Adjudicate a contradiction under the same claim lock.

        verdict 'superseded' -> the challenger wins; the incumbent is closed and
                                the challenger written, in one transaction.
        verdict 'rejected'   -> the incumbent stands.
        verdict 'duplicate'  -> it was a rephrasing after all.
        """
        if verdict not in ("superseded", "rejected", "duplicate"):
            raise ValueError(verdict)

        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM contradiction WHERE id=%s AND scope=%s",
                        (contradiction_id, self.scope))
            c = cur.fetchone()
            if c is None or c["resolution"] != "open":
                raise ValueError("no open contradiction with that id")

            cur.execute(
                "SELECT revision FROM claim_key WHERE scope=%s AND subject=%s AND predicate=%s "
                "FOR UPDATE",
                (self.scope, c["subject"], c["predicate"]),
            )

            new_id = None
            if verdict == "superseded":
                if embedding is None:
                    raise ValueError("superseding requires the challenger's embedding")
                new_id = uuid.uuid4()
                cur.execute(
                    "INSERT INTO memory (id, scope, content, embedding, bucket, subject, "
                    "predicate, embedder, author_agent, snapshot_ts) "
                    "VALUES (%s,%s,%s,%s::vector,0,%s,%s,%s,%s,%s)",
                    (new_id, self.scope, c["challenger"], vec_literal(embedding),
                     c["subject"], c["predicate"], self.embedder_name, self.agent, "0"),
                )
                cur.execute(
                    "UPDATE memory SET valid_to=now(), status='superseded', superseded_by=%s "
                    "WHERE id=%s",
                    (new_id, c["incumbent_id"]),
                )

            cur.execute(
                "UPDATE contradiction SET resolution=%s, resolved_at=now() WHERE id=%s",
                (verdict, contradiction_id),
            )
            self._audit(cur, "resolve", c["incumbent_id"],
                        {"verdict": verdict, "contradiction": str(contradiction_id)})
            conn.commit()

        return CommitResult(verdict, new_id, c["incumbent_id"], c["content"] if "content" in c else None)

    # ------------------------------------------------------------ RETRACT ---
    def retract(self, memory_id: uuid.UUID, reason: str) -> dict:
        """Take a belief back, and everything that rested on it.

        Concurrency control stops a bad fact being WRITTEN. This reaches the bad
        fact that was already written and already acted on. One transaction:
        retract the belief and every descendant, cancel their pending side
        effects, and surface the already-executed ones for compensation.
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                WITH RECURSIVE fallout(id) AS (
                    SELECT %s::UUID
                  UNION
                    SELECT d.child_id FROM derivation d JOIN fallout f ON d.parent_id = f.id
                )
                SELECT id FROM fallout
                """,
                (memory_id,),
            )
            ids = [r["id"] for r in cur.fetchall()]

            cur.execute(
                "UPDATE memory SET status='retracted', valid_to=now() "
                "WHERE id = ANY(%s) AND scope=%s",
                (ids, self.scope),
            )
            cur.execute(
                "UPDATE effect SET status='cancelled' "
                "WHERE justified_by = ANY(%s) AND status='pending' RETURNING id",
                (ids,),
            )
            cancelled = [r["id"] for r in cur.fetchall()]
            cur.execute(
                "UPDATE effect SET status='needs_compensation' "
                "WHERE justified_by = ANY(%s) AND status='executed' RETURNING id, tool, payload",
                (ids,),
            )
            compensate = cur.fetchall()

            self._audit(cur, "retract", memory_id, {
                "reason": reason,
                "beliefs_retracted": len(ids),
                "effects_cancelled": len(cancelled),
                "effects_needing_compensation": len(compensate),
            })
            conn.commit()

        return {"retracted": ids, "cancelled": cancelled, "needs_compensation": compensate}

    # ---------------------------------------------------------------------- #
    def _audit(self, cur, action: str, memory_id, detail: dict) -> None:
        cur.execute(
            "INSERT INTO audit_log (scope, agent, action, memory_id, detail) "
            "VALUES (%s,%s,%s,%s,%s)",
            (self.scope, self.agent, action, memory_id, json.dumps(detail)),
        )
