"""Can one fleet read another fleet's memory through the governed read path?

Until 13 Aug the answer was yes, and nothing in the repo said so. `scope` was
the tenant boundary and also a string the caller chose. RETRACT's headline is
*governed* shared memory; a read path that governs writes and not tenancy is
governed against the wrong thing.

WHAT THIS EVAL ASSERTS, WRITTEN BEFORE THE FIX WAS OPENED

    A read issued for a scope the caller was not granted must be refused,
    and the query must never be sent.

    Control: with the guard absent, the same read succeeds.

HOW THE CONTROL IS BUILT, AND WHY THE FIRST VERSION OF IT WAS WORTHLESS

The first draft ran every attack against the shipped reader and called it a
control. Four of its six "refusals" came from `ScopeGrant` raising before the
vulnerable reader was ever constructed -- the control arm was being defended by
the very guard it was supposed to be missing. It reported 6/6 and proved one
case.

So the arms are now defined by *both* layers, because there are two guards and
each needs its own absent-version:

    grant  -- guarded: ScopeGrant.from_token verifies an HMAC.
              control: accepts any token, verifying nothing.
    reader -- guarded: GovernedMemoryReader demands a grant, and constrains
              both ends of a provenance walk.
              control: the class exactly as it shipped, taking a scope string.

An attack that the control arm cannot even execute is not a control. If the
control stops breaching, this harness is broken and its passes are worthless.

NO CREDENTIALS NEEDED. The MCP client is replaced with a recorder that captures
the SQL instead of sending it, so the assertion is about what RETRACT *tried*
to read -- which is the security question. Whether Cockroach would then have
returned rows is a separate, weaker question that needs a live cluster.

Run:  uv run python experiments/scope_eval.py
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from retract.mcp import GovernedMemoryReader  # noqa: E402
from retract.scope import ScopeDenied, ScopeGrant, mint  # noqa: E402

OWNED = "tenant-alpha"
VICTIM = "tenant-beta"
FOREIGN_MEMORY = "00000000-0000-0000-0000-0000000000ff"


class RecordingClient:
    """Stands in for MCPClient. Sends nothing, remembers everything."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def select(self, query: str, database: str = "defaultdb") -> list[dict]:
        self.queries.append(" ".join(query.split()))
        return []


# -- the control arm: both guards, as they were before the fix -----------------

@dataclass(frozen=True)
class UnverifiedGrant:
    """What a grant is when nothing checks the tag. Takes the caller's word."""

    scope: str

    @classmethod
    def from_token(cls, token: str) -> "UnverifiedGrant":
        scope, _, _tag = str(token).rpartition(".")
        return cls(scope=scope or str(token))

    @classmethod
    def for_owned_scope(cls, scope: str) -> "UnverifiedGrant":
        return cls(scope=scope)

    def require(self, scope: str) -> str:
        return scope

    def sql_literal(self) -> str:
        return "'" + self.scope.replace("'", "''") + "'"


class LegacyReader:
    """`GovernedMemoryReader` as it shipped. Copied, not imported -- the
    vulnerable version no longer exists to import, and a control that is merely
    described is not a control. Only the exercised methods are reproduced."""

    def __init__(self, client, scope):
        self.mcp = client
        self.scope = (scope.scope if hasattr(scope, "scope") else str(scope)).replace("'", "''")

    def beliefs(self, limit: int = 20):
        return self.mcp.select(f"""
            SELECT subject, predicate, content, author_agent, recorded_at
            FROM memory
            WHERE scope = '{self.scope}' AND valid_to IS NULL AND status = 'active'
            ORDER BY recorded_at DESC LIMIT {int(limit)}
        """)

    def provenance(self, memory_id: str):
        mid = memory_id.replace("'", "''")
        return self.mcp.select(f"""
            SELECT m.id, m.content, m.status
            FROM derivation d JOIN memory m ON m.id = d.parent_id
            WHERE d.child_id = '{mid}'
        """)


@dataclass(frozen=True)
class Arm:
    label: str
    grant: type          # .from_token / .for_owned_scope
    reader: type         # (client, grant) -> reader


GUARDED = Arm("GUARDED  -- HMAC grant + reader that demands one",
              ScopeGrant, GovernedMemoryReader)
CONTROL = Arm("CONTROL  -- no verification, reader as it shipped",
              UnverifiedGrant, LegacyReader)


# -- what counts as a breach ---------------------------------------------------

