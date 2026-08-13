"""How much does a stranger holding down refresh cost us?

/api/distances is unauthenticated, public, and used to call the embedder twice
per pair on every request -- fourteen Bedrock InvokeModel calls per page view,
with no token in front of it. PR #2's demo token covers write paths only, so
this was an open spend endpoint on the live demo for as long as the demo has
been up.

WHAT THIS EVAL ASSERTS, WRITTEN BEFORE THE FIX WAS OPENED

    The number of embedder invocations must be bounded by a constant,
    independent of how many requests arrive.

    Control: the endpoint as it shipped costs 14 invocations per request,
    so cost grows linearly with traffic.

Note what is NOT asserted: that the cost is zero. The first request on a cold
container still pays once, and that is correct -- the number on the page is a
measurement, and a measurement nobody ever computes is a hardcoded claim. The
property worth having is that the bill stops depending on the visitor count.

The concurrency case is the one a cache usually gets wrong -- two visitors
arriving together on a cold process both paying -- and this eval REPORTS it
without asserting it. Removing the lock does not change the number, because
nothing awaits between the cache lookup and the store, so the event loop has no
opportunity to interleave. The first draft asserted it anyway and passed, which
made it a third green light that tested nothing. It is now labelled as such.

NO CREDENTIALS, NO NETWORK, NO DATABASE. The embedder is a counting stub, so
the assertion is about how many times RETRACT *would have* called Bedrock.

Run:  uv run python experiments/spend_eval.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# app.main reads both of these at import time. Neither is connected to here:
# the endpoint under test touches no database, and boot() only runs on startup.
os.environ.setdefault("CRDB_URL", "postgresql://unused-by-this-eval")
_CACHE = tempfile.mkdtemp(prefix="retract-spend-eval-")
os.environ["RETRACT_CACHE_DIR"] = _CACHE

import numpy as np  # noqa: E402

from app import main as app_main  # noqa: E402

REQUESTS = 25
PAIRS = len(app_main.DISTANCE_PAIRS)
PER_UNCACHED_REQUEST = PAIRS * 2          # both sides of every pair


class CountingEmbedder:
    """Stands in for Bedrock. Counts what the bill would have been."""

    name = "counting-stub"

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, text: str) -> np.ndarray:
        self.calls += 1
        # Deterministic and semantics-free. It must never be used to make a
        # claim about meaning -- this eval only counts calls.
        rng = np.random.default_rng(abs(hash(text)) % (2**32))
        return rng.standard_normal(512)


def shipped_endpoint(embedder) -> dict:
    """`/api/distances` as it shipped: recompute everything, every request."""
    out = []
    for a, b, kind in app_main.DISTANCE_PAIRS:
        d = float(np.linalg.norm(embedder.embed(a) - embedder.embed(b)))
        out.append({"a": a, "b": b, "kind": kind, "distance": round(d, 3)})
    return {"pairs": out, "embedder": embedder.name}


def guarded(n: int) -> tuple[int, list[dict]]:
    emb = CountingEmbedder()
    app_main._embedder = emb
    app_main._distances_memo.clear()
    for f in os.listdir(_CACHE):
        os.remove(os.path.join(_CACHE, f))

    async def drive():
        return [await app_main.distances() for _ in range(n)]

    results = asyncio.run(drive())
    return emb.calls, results


def guarded_concurrent(n: int) -> int:
    """n visitors arriving at once on a cold process."""
    emb = CountingEmbedder()
    app_main._embedder = emb
    app_main._distances_memo.clear()
    for f in os.listdir(_CACHE):
        os.remove(os.path.join(_CACHE, f))

    async def drive():
        await asyncio.gather(*(app_main.distances() for _ in range(n)))

    asyncio.run(drive())
    return emb.calls


def control(n: int) -> int:
    emb = CountingEmbedder()
    for _ in range(n):
        shipped_endpoint(emb)
    return emb.calls


def main() -> int:
    ok = True

    ctrl = control(REQUESTS)
    print(f"CONTROL  -- endpoint as it shipped, {REQUESTS} sequential requests")
    print(f"  embedder calls: {ctrl}  ({ctrl / REQUESTS:.0f} per request, linear in traffic)")
    if ctrl != REQUESTS * PER_UNCACHED_REQUEST:
        print(f"  FAIL (harness): expected {REQUESTS * PER_UNCACHED_REQUEST}; "
              "the control is not exercising the vulnerable path.")
        return 2

    calls, results = guarded(REQUESTS)
    print(f"\nGUARDED  -- cached endpoint, {REQUESTS} sequential requests")
    print(f"  embedder calls: {calls}")
    if calls != PER_UNCACHED_REQUEST:
        print(f"  FAIL: expected exactly {PER_UNCACHED_REQUEST} (one cold compute), got {calls}")
        ok = False

    # The cache must return the answer, not merely avoid computing one.
    if not results or any(r["pairs"] != results[0]["pairs"] for r in results):
        print("  FAIL: cached responses are not identical to the computed one")
        ok = False
    elif len(results[0]["pairs"]) != PAIRS or "computed_at" not in results[0]:
        print("  FAIL: cached payload is malformed or missing computed_at")
        ok = False
    else:
        print(f"  payload: {PAIRS} pairs, identical across all {REQUESTS}, "
              f"stamped {results[0]['computed_at']}")

    conc = guarded_concurrent(REQUESTS)
    print(f"\nNOT A CONTROL -- {REQUESTS} visitors arriving together on a cold process")
    print(f"  embedder calls: {conc}")
    print("  This number is reported, not asserted. Removing the lock entirely")
    print("  leaves it at 14: there is no await between the cache lookup and")
    print("  the store, so the event loop cannot interleave two visitors here")
    print("  no matter what the lock does. A guard never observed to fire is a")
    print("  claim, not a control, so this one is labelled rather than counted.")
    print("  The lock stays as defence for the day embed() becomes awaitable,")
    print("  and on that day this case becomes a real control.")

    saved = ctrl - calls
    print(f"\n{'PASS' if ok else 'FAIL'}: cost is constant, not linear. "
          f"{REQUESTS} requests went from {ctrl} calls to {calls} "
          f"({saved} avoided; at 1000 visitors, {1000 * PER_UNCACHED_REQUEST - PER_UNCACHED_REQUEST} avoided).")
    print("Unverified here: the live Railway container's cache directory is "
          "writable. If it is not, the bound degrades to once per process, "
          "which is still constant in traffic.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
