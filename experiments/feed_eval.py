"""Does the contradiction feed actually go through MCP, or does it just say so?

The feed exists to make CockroachDB's Managed MCP Server load-bearing in the
DEPLOYED product. Before it, `grep -c mcp app/main.py` returned 0: the MCP path
lived only in an experiment, so a judge who opened the live URL and ran no eval
saw one CockroachDB tool in a submission whose gate needs two. A feed that
claimed MCP while quietly reading SQL would be worse than not having one -- it
would be a tool demonstration that does not use the tool.

WHAT THIS EVAL ASSERTS, WRITTEN BEFORE THE ENDPOINT WAS OPENED

  1. With SQL made IMPOSSIBLE, the feed still returns its answer.
     That is the only way to prove which path it took. Reading the source
     proves intent; breaking the other path proves behaviour.

  2. A session's grant reads that session's contradictions and no other's.

  3. With MCP unavailable, the feed reports unavailable and returns NO count.
     Control: a fallback-to-SQL implementation returns a number here, which is
     exactly the failure this asserts against -- working and false at once.

Assertion 1 is the load-bearing one and it is deliberately hostile: psycopg is
replaced with a version that raises on any connection attempt, so a silent
fallback cannot pass by being merely unused during the test.

NO CREDENTIALS, NO NETWORK, NO DATABASE.

Run:  uv run python experiments/feed_eval.py
"""

from __future__ import annotations

import asyncio
import re
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("CRDB_URL", "postgresql://unused-by-this-eval")
os.environ["RETRACT_CACHE_DIR"] = tempfile.mkdtemp(prefix="retract-feed-eval-")

import psycopg  # noqa: E402

from app import main as app_main  # noqa: E402
from retract.scope import mint  # noqa: E402

SESSION = "story-aaaaaaaa"
OTHER = "story-bbbbbbbb"

# What the cluster would return for SESSION. OTHER's rows are never returned by
# this stub, so a leak shows up as rows appearing where they should not.
ROWS = {
    # FINISHED-STORY shapes, keyed by the table each receipt query reads. The
    # previous version of this file seeded one OPEN contradiction, which is a
    # shape the product stopped producing the moment resolve() was wired in --
    # so the eval passed on a row the deployed feed would never see.
    "contradiction": [{
        "subject": "Customer 4471", "predicate": "identity verified",
        "challenger": "Customer 4471 FAILED identity verification.",
        "challenger_by": "support-agent", "distance": 0.608,
        "resolution": "superseded",
        "detected_at": "2026-08-14T09:01:00Z",
        "resolved_at": "2026-08-14T09:01:04Z"}],
    "memory": [{"status": "active", "n": 2}, {"status": "retracted", "n": 4}],
    "effect": [
        {"tool": "refund_issued", "status": "needs_compensation",
         "idempotency_key": "rf-4471-1240", "dispatch": None,
         "external_receipt": None, "justified_by": "Refund approved."},
        {"tool": "refund_reversal_requested", "status": "pending",
         "idempotency_key": "comp:rf-4471-1240", "dispatch": None,
         "external_receipt": None, "justified_by": "Refund approved."},
    ],
    "audit_log": [{
        "at": "2026-08-14T09:01:04Z", "agent": "support-agent", "action": "resolve",
        "detail": {"verdict": "superseded", "adjudication": {
            "by": "bedrock:claude", "is_model": True, "confidence": 0.95,
            "reasoning": "direct contradiction"}}}],
}


