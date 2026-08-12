"""The eval, and the demo's two panes: N agents concluding the same fact at once.

Eight agents independently learn the same thing about a customer at the same
moment. They phrase it differently AND they extract the subject and predicate
differently -- "Customer 4471" vs "cust 4471" vs "4471", "identity verified" vs
"identity-verification". That spelling variance is not decoration: if
canonicalisation fails, the agents take different locks and every one of them
writes, which is precisely the bug the deterministic key exists to prevent.

    --mode naive     what everyone builds: read, think, insert.
    --mode retract   claim lock + adjudication under lock.

SUCCESS CRITERION, fixed before the engine was written: exactly ONE active
belief for the claim afterwards. Not "no errors", not "it ran". One belief.
The naive arm exists so the number means something -- if both arms land on 1,
the lock is doing nothing and the demo is theatre.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import uuid

import psycopg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from retract.embed import get_embedder  # noqa: E402
from retract.engine import MemoryEngine, vec_literal  # noqa: E402

# (content, subject-as-extracted, predicate-as-extracted)
CLAIMS = [
    ("Customer 4471 has verified their identity via passport.", "Customer 4471", "identity verified"),
    ("ID verification complete for customer 4471 (passport).",  "customer 4471", "identity_verified"),
    ("Cust 4471 identity confirmed, passport on file.",         "cust 4471",     "identity-verification"),
    ("Passport check passed for customer 4471.",                "CUSTOMER#4471", "Identity Verified"),
    ("Customer 4471: identity verified.",                       "4471",          "identity verification"),
    ("Verified customer 4471 using passport documentation.",    "Cust. 4471",    "IDENTITY VERIFIED"),
    ("Identity of customer 4471 established via passport.",     "customer_4471", "identity verified status"),
    ("4471 has now passed passport-based identity verification.", "Customer 4471", "identity_verification"),
]


def naive_write(url, scope, agent, emb, content, subject, predicate) -> str:
    """No lock, no adjudication. Read, think, insert. The common implementation."""
    with psycopg.connect(url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM memory WHERE scope=%s AND valid_to IS NULL "
            "ORDER BY embedding <-> %s::vector LIMIT 1",
            (scope, vec_literal(emb)),
        )
        cur.fetchall()
        time.sleep(0.4)  # think
        cur.execute(
            "INSERT INTO memory (scope, content, embedding, subject, predicate, "
            "embedder, author_agent, snapshot_ts) VALUES (%s,%s,%s::vector,%s,%s,'naive',%s,'0')",
            (scope, content, vec_literal(emb), subject, predicate, agent),
        )
    return "inserted"


def retract_write(url, scope, agent, emb, content, subject, predicate, embedder_name) -> str:
    eng = MemoryEngine(url, scope, agent, embedder_name)
    for attempt in range(6):
        try:
            eng.read(emb)
            time.sleep(0.4)  # think
            return eng.commit(emb, content, subject, predicate).outcome
        except psycopg.errors.SerializationFailure:
            # The client owns the retry loop: the commit phase is multi-round-trip,
            # so CockroachDB's automatic retry never fires for this workload.
            time.sleep(0.05 * (2 ** attempt))
    return "exhausted"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["naive", "retract"], required=True)
    ap.add_argument("--agents", type=int, default=8)
    args = ap.parse_args()

    url = os.environ["CRDB_URL"]
    scope = f"race-{args.mode}-{uuid.uuid4().hex[:8]}"
    embedder = get_embedder(os.environ.get("RETRACT_EMBEDDER", "local"))
    vectors = embedder.embed_many([c[0] for c in CLAIMS])

    results: list[str] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        content, subject, predicate = CLAIMS[i % len(CLAIMS)]
        emb = vectors[i % len(CLAIMS)]
        if args.mode == "naive":
            out = naive_write(url, scope, f"agent-{i}", emb, content, subject, predicate)
        else:
            out = retract_write(url, scope, f"agent-{i}", emb, content, subject,
                                predicate, embedder.name)
        with lock:
            results.append(out)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(args.agents)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - t0

    with psycopg.connect(url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM memory WHERE scope=%s AND valid_to IS NULL "
                    "AND status='active'", (scope,))
        active = cur.fetchone()[0]
        cur.execute("SELECT count(DISTINCT (subject, predicate)) FROM memory WHERE scope=%s", (scope,))
        keys = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM contradiction WHERE scope=%s", (scope,))
        contras = cur.fetchone()[0]

    print(f"\nmode={args.mode}  embedder={embedder.name}  agents={args.agents}  {elapsed:.1f}s")
    print(f"outcomes:       { {o: results.count(o) for o in set(results)} }")
    print(f"distinct claim keys written: {keys}   (correct: 1 -- canonicalisation)")
    print(f"contradictions raised:       {contras}")
    print(f"\nACTIVE BELIEFS: {active}   (correct answer: 1)")
    print("PASS" if active == 1 else f"FAIL -- {active - 1} duplicate belief(s) about one fact")
    return 0 if active == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
