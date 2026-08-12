"""Day-1 experiment: does an ANN read participate in transaction conflict detection?

The claim under test (RETRACT's headline):

    A serializable transaction that performs an ANN search over a C-SPANN vector
    index acquires read spans covering the touched index partitions. A concurrent
    insert of a SEMANTICALLY NEAR vector should therefore force a 40001 retry,
    while a concurrent insert of a SEMANTICALLY FAR vector should not.

Nothing in the product depends on this being true -- durable bucket locking is the
correctness path. This experiment decides whether the vector index gives us the
same guarantee for free, and we report the finding either way.

Design notes, so the result means something:

  * There are TWO arms. NEAR is the treatment, FAR is the control. A run where
    both arms abort at the same rate proves range-level contention, NOT semantic
    conflict detection -- that is a failed hypothesis dressed as a success, and
    it is exactly the trap this control exists to catch.
  * The B session commits INSIDE A's open transaction window, after A's ANN read
    and before A's write. If B commits outside that window there is nothing to
    conflict with and every trial trivially succeeds.
  * Vectors are placed on a line so "near" and "far" are unambiguous, and the
    table is seeded so the index has real partitions rather than a single leaf.

Usage:
    CRDB_URL='postgresql://...' uv run experiments/day1_conflict.py [--trials N]
"""

from __future__ import annotations

import argparse
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field

import psycopg

DIM = 16
SEED_ROWS = 2000
# A's probe sits at the origin. NEAR inserts land inside its neighbourhood;
# FAR inserts land on the opposite side of the seeded cloud.
PROBE = [0.0] * DIM
NEAR_CENTRE = 0.02
FAR_CENTRE = 8.0


def vec(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in values) + "]"


def jitter(centre: float, scale: float = 0.005) -> list[float]:
    return [random.gauss(centre, scale) for _ in range(DIM)]


def is_retry_error(exc: BaseException) -> bool:
    return getattr(exc, "sqlstate", None) == "40001"


def fisher_one_sided(a: int, b: int, c: int, d: int) -> float:
    """One-sided Fisher exact test, P(treatment aborts >= observed | no effect).

    Table: [[near_aborts, near_commits], [far_aborts, far_commits]].
    Eyeballing "28% vs 8%" is how a 7-vs-2 split becomes a headline claim.
    This makes the threshold a number instead of a feeling.
    """
    n = a + b + c + d
    row1, col1 = a + b, a + c
    total = 0.0
    hi = min(row1, col1)
    for k in range(a, hi + 1):
        total += (
            math.comb(row1, k)
            * math.comb(n - row1, col1 - k)
            / math.comb(n, col1)
        )
    return total


@dataclass
class ArmResult:
    name: str
    trials: int = 0
    aborts: int = 0
    commits: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> int:
        """Trials that actually exercised the interleaving."""
        return self.aborts + self.commits

    @property
    def rate(self) -> float:
        # Denominator is VALID trials, never attempted ones. A harness that
        # errors on every trial must not be able to report a 0% abort rate.
        return self.aborts / self.valid if self.valid else 0.0


def setup(conn: psycopg.Connection) -> dict[str, object]:
    """Create the table and index. Reports what the tier actually supports."""
    facts: dict[str, object] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT version()")
        facts["version"] = cur.fetchone()[0]
        cur.execute("SHOW default_transaction_isolation")
        facts["isolation"] = cur.fetchone()[0]

        cur.execute("DROP TABLE IF EXISTS memory_probe")
        cur.execute(
            f"""
            CREATE TABLE memory_probe (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                scope STRING NOT NULL,
                content STRING NOT NULL,
                embedding VECTOR({DIM}) NOT NULL
            )
            """
        )

        # Index FIRST, seed second. A vector-index backfill on a non-empty table
        # blocks writes and cannot be created online, so seeding first would
        # stall the setup on a table this size.
        try:
            cur.execute("CREATE VECTOR INDEX ON memory_probe (embedding)")
            facts["vector_index"] = "created"
        except psycopg.Error as exc:
            facts["vector_index"] = f"FAILED: {exc.sqlstate} {exc}"
            conn.rollback()
            return facts
    conn.commit()

    rows = [
        (f"seed-{i}", vec(jitter(random.uniform(-1.0, 9.0), 0.35)))
        for i in range(SEED_ROWS)
    ]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO memory_probe (scope, content, embedding) VALUES ('probe', %s, %s)",
            rows,
        )
    conn.commit()
    facts["seeded"] = SEED_ROWS
    return facts


