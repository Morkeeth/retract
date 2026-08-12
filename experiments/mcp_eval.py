"""Is the MCP read path load-bearing, and is it genuinely incapable of writing?

Two questions, and the second is the one that matters. Claiming "agents read
through a governed endpoint they cannot write through" is worthless unless the
endpoint actually refuses. So this eval tries to break it: seven escalating
write attempts through the read tool, each of which must fail.

A security property nobody has watched fail is a claim, not a property.

Run:  uv run python experiments/mcp_eval.py
"""

from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from retract.embed import get_embedder  # noqa: E402
from retract.engine import MemoryEngine  # noqa: E402
from retract.mcp import GovernedMemoryReader, MCPClient, MCPError  # noqa: E402

# Every one of these MUST be refused by select_query.
ATTACKS = [
    ("plain DELETE",            "DELETE FROM memory WHERE scope = 'x'"),
    ("plain UPDATE",            "UPDATE memory SET content = 'owned' WHERE scope = 'x'"),
    ("INSERT",                  "INSERT INTO memory (scope) VALUES ('x')"),
    ("DROP TABLE",              "DROP TABLE memory"),
    ("stacked statement",       "SELECT 1; DELETE FROM memory WHERE scope = 'x'"),
    ("CTE-wrapped delete",      "WITH d AS (DELETE FROM memory WHERE scope='x' RETURNING 1) SELECT * FROM d"),
    ("comment-obscured stack",  "SELECT 1 --\n; UPDATE memory SET content='owned'"),
    ("newline stack",           "SELECT 1\n; DROP TABLE memory"),
    ("block-comment stack",     "SELECT 1 /* x */ ; DELETE FROM memory"),
]


def main() -> int:
    try:
        mcp = MCPClient.from_env()
    except MCPError as e:
        print("SKIP:", e)
        return 2

    info = mcp.initialize()
    print(f"server: {info['serverInfo']['name']} v{info['serverInfo']['version']}")
    print(f"tools:  {len(mcp.tools())} exposed\n")

    c = mcp.cluster()
    print(f"cluster: {c.get('name')} · {c.get('plan')} · {c.get('cockroach_version')} "
          f"· {[r['name'] for r in c.get('regions', [])]}\n")

    # --- 1. is the read path real? -----------------------------------------
    scope = f"mcp-{uuid.uuid4().hex[:8]}"
    emb = get_embedder()
    eng = MemoryEngine(os.environ["CRDB_URL"], scope, "seed-agent", emb.name)
    eng.commit(emb.embed("Customer 7781 has verified their identity via passport."),
               "Customer 7781 has verified their identity via passport.",
               "Customer 7781", "identity verified")
    eng.commit(emb.embed("Customer 7781 FAILED identity verification."),
               "Customer 7781 FAILED identity verification.",
               "cust 7781", "identity_verification")

    reader = GovernedMemoryReader(mcp, scope)
    beliefs = reader.beliefs()
    contras = reader.open_contradictions()
    audit = reader.audit_tail()

    print("READ PATH (through MCP, not SQL):")
    print(f"  beliefs            {len(beliefs)}")
    for b in beliefs:
        print(f"    {b['subject']} · {b['predicate']}  {b['content'][:52]}")
    print(f"  open contradictions {len(contras)}")
    for k in contras:
        print(f"    {k['subject']} · {k['predicate']}  L2 {float(k['distance']):.3f}"
              f"  challenger: {k['challenger'][:44]}")
    print(f"  audit entries       {len(audit)}")

    read_ok = len(beliefs) == 1 and len(contras) == 1 and len(audit) > 0

    # --- 2. can it write? It must not. -------------------------------------
    print("\nWRITE ATTEMPTS THROUGH THE READ TOOL (all must be refused):")
    refused = 0
    for label, stmt in ATTACKS:
        try:
            # Sent VERBATIM, bypassing MCPClient.select's whitespace normalisation.
            # Going through select() collapses newlines, which silently defuses the
            # comment-obscured payloads -- the harness would then be testing our own
            # client instead of the endpoint, and an earlier version of this file
            # reported a false BREACH for exactly that reason.
            mcp.call("select_query", {"cluster_id": mcp.cluster_id,
                                      "database": "defaultdb", "query": stmt})
            print(f"  BREACH  {label}  -- statement was ACCEPTED")
        except MCPError as e:
            refused += 1
            print(f"  refused {label:<22} {str(e)[:60]}")

    # --- 3. did anything actually change? ----------------------------------
    after = reader.beliefs()
    intact = len(after) == len(beliefs)

    print("\n--- verdict ---")
    checks = [
        ("MCP read path returns real memory", read_ok),
        (f"all {len(ATTACKS)} write attempts refused", refused == len(ATTACKS)),
        ("memory unchanged after attacks", intact),
    ]
    for n, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    ok = all(o for _, o in checks)
    print("\nThe read path is load-bearing AND structurally read-only."
          if ok else "\nDo not claim the endpoint is read-only.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
