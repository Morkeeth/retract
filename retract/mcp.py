"""The governed read path: agents reach memory through CockroachDB's managed MCP.

WHY A SECOND PATH AT ALL

RETRACT already has a SQL connection. Adding MCP would be pure decoration if it
were just another way to run the same queries. It is not, and the reason is the
asymmetry:

    READS  go through the managed MCP endpoint -- permission-scoped by a Cloud
           service account, audited by Cockroach, and reachable by any
           MCP-speaking client (Claude Code, Cursor, an operator at 3am).
    WRITES never go through MCP. They cannot: the claim lock needs
           SELECT ... FOR UPDATE inside a multi-statement serializable
           transaction, and MCP's write surface is create_table / insert_rows.
           There is no way to express the lock through it.

So agents read memory through an endpoint they are structurally incapable of
corrupting, while every mutation is funnelled through the one code path that
takes the lock. That is not a limitation we worked around -- it is the safety
property, and it falls out of the tool's design rather than our discipline.

The endpoint enforces this too: `select_query` rejects anything that is not a
single read-only SELECT.

WHAT THAT ASYMMETRY DOES NOT COVER

Being unable to write says nothing about *which tenant's* rows you may read.
That second boundary was open until 13 Aug: the reader took a scope name from
its caller. It now takes a granted scope; see `retract/scope.py` for what the
grant proves and what it still does not.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from .scope import ScopeDenied, ScopeGrant

ENDPOINT = "https://cockroachlabs.cloud/mcp"


class MCPError(RuntimeError):
    pass


@dataclass
class MCPClient:
    """Minimal MCP client over streamable HTTP. No SDK, no extra dependency."""

    api_key: str
    cluster_id: str
    endpoint: str = ENDPOINT
    _id: int = 0

    @classmethod
    def from_env(cls) -> "MCPClient":
        key = os.environ.get("CRDB_API_KEY")
        cid = os.environ.get("CRDB_CLUSTER_ID")
        if not key or not cid:
            raise MCPError("CRDB_API_KEY and CRDB_CLUSTER_ID must be set")
        return cls(api_key=key, cluster_id=cid)

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method,
                           "params": params or {}}).encode()
        req = urllib.request.Request(
            self.endpoint, data=body, method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                # The endpoint speaks streamable HTTP: it replies with SSE
                # framing even for a single response, so both are advertised.
                "Accept": "application/json, text/event-stream",
            },
        )
        try:
            raw = urllib.request.urlopen(req, timeout=30).read().decode()
        except urllib.error.HTTPError as e:
            raise MCPError(f"{e.code} {e.read().decode()[:200]}") from None

        payload = None
        for line in raw.splitlines():
            line = line[5:].strip() if line.startswith("data:") else line.strip()
            if line.startswith("{"):
                payload = json.loads(line)
        if payload is None:
            raise MCPError(f"no JSON in response: {raw[:200]}")
        if "error" in payload:
            raise MCPError(payload["error"].get("message", str(payload["error"])))
        return payload.get("result", {})

    def initialize(self) -> dict:
        return self._rpc("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "retract", "version": "0.1"},
        })

    def tools(self) -> list[str]:
        return [t["name"] for t in self._rpc("tools/list").get("tools", [])]

    def call(self, name: str, arguments: dict) -> dict:
        res = self._rpc("tools/call", {"name": name, "arguments": arguments})
        content = res.get("content", [])
        if not content:
            return {}
        text = content[0].get("text", "")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}

    # -- the read surface RETRACT actually uses ----------------------------
    def select(self, query: str, database: str = "defaultdb") -> list[dict]:
        """One read-only SELECT. The endpoint rejects anything else.

        The argument is `query`, not `statement` -- a wrong key surfaces as
        "must contain exactly one statement", which reads like a SQL complaint
        and is not one. Read the tool's inputSchema, do not infer it.
        """
        out = self.call("select_query", {
            "cluster_id": self.cluster_id,
            "database": database,
            "query": " ".join(query.split()),
        })
        return out.get("rows", [])

    def cluster(self) -> dict:
        return self.call("get_cluster", {"cluster_id": self.cluster_id})

    def table_schema(self, table: str, database: str = "defaultdb") -> dict:
        return self.call("get_table_schema", {
            "cluster_id": self.cluster_id, "database": database, "table": table})

    def running_queries(self) -> list[dict]:
        return self.call("show_running_queries", {"cluster_id": self.cluster_id}).get("rows", [])


class GovernedMemoryReader:
    """Read-only views over RETRACT's memory, served through MCP.

    Everything an operator or a downstream agent needs to INSPECT the fleet's
    beliefs, with no path to change them. If this class could write, the
    guarantee would be a convention; because MCP cannot, it is structural.
    """

    def __init__(self, client: MCPClient, grant: ScopeGrant):
        # A string used to be accepted here, and that was the whole defect: the
        # caller named the tenant boundary it wanted to be inside. Refusing the
        # string outright, rather than coercing it, is deliberate -- a coercion
        # would have let every existing call site keep the old authority.
        if not isinstance(grant, ScopeGrant):
            raise ScopeDenied(
                "GovernedMemoryReader needs a ScopeGrant, not a scope name. "
                "Mint one where the scope is owned: ScopeGrant.for_owned_scope(...)"
            )
        self.mcp = client
        self.grant = grant
        self.scope = grant.scope
        self._s = grant.sql_literal()

    def beliefs(self, limit: int = 20) -> list[dict]:
        return self.mcp.select(f"""
            SELECT subject, predicate, content, author_agent, recorded_at
            FROM memory
            WHERE scope = {self._s} AND valid_to IS NULL AND status = 'active'
            ORDER BY recorded_at DESC LIMIT {int(limit)}
        """)

    def open_contradictions(self) -> list[dict]:
        """The facts this fleet currently disagrees about."""
        return self.mcp.select(f"""
            SELECT subject, predicate, challenger, challenger_by, distance, detected_at
            FROM contradiction
            WHERE scope = {self._s} AND resolution = 'open'
            ORDER BY detected_at DESC
        """)

    def unreachable_effects(self) -> list[dict]:
        """Side effects that outlived the belief that justified them."""
        return self.mcp.select(f"""
            SELECT e.tool, e.idempotency_key, e.status, m.content AS justified_by
            FROM effect e JOIN memory m ON m.id = e.justified_by
            WHERE e.scope = {self._s} AND e.status = 'needs_compensation'
        """)

    def provenance(self, memory_id: str) -> list[dict]:
        """What a belief was built on. Reads the DAG without touching it.

        `derivation` carries no scope of its own -- it is two memory ids -- so
        this query was reachable for ANY memory id regardless of tenant, which
        made it a cross-tenant read even for a correctly scoped reader. Both
        ends of the edge are now constrained: a caller cannot walk out of its
        own scope by naming a child, and cannot learn a parent by inference
        from one that is in scope.
        """
        mid = memory_id.replace("'", "''")
        return self.mcp.select(f"""
            SELECT m.id, m.content, m.status
            FROM derivation d
            JOIN memory m ON m.id = d.parent_id
            JOIN memory c ON c.id = d.child_id
            WHERE d.child_id = '{mid}'
              AND c.scope = {self._s} AND m.scope = {self._s}
        """)

    def audit_tail(self, limit: int = 25) -> list[dict]:
        return self.mcp.select(f"""
            SELECT at, agent, action, detail
            FROM audit_log WHERE scope = {self._s}
            ORDER BY at DESC LIMIT {int(limit)}
        """)