def one_trial(url: str, centre: float, hold_ms: int) -> tuple[str, str | None]:
    """Run one interleaving. Returns (outcome, error) where outcome is
    'abort' (40001), 'commit', or 'error' (the trial never ran)."""
    a = psycopg.connect(url, autocommit=False)
    b = psycopg.connect(url, autocommit=True)
    try:
        with a.cursor() as cur_a:
            # No explicit BEGIN: psycopg opens the transaction on first execute
            # when autocommit=False. An explicit BEGIN raises 25001 and silently
            # invalidates every trial.
            # READ PHASE: the ANN search whose read spans are the thing under test.
            cur_a.execute(
                "SELECT id FROM memory_probe ORDER BY embedding <-> %s::vector LIMIT 10",
                (vec(PROBE),),
            )
            cur_a.fetchall()

            # B commits a concurrent insert INSIDE A's window.
            with b.cursor() as cur_b:
                cur_b.execute(
                    "INSERT INTO memory_probe (scope, content, embedding) VALUES ('probe', 'interloper', %s::vector)",
                    (vec(jitter(centre)),),
                )

            time.sleep(hold_ms / 1000.0)

            # WRITE PHASE: A commits its own conclusion.
            cur_a.execute(
                "INSERT INTO memory_probe (scope, content, embedding) VALUES ('probe', 'winner', %s::vector)",
                (vec(jitter(NEAR_CENTRE)),),
            )
            a.commit()
        return "commit", None
    except psycopg.Error as exc:
        a.rollback()
        if is_retry_error(exc):
            return "abort", None
        return "error", f"{exc.sqlstate} {exc}"
    finally:
        a.close()
        b.close()


def run_arm(url: str, name: str, centre: float, trials: int, hold_ms: int) -> ArmResult:
    res = ArmResult(name=name)
    for i in range(trials):
        outcome, err = one_trial(url, centre, hold_ms)
        res.trials += 1
        if outcome == "abort":
            res.aborts += 1
        elif outcome == "commit":
            res.commits += 1
        if err and len(res.errors) < 5:
            res.errors.append(err)
        label = {"abort": "40001", "commit": "committed", "error": "ERROR (trial void)"}[outcome]
        print(f"  {name} trial {i + 1}/{trials}: {label}", flush=True)
    return res


def check_retry_injection(url: str) -> str:
    """inject_retry_errors_enabled is how the retry loop gets PROVEN, not asserted."""
    try:
        conn = psycopg.connect(url, autocommit=True)
        with conn.cursor() as cur:
            cur.execute("SET inject_retry_errors_enabled = true")
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            conn.commit()
            return "enabled but no error injected"
        except psycopg.Error as exc:
            conn.rollback()
            return "injects 40001 on demand" if is_retry_error(exc) else f"raised {exc.sqlstate}: {exc}"
        finally:
            conn.close()
    except psycopg.Error as exc:
        return f"UNAVAILABLE: {exc.sqlstate} {exc}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=25)
    ap.add_argument("--hold-ms", type=int, default=150)
    args = ap.parse_args()

    url = os.environ.get("CRDB_URL")
    if not url:
        print("CRDB_URL not set", file=sys.stderr)
        return 2

    random.seed(7)

    with psycopg.connect(url, autocommit=False) as conn:
        facts = setup(conn)

    print("\n=== CLUSTER ===")
    for k, v in facts.items():
        print(f"{k}: {v}")
    if str(facts.get("vector_index", "")).startswith("FAILED"):
        print("\nVerdict: vector index unavailable on this tier. Hypothesis untestable here.")
        return 1

    print(f"\n=== ARMS ({args.trials} trials each, {args.hold_ms}ms hold) ===")
    near = run_arm(url, "NEAR(treatment)", NEAR_CENTRE, args.trials, args.hold_ms)
    far = run_arm(url, "FAR (control)  ", FAR_CENTRE, args.trials, args.hold_ms)

    print("\n=== RESULT ===")
    for arm in (near, far):
        voids = arm.trials - arm.valid
        print(f"{arm.name}: {arm.aborts}/{arm.valid} valid trials aborted with 40001 ({arm.rate:.0%})"
              f"   [{voids} void]")
        for e in arm.errors:
            print(f"    error: {e}")

    print(f"\ninject_retry_errors_enabled: {check_retry_injection(url)}")

    print("\n=== VERDICT ===")
    # A harness that errored has no finding. Refuse to render one -- this is the
    # exact failure mode that produced a confident false 'REFUTED' on the first run.
    if near.valid < args.trials or far.valid < args.trials:
        print("NO FINDING. Some trials never exercised the interleaving.")
        print(f"Valid: near {near.valid}/{args.trials}, far {far.valid}/{args.trials}.")
        print("Fix the harness before reading anything into these numbers.")
        return 1

    p = fisher_one_sided(near.aborts, near.commits, far.aborts, far.commits)
    lift = (near.rate / far.rate) if far.rate else float("inf")
    print(f"near {near.rate:.0%} vs far {far.rate:.0%}   lift {lift:.1f}x   Fisher one-sided p = {p:.4f}")

    if p >= 0.05:
        print("\nNOT SIGNIFICANT. The gap is consistent with chance at this n.")
        print("No claim may rest on this. Durable bucket locking carries correctness.")
    elif far.rate >= 0.5:
        print("\nREFUTED -- the trap the control exists to catch.")
        print("Both arms abort heavily: this is range-level contention, not semantic")
        print("conflict detection. Reporting the treatment alone would have been a lie.")
    else:
        print("\nSUPPORTED. Near inserts conflict significantly more than far inserts.")
        print("The ANN read participates in conflict detection -- as a MEASURED")
        print("optimisation, not a guarantee. Bucket locking still carries correctness.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