def breaches(queries: list[str], granted: str) -> list[str]:
    """A query breaches if it names a scope we were not granted, OR if it
    reads memory while naming no scope at all. The second form is the one the
    provenance defect took: an unconstrained read looks innocent because there
    is no wrong scope in it, only a missing right one."""
    out = []
    for q in queries:
        named = re.findall(r"scope\s*=\s*'([^']*)'", q)
        foreign = set(named) - {granted}
        if foreign:
            out.append(f"named {sorted(foreign)}")
        elif not named and re.search(r"\bFROM\s+(memory|derivation|effect|audit_log|contradiction)\b", q, re.I):
            out.append("no scope predicate at all")
        elif re.search(r"\bFROM\s+derivation\b", q, re.I) and len(named) < 2:
            # A DAG walk crosses two memory rows. Constraining one end and not
            # the other still leaks the other -- and it would slip past the two
            # checks above, because the scope it names is the RIGHT one. This
            # case exists because that is exactly what a half-fix looks like.
            out.append(f"derivation walk constrains only {len(named)} of 2 ends")
    return out


# -- the attacks ---------------------------------------------------------------
# Each takes an arm and a client, and attempts a read it is not entitled to.
# Raising means the attempt was refused. Returning normally means it went
# through -- which is only a pass if `breaches` also finds nothing on the wire.

def caller_names_another_tenant(arm, client):
    """The original hole in one line: name the tenant you want."""
    arm.reader(client, VICTIM).beliefs()


def forged_token(arm, client):
    """An attacker who knows the token format but not the secret."""
    arm.reader(client, arm.grant.from_token(f"{VICTIM}." + "0" * 32)).beliefs()


def tag_removed(arm, client):
    """Tag stripped entirely -- tests that "no tag" is not "no check"."""
    arm.reader(client, arm.grant.from_token(VICTIM + ".")).beliefs()


def tag_from_another_scope(arm, client):
    """A real tag, lifted off a scope the attacker legitimately holds."""
    stolen = mint(OWNED).split(".", 1)[1]
    arm.reader(client, arm.grant.from_token(f"{VICTIM}.{stolen}")).beliefs()


def valid_grant_wrong_scope(arm, client):
    """A legitimate holder of tenant-alpha asking for tenant-beta's rows."""
    g = arm.grant.from_token(mint(OWNED))
    arm.reader(client, arm.grant.from_token(f"{g.require(VICTIM)}.x")).beliefs()


def provenance_walk(arm, client):
    """The second hole. `derivation` carries no scope of its own, so a reader
    correctly granted tenant-alpha could still walk the DAG into tenant-beta by
    naming a child id. Refusal here is not an exception -- it is the query
    coming back constrained. `breaches` is what judges it."""
    arm.reader(client, arm.grant.for_owned_scope(OWNED)).provenance(FOREIGN_MEMORY)


ATTACKS = [
    ("caller names another tenant", caller_names_another_tenant),
    ("forged grant token", forged_token),
    ("token with the tag removed", tag_removed),
    ("tag lifted from a held scope", tag_from_another_scope),
    ("valid grant, other tenant's scope", valid_grant_wrong_scope),
    ("provenance walk out of scope", provenance_walk),
]


def run(arm: Arm) -> tuple[int, int]:
    """Returns (refused, breached)."""
    refused = breached = 0
    print(f"\n{arm.label}")
    for name, attack in ATTACKS:
        client = RecordingClient()
        try:
            attack(arm, client)
            outcome = "ALLOWED"
        except (ScopeDenied, TypeError, ValueError, AttributeError) as e:
            outcome = f"refused ({type(e).__name__})"
            refused += 1

        found = breaches(client.queries, OWNED)
        if found:
            breached += 1
            outcome += f"  <-- SENT: {'; '.join(found)}"
        print(f"  {name:36s} {outcome}")
    return refused, breached


def main() -> int:
    if os.environ.get("RETRACT_SCOPE_SECRET"):
        print("note: RETRACT_SCOPE_SECRET is set; tokens are cross-process")

    total = len(ATTACKS)
    g_refused, g_breached = run(GUARDED)
    c_refused, c_breached = run(CONTROL)

    print(f"\nguarded: {g_refused}/{total} refused · {g_breached} breaching queries sent")
    print(f"control: {c_refused}/{total} refused · {c_breached} breaching queries sent")

    if c_breached < total:
        print(f"\nFAIL (harness): the control only breached {c_breached}/{total}. "
              "Every attack must succeed against the unguarded path, or the "
              "guarded pass is measuring the harness, not the guard.")
        return 2
    if g_breached:
        print(f"\nFAIL: {g_breached} cross-tenant queries survived the guard.")
        return 1

    print(f"\nPASS: {total}/{total} attacks reached the wire unguarded and "
          f"{total}/{total} were stopped by the guard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
