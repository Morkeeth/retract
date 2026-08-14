"""Run the real story, then read that exact session back through the real MCP.

WHY THIS EXISTS RATHER THAN AN EXTENSION OF feed_eval
`experiments/feed_eval.py` fakes MCP entirely, on purpose: it makes SQL
impossible and proves the endpoint cannot fall back. That is a good control and
it stays. What it cannot do is notice that the SHAPE it feeds the endpoint is a
shape the product never produces. It seeded one open contradiction, the product
resolves its contradiction, and so the eval passed while the deployed feed
returned nothing.

That is an assertion coming from the test rather than from the task, and it is
why running the suite did not catch the defect.

So this file seeds NOTHING. It drives `_story_events` -- the same function the
deployed endpoint drives -- and then asks the live Managed MCP Server for what
that story just produced. If the receipt cannot describe a session the product
actually created, the read is decorative, whatever the endpoint returns.

WHAT THE RECEIPT MUST CARRY, and each one is a question a judge asks
  the contradiction, RESOLVED, with the resolution and who chose it
  what the memory believes now
  the effects reached and still owed a reversal
  the reversal requests, their idempotency keys, and whether anything dispatched
  an audit trail

AND IT MUST FAIL CLOSED. With MCP unavailable the endpoint returns
available=false and no receipt. It does not fall back to SQL and it does not
return an empty receipt that reads like an empty session.

    CRDB_URL=... CRDB_API_KEY=... CRDB_CLUSTER_ID=... RETRACT_EMBEDDER=bedrock \\
      uv run python experiments/receipt_eval.py
"""

from __future__ import annotations

import asyncio
import os
import queue
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.main as M  # noqa: E402
from retract.embed import get_embedder  # noqa: E402


def run_the_real_story() -> dict:
    """Drive the product. No seeding, no constructed rows."""
    if M._embedder is None:
        M._embedder = get_embedder(os.environ.get("RETRACT_EMBEDDER", "bedrock"))
    if M._adjudicator is None:
        from retract.adjudicate import get_adjudicator
        M._adjudicator = get_adjudicator()

    q: "queue.Queue[dict]" = queue.Queue()
    M._story_events(q)
    events = []
    while not q.empty():
        events.append(q.get())
    return {"events": events,
            "done": next(e for e in events if e["type"] == "done")}


def main() -> int:
    for var in ("CRDB_API_KEY", "CRDB_CLUSTER_ID"):
        if not os.environ.get(var):
            print(f"{var} unset — this eval needs the real MCP endpoint, and a "
                  f"faked one would be the defect it exists to catch.")
            return 2

    print("Driving the real story, then reading its session through MCP.\n")
    ran = run_the_real_story()
    done = ran["done"]
    grant = done["scope_token"]
    print(f"  story ran: scope {done['scope']}  retracted={done.get('retracted')} "
          f"recorded={done.get('recorded')} unreachable={done.get('unreachable')}")

    res = asyncio.run(M.contradictions(grant_token=grant))
    problems = []

    if not res.get("available"):
        print(f"\n  FAIL  the receipt was not available: {res.get('reason')}")
        return 1
    R = res.get("receipt") or {}

    contradictions = R.get("contradictions") or []
    resolved = [c for c in contradictions if c.get("resolution")
                and c["resolution"] != "open"]
    effects = R.get("effects") or []
    owed = [e for e in effects if e.get("status") == "needs_compensation"]
    requested = [e for e in effects if str(e.get("tool", "")).endswith("_requested")]
    memory = R.get("memory") or []
    audit = R.get("audit") or []

    if not contradictions:
        problems.append("no contradiction in the receipt for a story that raised one")
    if not resolved:
        problems.append("the contradiction is not resolved — the story calls "
                        "resolve(), so a receipt showing 'open' means the read is "
                        "not describing this session")
    # WHICH BACKEND DECIDED, read out of the database rather than out of the
    # stream. `challenger_by` is the agent that WROTE the challenger; it is not
    # the adjudicator and was never a substitute for it.
    adj = R.get("adjudication")
    stream_verdict = next((e for e in ran["events"] if e["type"] == "adjudicated"), {})
    if not adj:
        problems.append("the receipt cannot say which backend decided — "
                        "adjudicator identity is not durable")
    else:
        if not adj.get("by"):
            problems.append("adjudication carries no backend name")
        if adj.get("is_model") is None:
            problems.append("adjudication does not say whether a model decided")
        if not adj.get("reasoning"):
            problems.append("adjudication carries no reasoning")
        if adj.get("verdict") != (resolved[0]["resolution"] if resolved else None):
            problems.append("the audited verdict and the contradiction disagree")
        # The stream is used ONLY to check the durable copy matches it. If they
        # ever diverge the durable one is the product and the stream is decoration.
        if stream_verdict and adj.get("by") != stream_verdict.get("by"):
            problems.append(f"receipt says {adj.get('by')!r}, stream said "
                            f"{stream_verdict.get('by')!r}")
    if not memory:
        problems.append("no memory outcome")
    if not owed:
        problems.append("no effect owed a reversal, though the story retracts one "
                        "that already executed")
    if not requested:
        problems.append("no reversal request recorded")
    if requested and not any(str(e.get("idempotency_key", "")).startswith("comp:")
                             for e in requested):
        problems.append("a reversal request carries no comp:<original> key")
    if any(e.get("external_receipt") for e in requested):
        problems.append("a request claims an external receipt with no provider "
                        "configured")
    if not audit:
        problems.append("no audit provenance")
    if res.get("via") != "cockroachdb-managed-mcp":
        problems.append(f"served via {res.get('via')!r}")

    print(f"\n  {'PASS' if not problems else 'FAIL'}  receipt describes the real session")
    print(f"          contradiction   {resolved[0]['resolution'] if resolved else '—'}")
    print(f"          decided by      {(adj or {}).get('by', '—')}  "
          f"is_model={(adj or {}).get('is_model')}  "
          f"conf={(adj or {}).get('confidence')}")
    print(f"          reasoning       {str((adj or {}).get('reasoning', '—'))[:78]}")
    print(f"          memory          {' · '.join(str(m['n']) + ' ' + m['status'] for m in memory) or '—'}")
    print(f"          owed a reversal {len(owed)}  ({', '.join(e['tool'] for e in owed) or '—'})")
    print(f"          requested       {len(requested)}  "
          f"({', '.join(e['idempotency_key'] for e in requested) or '—'})")
    print(f"          dispatched      {sum(1 for e in requested if e.get('external_receipt'))}")
    print(f"          audit entries   {len(audit)}")
    for p in problems:
        print(f"          {p}")

    # --- fail closed -------------------------------------------------------
    saved = M._mcp
    try:
        class Dead:
            def select(self, *a, **k):
                from retract.mcp import MCPError
                raise MCPError("simulated: managed endpoint unreachable")
        M._mcp = Dead()
        closed = asyncio.run(M.contradictions(grant_token=grant))
    finally:
        M._mcp = saved

    fc = []
    if closed.get("available") is not False:
        fc.append(f"available={closed.get('available')!r} with MCP down")
    if closed.get("receipt") is not None:
        fc.append("a receipt was returned anyway")
    print(f"\n  {'PASS' if not fc else 'FAIL'}  fails closed when MCP is unavailable")
    print(f"          available={closed.get('available')} reason={closed.get('reason')}")
    for f in fc:
        print(f"          {f}")

    bad = bool(problems) + bool(fc)
    print()
    if bad:
        print("A read that is empty exactly when the product works is a badge, "
              "not a dependency.")
        return 1
    print("MCP serves the receipt for the session the product just produced, and "
          "says so when it cannot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
