"""Scope is the tenant boundary. This module is what makes it one.

THE DEFECT THIS EXISTS TO CLOSE

`scope` was a caller-supplied string. `GovernedMemoryReader(mcp, scope)` took
whatever it was handed, escaped the quotes, and interpolated it into every
WHERE clause. Escaping stops SQL injection; it does nothing about authority.
Any caller that could name another fleet's scope could read that fleet's
beliefs, contradictions, effects and audit trail -- through the endpoint we
describe as *governed*. The read path was governed against writes and against
nothing else.

WHAT REPLACES IT

A scope now has to be *granted*, not *declared*. The process that owns a scope
mints a token for it; a reader is constructed from that token and refuses to
exist without one. The token is an HMAC over the scope name, so a caller
holding a token for tenant A cannot produce one for tenant B: it would have to
forge the tag, and the secret never leaves the minting process.

WHAT THIS IS NOT

This is not authentication. It does not know *who* is asking, only that
whoever is asking was handed authority over this scope by something that holds
the secret. Binding a scope to a real identity -- a Cloud service account, an
MCP session -- is the next layer and is not built. Stated here rather than in a
commit message, because the gap is the kind a reader should not have to find.

THE SECRET

`RETRACT_SCOPE_SECRET` if set. Otherwise a random per-process secret, which is
the correct default for the demo: the app mints and verifies in one process, so
tokens are unforgeable from outside it and worthless if they leak, because the
next restart invalidates them. A deployment that mints in one process and reads
in another MUST set the variable -- with the ephemeral default, its tokens will
be rejected across the boundary rather than silently trusted.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass


class ScopeDenied(PermissionError):
    """A scope was requested that the caller was not granted."""


_EPHEMERAL = secrets.token_hex(32)


def _secret() -> bytes:
    return (os.environ.get("RETRACT_SCOPE_SECRET") or _EPHEMERAL).encode()


def _tag(scope: str) -> str:
    return hmac.new(_secret(), scope.encode(), hashlib.sha256).hexdigest()[:32]


def mint(scope: str) -> str:
    """Issue a grant token for a scope. Only call this where the scope is owned.

    The demo mints at session creation, which is the honest place: the process
    that invents `story-4f2a...` is the only one entitled to read it.
    """
    if not scope or "." in scope:
        # The dot separates the token, so a scope containing one would let a
        # crafted name shift the boundary between payload and tag.
        raise ValueError(f"scope must be non-empty and contain no '.': {scope!r}")
    return f"{scope}.{_tag(scope)}"


@dataclass(frozen=True)
class ScopeGrant:
    """Proof that the holder may read one scope. Constructed only by verifying.

    Frozen, and deliberately without a public constructor path that skips the
    check: `ScopeGrant(scope="other-tenant")` is reachable in Python and would
    defeat the whole module, so nothing in RETRACT constructs it that way and
    the eval's control arm demonstrates what happens when something does.
    """

    scope: str

    @classmethod
    def from_token(cls, token: str) -> "ScopeGrant":
        scope, _, tag = str(token).rpartition(".")
        if not scope or not tag:
            raise ScopeDenied("malformed scope token")
        if not hmac.compare_digest(tag, _tag(scope)):
            raise ScopeDenied(f"scope token not valid for {scope!r}")
        return cls(scope=scope)

    @classmethod
    def for_owned_scope(cls, scope: str) -> "ScopeGrant":
        """Mint and immediately verify. For the process that owns the scope."""
        return cls.from_token(mint(scope))

    def require(self, scope: str) -> str:
        """Assert this grant covers `scope`, and return it. Raises otherwise."""
        if scope != self.scope:
            raise ScopeDenied(f"granted {self.scope!r}, requested {scope!r}")
        return scope

    def sql_literal(self) -> str:
        """The scope as a SQL literal. Escaping stays -- authority is not it."""
        return "'" + self.scope.replace("'", "''") + "'"