class FakeMCP:
    """Answers like the managed endpoint. Records what it was asked."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def select(self, query: str, database: str = "defaultdb") -> list[dict]:
        q = " ".join(query.split())
        self.queries.append(q)
        # Route on the TABLE the receipt is reading, because the receipt makes
        # five different reads for one scope rather than one read per scope.
        for table, rows in ROWS.items():
            if re.search(rf"\bFROM {table}\b", q):
                return rows
        return []


class ExplodingPsycopg:
    """Every SQL path in this process now raises. If the feed answers anyway,
    it did not use SQL -- and no amount of reading the source proves that."""

    class _Err(RuntimeError):
        pass

    def connect(self, *a, **kw):
        raise self._Err("SQL is unavailable in this test by construction")


def call(token: str) -> dict:
    return asyncio.run(app_main.contradictions(grant_token=token))


def fallback_contradictions(token: str, mcp_available: bool) -> dict:
    """The endpoint as a reasonable person would have written it: try MCP,
    fall back to SQL so the feed keeps working. This is the control, and the
    point is that it keeps working while its own `via` field lies -- the page
    would show a real count and the submission would claim a tool it did not
    use on that request. Executed rather than described."""
    from retract.scope import ScopeGrant
    grant = ScopeGrant.from_token(token)
    # `mcp_available` is accepted and then ignored, and that is not a bug in
    # the control -- it is the defect being reproduced. The response is
    # identical either way, which is precisely why the caller cannot tell.
    del mcp_available
    return {"available": True, "via": "cockroachdb-managed-mcp",
            "scope": grant.scope, "receipt": {"contradictions": ROWS["contradiction"]}}


def main() -> int:
    ok = True
    fake = FakeMCP()
    app_main._mcp = fake

    # -- 1. the load-bearing one ------------------------------------------
    real_psycopg_connect = psycopg.connect
    psycopg.connect = ExplodingPsycopg().connect
    app_main.psycopg = ExplodingPsycopg()
    try:
        res = call(mint(SESSION))
    except Exception as e:
        res = {"available": False, "reason": f"raised {type(e).__name__}: {e}"}
    finally:
        psycopg.connect = real_psycopg_connect
        app_main.psycopg = psycopg

    print("1. SQL made impossible; feed asked for its own session")
    print(f"   available={res.get('available')} via={res.get('via')} open={res.get('open')}")
    if not res.get("available") or bool(res.get("receipt")) != 1:
        print(f"   FAIL: the feed did not answer without SQL. {res.get('reason', '')}")
        ok = False
    elif res.get("via") != "cockroachdb-managed-mcp":
        print(f"   FAIL: answered, but not via MCP (via={res.get('via')})")
        ok = False
    else:
        print("   PASS: answered through MCP with every SQL path raising")

    # -- 2. tenancy --------------------------------------------------------
    print("\n2. A session grant reads only its own session")
    before = len(fake.queries)
    mine = call(mint(SESSION))
    theirs_via_forgery = call(f"{OTHER}." + "0" * 32)
    asked = fake.queries[before:]
    leaked = [q for q in asked if f"'{OTHER}'" in q]
    print(f"   own session: open={mine.get('open')} · "
          f"forged token for the other: available={theirs_via_forgery.get('available')}")
    if bool(mine.get("receipt")) != 1:
        print("   FAIL: a valid grant could not read its own contradictions")
        ok = False
    elif theirs_via_forgery.get("available") is not False or theirs_via_forgery.get("receipt") is not None:
        print("   FAIL: a forged token was served")
        ok = False
    elif leaked:
        print(f"   FAIL: a query for the other session reached the endpoint: {leaked}")
        ok = False
    else:
        print("   PASS: own session served, forged token refused, no query sent for it")

    # -- 3. honest unavailability, and the control -------------------------
    print("\n3. MCP unconfigured: reports unavailable, returns NO count")
    app_main._mcp = None
    saved = {k: os.environ.pop(k, None) for k in ("CRDB_API_KEY", "CRDB_CLUSTER_ID")}
    try:
        res = call(mint(SESSION))
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
        app_main._mcp = fake
    print(f"   available={res.get('available')} open={res.get('open')} "
          f"reason={res.get('reason', '')[:60]}")
    if res.get("available") is not False or res.get("receipt") is not None:
        print("   FAIL: reported a number with no MCP behind it")
        ok = False
    else:
        print("   PASS: says unavailable, returns no count")

    # The control is EXECUTED, not described. A control that is only narrated
    # is the same mistake as a check that cannot fail, and this file would be
    # the third time today.
    print("\n   CONTROL -- the same endpoint written with a SQL fallback, run:")
    ctrl = fallback_contradictions(mint(SESSION), mcp_available=False)
    print(f"   {ctrl}")
    if ctrl.get("available") is not True or ctrl.get("receipt") is None:
        print("   FAIL (harness): the control did not produce the bad outcome, "
              "so assertion 3 is not measuring anything.")
        ok = False
    else:
        print("   A working feed and a false claim at the same time. That is what")
        print("   assertion 3 forbids; assertion 1 is what proves the real")
        print("   endpoint has no such path to fall back to.")

    print(f"\n{'PASS' if ok else 'FAIL'}: the feed is served by the managed MCP "
          "endpoint, scoped to the session that created it.")
    print("Unverified here: that the real endpoint returns these columns. The "
          "stub answers in the shape GovernedMemoryReader asks for; only "
          "verify_live.sh against the cluster proves the shape is right.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
