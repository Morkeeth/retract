"""Canonicalising a claim into the key that agents lock on.

The whole correctness argument rests on two agents asserting the same thing
deriving the SAME key. If one extracts subject "4471" and another extracts
"customer 4471", they take different locks and both write -- the exact failure
the deterministic key was brought in to fix.

So canonicalisation is not tidying, it is the guarantee. It is deliberately
boring, deterministic, and free of model calls: a model that canonicalises
differently on two runs would reintroduce the bug it is here to prevent.
"""

from __future__ import annotations

import re
import unicodedata

_ID = re.compile(r"\b(?:customer|cust|client|user|account|acct)[\s#:_-]*(\d{2,})\b", re.I)
_BARE_ID = re.compile(r"\b(\d{4,})\b")
_WS = re.compile(r"\s+")


def canon_subject(raw: str) -> str:
    """Normalise an entity reference to a stable key.

    'Customer 4471', 'cust 4471', 'CUSTOMER#4471', '4471' -> 'customer:4471'
    Anything unrecognised is lowercased and whitespace-collapsed rather than
    rejected: an unknown subject must still lock consistently.
    """
    s = unicodedata.normalize("NFKC", raw).strip()
    m = _ID.search(s) or _BARE_ID.search(s)
    if m:
        return f"customer:{int(m.group(1))}"
    s = _WS.sub(" ", s.lower())
    s = re.sub(r"[^\w\s:.-]", "", s)
    return s or "unknown"


def canon_predicate(raw: str) -> str:
    """Normalise a predicate to snake_case.

    'Identity Verified', 'identity-verification', 'identity_verified'
        -> 'identity_verified'
    """
    s = unicodedata.normalize("NFKC", raw).strip().lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = _WS.sub("_", s.strip())
    # crude but deterministic stemming of the handful of endings that actually
    # collide in practice. A model-based lemmatiser would not be reproducible.
    s = re.sub(r"(ication|ications)$", "ied", s)
    s = re.sub(r"(_status|_state|_flag)$", "", s)
    return s or "unknown"


def claim_key(subject: str, predicate: str) -> tuple[str, str]:
    return canon_subject(subject), canon_predicate(predicate)
