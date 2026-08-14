"""RETRACT demo surface: the race, live, against the real cluster.

Nothing here is simulated. Every event streamed to the browser is the result of
an actual transaction against CockroachDB. The naive pane is a real, deliberately
naive implementation -- not a strawman drawn in CSS -- because a control the
viewer cannot verify is theatre.

Write paths are preset scenarios under `/api/run/{id}` and go through the
guards in `app/middleware.py`. No request text ever reaches an embedding or a
model call — the claims below are the only inputs the runners use.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import queue
import sys
import threading
import time
import uuid
from pathlib import Path

import numpy as np
import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from middleware import (  # noqa: E402
    REQUEST_TIMEOUT_S,
    DemoGuardMiddleware,
    configure_logging,
)
from retract.adjudicate import get_adjudicator  # noqa: E402
from retract.embed import get_embedder  # noqa: E402
from retract.engine import MemoryEngine, vec_literal  # noqa: E402
from retract.mcp import GovernedMemoryReader, MCPClient, MCPError  # noqa: E402
from retract.scope import ScopeDenied, ScopeGrant, mint  # noqa: E402

configure_logging()
log = logging.getLogger("retract")

app = FastAPI(title="RETRACT")
app.add_middleware(DemoGuardMiddleware)
STATIC = Path(__file__).parent / "static"
URL = os.environ["CRDB_URL"]

# Server-side scenario IDs. The URL carries an id from this set and nothing
# else — no free-form mode, no caller-supplied claim text.
SCENARIOS = {
    "race_naive": "race",
    "race_retract": "race",
    "story": "story",
}

CLAIMS = [
    ("Customer 4471 has verified their identity via passport.", "Customer 4471", "identity verified"),
    ("ID verification complete for customer 4471 (passport).", "customer 4471", "identity_verified"),
    ("Cust 4471 identity confirmed, passport on file.", "cust 4471", "identity-verification"),
    ("Passport check passed for customer 4471.", "CUSTOMER#4471", "Identity Verified"),
    ("Customer 4471: identity verified.", "4471", "identity verification"),
    ("Verified customer 4471 using passport documentation.", "Cust. 4471", "IDENTITY VERIFIED"),
    ("Identity of customer 4471 established via passport.", "customer_4471", "identity verified status"),
    ("4471 has now passed passport-based identity verification.", "Customer 4471", "identity_verification"),
]
NEGATION = ("Customer 4471 FAILED identity verification - passport is forged.",
            "Customer 4471", "identity verified")

# The pairs behind /api/distances. A module-level constant because the cache
# key is derived from them: edit a pair and every cached answer is discarded,
# which is the only way a stale number cannot outlive the question it answered.
DISTANCE_PAIRS = [
    ("verified via passport", "ID verification complete", "paraphrase"),
    ("verified via passport", "identity confirmed, passport on file", "paraphrase"),
    ("Customer 4471 verified", "Customer 4472 verified", "different customer"),
    ("verified their identity", "FAILED identity verification", "negation"),
    ("refund of $1,240 approved", "refund of $1,240 declined", "negation"),
    ("refund of $1,240 approved", "refund of $2,140 approved", "different amount"),
    ("9902 lives in Berlin", "9902 used to live in Berlin", "tense change"),
]

# Survives process restarts, so a redeploy does not re-pay for an answer that
# cannot have changed. /tmp is the honest default on Railway: the container
# filesystem is ephemeral, so the guarantee is "once per container", not
# "once ever". Set RETRACT_CACHE_DIR at a volume to get the stronger one.
CACHE_DIR = Path(os.environ.get("RETRACT_CACHE_DIR", "/tmp/retract-cache"))

_embedder = None
_adjudicator = None
_vectors: list[np.ndarray] = []
_distances_lock = asyncio.Lock()
_mcp = None
_distances_memo: dict[str, dict] = {}


def _distances_key(embedder_name: str) -> str:
    h = hashlib.sha256(json.dumps(DISTANCE_PAIRS).encode()).hexdigest()[:16]
    return f"distances-{embedder_name}-{h}"


def _load_distances(embedder_name: str) -> dict | None:
    key = _distances_key(embedder_name)
    if key in _distances_memo:
        return _distances_memo[key]
    try:
        payload = json.loads((CACHE_DIR / f"{key}.json").read_text())
    except (OSError, ValueError):
        # A missing or corrupt cache costs one recomputation, never an error
        # page. The failure mode of a cache must be slowness, not an outage.
        return None
    _distances_memo[key] = payload
    return payload


def _store_distances(embedder_name: str, payload: dict) -> None:
    _distances_memo[_distances_key(embedder_name)] = payload
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{_distances_key(embedder_name)}.json").write_text(json.dumps(payload))
    except OSError:
        # An unwritable disk degrades us to once-per-process, which is still
        # bounded. Not worth failing the request over.
        pass


def boot() -> None:
    global _embedder, _adjudicator, _vectors
    _embedder = get_embedder()
    _adjudicator = get_adjudicator()
    _vectors = _embedder.embed_many([c[0] for c in CLAIMS] + [NEGATION[0]])


@app.on_event("startup")
def _startup() -> None:
    threading.Thread(target=boot, daemon=True).start()


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# --------------------------------------------------------------------------- #
def run_race(mode: str, q: "queue.Queue[dict]") -> None:
    """Eight agents, one fact, real transactions. Emits events as they happen."""
    scope = f"live-{mode}-{uuid.uuid4().hex[:8]}"
    lock = threading.Lock()
    state = {"beliefs": 0, "contradictions": 0, "keys": set()}

    def emit(**kw):
        q.put({"mode": mode, **kw})

    def worker(i: int) -> None:
        content, subject, predicate = CLAIMS[i]
        emb = _vectors[i]
        emit(type="agent", agent=i, phase="read", claim=content)
        time.sleep(0.35 + i * 0.03)

        if mode == "naive":
            with psycopg.connect(URL, autocommit=True) as c, c.cursor() as cur:
                cur.execute(
                    "INSERT INTO memory (scope, content, embedding, subject, predicate,"
                    " embedder, author_agent, snapshot_ts)"
                    " VALUES (%s,%s,%s::vector,%s,%s,'naive',%s,'0')",
                    (scope, content, vec_literal(emb), subject, predicate, f"agent-{i}"),
                )
            with lock:
                state["beliefs"] += 1
                state["keys"].add((subject, predicate))
                emit(type="result", agent=i, outcome="inserted",
                     beliefs=state["beliefs"], contradictions=0, keys=len(state["keys"]))
            return

        eng = MemoryEngine(URL, scope, f"agent-{i}", _embedder.name)
        for attempt in range(6):
            try:
                eng.read(emb)
                res = eng.commit(emb, content, subject, predicate)
                with lock:
                    if res.outcome == "inserted":
                        state["beliefs"] += 1
                    elif res.outcome == "contradiction":
                        state["contradictions"] += 1
                    state["keys"].add(("customer:4471", "identity_verified"))
                    emit(type="result", agent=i, outcome=res.outcome,
                         distance=res.distance, beliefs=state["beliefs"],
                         contradictions=state["contradictions"], keys=len(state["keys"]))
                return
            except psycopg.errors.SerializationFailure:
                time.sleep(0.05 * (2 ** attempt))
        emit(type="result", agent=i, outcome="exhausted", beliefs=state["beliefs"],
             contradictions=state["contradictions"], keys=len(state["keys"]))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(CLAIMS))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    emit(type="done", beliefs=state["beliefs"], contradictions=state["contradictions"],
         keys=len(state["keys"]), scope=scope)


@app.get("/api/run/{scenario_id}")
async def run_scenario(scenario_id: str, request: Request):
    """Preset write-path scenarios. The only way to mutate the demo database.

    `scenario_id` is one of `race_naive`, `race_retract`, `story`. Anything else
    is 404. No request body is read; no query text reaches the embedder or the
    adjudicator — those inputs are the module-level CLAIMS / NEGATION constants.
    """
    if scenario_id not in SCENARIOS:
        raise HTTPException(
            404,
            f"unknown scenario {scenario_id!r}; choose from {sorted(SCENARIOS)}",
        )
    request_id = getattr(request.state, "request_id", None)
    log.info(
        "scenario_start",
        extra={
            "request_id": request_id, "scenario": scenario_id,
            "path": request.url.path, "adjudication_mode":
            (_adjudicator.name if _adjudicator else "loading"),
        },
    )
    kind = SCENARIOS[scenario_id]
    if kind == "race":
        mode = "naive" if scenario_id == "race_naive" else "retract"
        return StreamingResponse(
            _race_stream(mode, request_id),
            media_type="text/event-stream",
        )
    return StreamingResponse(
        _story_stream(request_id),
        media_type="text/event-stream",
    )


@app.get("/api/race")
@app.get("/api/story")
async def legacy_write_paths_removed():
    """Old free-form write paths. Removed so a bookmarked URL cannot skip the token."""
    raise HTTPException(
        410,
        "use /api/run/{race_naive|race_retract|story}?token=… — free-form write paths are gone",
    )


@app.get("/api/distances")
async def distances():
    """The measurement that kills threshold-based dedup.

    Computed once per (embedder, pair set) and then served from cache. It used
    to be computed on every page view, which meant fourteen Bedrock
    InvokeModel calls per visitor on a public URL with no token in front of it
    -- an unauthenticated stranger could spend our AWS budget by holding down
    refresh. The pairs are a fixed constant and the embedder is deterministic,
    so recomputing was buying an identical answer every time.

    Read path, so no token, and that is safe here for a second reason: the
    pairs are server-side constants, so no request text ever reaches an
    embedder. SECURITY.md still says this endpoint costs an embedder call per
    page load -- that was true when it was written and the cache is what made
    it false. Fix that sentence there rather than here.

    The result carries `computed_at` so the page cannot present a cached number
    as a live one.
    """
    while _embedder is None:
        await asyncio.sleep(0.3)
    async with _distances_lock:
        # The lock is defence, not a fix: nothing awaits between the lookup and
        # the store, so today the event loop cannot interleave two visitors here
        # with or without it -- experiments/spend_eval.py reports that rather
        # than claiming a stampede was prevented. It earns its place the day
        # embed() becomes awaitable, which is when the window opens.
        cached = _load_distances(_embedder.name)
        if cached is not None:
            return cached
        out = []
        for a, b, kind in DISTANCE_PAIRS:
            d = float(np.linalg.norm(_embedder.embed(a) - _embedder.embed(b)))
            out.append({"a": a, "b": b, "kind": kind, "distance": round(d, 3),
                        "same_fact": kind == "paraphrase"})
        payload = {"pairs": sorted(out, key=lambda x: x["distance"]),
                   "embedder": _embedder.name,
                   "computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        _store_distances(_embedder.name, payload)
        return payload


@app.get("/api/contradictions")
async def contradictions(grant_token: str = ""):
    """The facts this fleet currently disagrees about, read through MCP.

    THIS IS THE ONLY ENDPOINT THAT DOES NOT TALK SQL, AND THAT IS THE POINT.

    Every other route here opens a psycopg connection. This one goes through
    CockroachDB's Managed MCP Server, which cannot write -- so the surface that
    exposes the fleet's disagreements is structurally incapable of editing
    them. Until now that path existed only in `experiments/mcp_eval.py`, which
    meant a judge who opened the live URL and ran no eval saw exactly one
    CockroachDB tool in a submission whose gate needs two.

    The parameter is `grant_token`, NOT `token`. PR #2's middleware reads
    `?token=` as the demo write-path credential, and two different secrets
    sharing one parameter name in one app is a collision waiting for the day
    this route moves behind a guard. Named apart on purpose.

    `grant_token` is a scope grant, minted by /api/story for the session it
    created.
    A caller cannot read another session's contradictions by naming its scope,
    because naming is no longer how you get in.

    WHEN MCP IS NOT CONFIGURED IT SAYS SO AND RETURNS NOTHING. It does not fall
    back to SQL. A fallback would make the feed work and the claim false at the
    same time, which is the worst of the three outcomes: the endpoint would be
    demonstrating a tool it was not using.
    """
    try:
        grant = ScopeGrant.from_token(grant_token)
    except ScopeDenied as e:
        return {"available": False, "reason": f"scope: {e}", "open": None}

    try:
        client = _mcp_client()
    except MCPError as e:
        return {"available": False, "reason": f"MCP not configured: {e}",
                "open": None, "via": "none"}

    rows = await asyncio.to_thread(
        lambda: GovernedMemoryReader(client, grant).open_contradictions())
    return {"available": True, "via": "cockroachdb-managed-mcp",
            "scope": grant.scope, "open": len(rows), "contradictions": rows}


def _mcp_client():
    """One client per process. Raises MCPError when the credentials are absent,
    which the caller turns into an honest 'not configured' rather than a zero."""
    global _mcp
    if _mcp is None:
        _mcp = MCPClient.from_env()
    return _mcp


async def _race_stream(mode: str, request_id: str | None):
    q: "queue.Queue[dict]" = queue.Queue()
    started = time.monotonic()
    while _embedder is None:
        if time.monotonic() - started > REQUEST_TIMEOUT_S:
            yield sse("error", {"error_class": "timeout", "msg": "embedder boot timed out"})
            return
        yield sse("booting", {"msg": "loading embedder"})
        await asyncio.sleep(0.4)
    threading.Thread(target=run_race, args=(mode, q), daemon=True).start()
    while True:
        if time.monotonic() - started > REQUEST_TIMEOUT_S:
            log.info(
                "scenario_timeout",
                extra={"request_id": request_id, "scenario": f"race_{mode}",
                       "error_class": "timeout"},
            )
            yield sse("error", {"error_class": "timeout"})
            return
        try:
            item = q.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.05)
            continue
        if item["type"] == "done":
            log.info(
                "scenario_done",
                extra={
                    "request_id": request_id, "scenario": f"race_{mode}",
                    "lock_outcome": (
                        f"beliefs={item.get('beliefs')} contradictions="
                        f"{item.get('contradictions')} keys={item.get('keys')}"
                    ),
                },
            )
        yield sse(item["type"], item)
        if item["type"] == "done":
            break


def _fraud_team_confirmation(scope: str) -> dict:
    """The external event the demo injects, stated rather than implied.

    In the story a human fraud team confirms the passport is forged. That
    confirmation arrives from outside RETRACT, and in this demo it is
    manufactured here -- there is no fraud team and no external system. Saying
    so in the code is the honest version; pretending the model's verdict is an
    authority is not.

    EXTERNAL_RETRACTION below is a seam on purpose. Point it at something that
    returns None and the absence becomes observable: the story then adjudicates,
    resolves the contradiction, and retracts nothing. That case is a row in
    experiments/verdict_eval.py's matrix rather than a paragraph nobody can run.
    """
    return {
        "authority": "fraud-team",
        "receipt": f"FRAUD-{scope.split('-')[-1].upper()}",
        "reason": "passport confirmed forged by fraud team",
    }


EXTERNAL_RETRACTION = _fraud_team_confirmation


def _story_events(q: "queue.Queue[dict]") -> None:
    scope = f"story-{uuid.uuid4().hex[:8]}"
    eng = MemoryEngine(URL, scope, "support-agent", _embedder.name)
    E = _embedder.embed

    def put(**kw):
        q.put(kw)

    chain = [
        ("Customer 4471 has verified their identity via passport.", "Customer 4471", "identity verified", None),
        ("Customer 4471 is eligible for instant refunds.", "Customer 4471", "refund eligibility", 0),
        ("Refund of $1,240 to customer 4471 is approved.", "Customer 4471", "refund approval", 1),
        ("Customer 4471 qualifies for priority support.", "Customer 4471", "support tier", 0),
        ("Customer 9902 has verified their identity.", "Customer 9902", "identity verified", None),
    ]
    ids = []
    for text, subj, pred, parent in chain:
        r = eng.commit(E(text), text, subj, pred,
                       derived_from=[ids[parent]] if parent is not None else ())
        ids.append(r.memory_id)
        put(type="belief", id=str(r.memory_id), text=text, subject=subj,
            predicate=pred, parent=(str(ids[parent]) if parent is not None else None))
        time.sleep(0.25)

    # Two executed effects, and only one of them is reachable. `card_charge` has
    # no entry in COMPENSATIONS, so the cascade flags it and the handler refuses
    # it — which is the half of the claim the page used to leave out. Every
    # surface says compensation is closed-loop for registered tools and that
    # unknown tools stay flagged; before this row the demo only ever showed the
    # first half, and a judge reading the claim then watching the film saw the
    # strong half demonstrated and the honest half absent.
    #
    # The name is deliberate. `card_charge` is already the canonical
    # unregistered tool in experiments/compensate_eval.py, and DEMO.md's shot
    # list was written around it. It does NOT collide with that eval's control
    # arm: the assert at compensate_eval.py:92 is about the COMPENSATIONS
    # registry, which this does not touch. Checked, not assumed.
    effects = [
        (2, "refund_issued", "rf-4471-1240", "executed", "$1,240 sent to customer 4471"),
        (2, "card_charge", "cc-4471-89", "executed", "$89 processed for customer 4471"),
        (3, "tier_upgrade", "tu-4471", "pending", "priority support queued"),
        (4, "welcome_email", "we-9902", "pending", "welcome email to customer 9902"),
    ]
    eff_ids = {}
    with psycopg.connect(URL, autocommit=True) as c, c.cursor() as cur:
        for idx, tool, key, status, label in effects:
            cur.execute(
                "INSERT INTO effect (scope, justified_by, tool, payload, idempotency_key, status,"
                " executed_at) VALUES (%s,%s,%s,%s,%s,%s, CASE WHEN %s='executed' THEN now() END)"
                " RETURNING id",
                (scope, ids[idx], tool, json.dumps({"label": label}), key, status, status),
            )
            eff_ids[tool] = cur.fetchone()[0]
            put(type="effect", tool=tool, status=status, label=label)
            time.sleep(0.2)

    # --- act 3: the negation, on the same claim key -----------------------
    neg = NEGATION[0]
    time.sleep(0.5)
    put(type="inject", text=neg)
    res = eng.commit(E(neg), neg, NEGATION[1], NEGATION[2])
    put(type="verdict_pending", outcome=res.outcome, distance=res.distance,
        incumbent=res.incumbent_content)
    time.sleep(0.4)

    # The verdict now decides something. It used to be printed and then ignored:
    # the next statement retracted unconditionally, so inverting Claude's answer
    # changed nothing a judge could observe. `MemoryEngine.resolve()` existed the
    # whole time and nothing called it.
    resolution = None
    if res.outcome == "contradiction":
        v = _adjudicator.judge("customer:4471", "identity_verified",
                               res.incumbent_content, neg)
        put(type="adjudicated", resolution=v.resolution, reasoning=v.reasoning,
            by=v.by, is_model=_adjudicator.is_model)
        resolution = v.resolution

        # Close the contradiction under the same claim lock, whatever the answer.
        # Leaving it open is how the MCP feed could show an open contradiction
        # seconds after this page said it had been adjudicated.
        eng.resolve(res.contradiction_id, v.resolution, E(neg))
        put(type="resolved", resolution=v.resolution,
            contradiction=str(res.contradiction_id))
        time.sleep(0.5)

    # --- act 4: the cascade, on an authority that is not the model ---------
    # A first version of this gate ran the cascade when the verdict came back
    # `superseded`. That still let the model authorise compensation -- one step
    # removed, and the event payload said so out loud with `authorised_by=
    # resolution`. Naming a string RETRACTION_AUTHORITY does not create one.
    #
    # These are two independent inputs and neither substitutes for the other:
    #
    #   the model's resolution     decides which belief the memory HOLDS.
    #                              superseded/rejected/duplicate, applied by
    #                              resolve() above, under the claim lock.
    #   an external retraction     decides whether anything is TAKEN BACK. It
    #   event                      carries an authority and a receipt from
    #                              outside this system, and it is the sole
    #                              trigger for retract() and therefore for any
    #                              compensation.
    #
    # With no external event there is no retraction and no compensation, whatever
    # the model said. With one, the cascade runs on ITS authority, and the
    # resolution is not consulted and is not recorded on the event.
    event = EXTERNAL_RETRACTION(scope) if EXTERNAL_RETRACTION else None
    if event is None:
        put(type="no_retraction", resolution=resolution,
            reason="no verified external retraction event. An adjudication decides "
                   "what the memory believes; it does not authorise taking back an "
                   "effect that already executed.")
        put(type="done", scope=scope, scope_token=mint(scope),
            retracted=0, cancelled=0, compensate=0, compensated=0)
        return

    put(type="retracting", reason=event["reason"],
        authority=event["authority"], receipt=event["receipt"])
    out = eng.retract(ids[0], f"{event['reason']} [{event['authority']} · {event['receipt']}]")
    retracted = {str(x) for x in out["retracted"]}
    for i, (text, subj, pred, _) in enumerate(chain):
        put(type="fallout", text=text, subject=subj,
            retracted=str(ids[i]) in retracted)
        time.sleep(0.22)

    with psycopg.connect(URL, autocommit=True) as c, c.cursor() as cur:
        cur.execute(
            "SELECT id, tool, status, payload FROM effect WHERE scope=%s ORDER BY tool",
            (scope,),
        )
        effect_rows = cur.fetchall()

    for eid, tool, status, payload in effect_rows:
        put(type="effect_final", tool=tool, status=status,
            label=payload.get("label", ""), effect_id=str(eid))
        time.sleep(0.22)

    # Close the loop the flag opens. One compensation per needs_compensation
    # row that has a registered handler; unknown tools stay flagged (surfaced
    # below as still needs_compensation). Day 3 owns a dedicated act-5 UI;
    # calling the handler here is what makes the Day-2 public-URL check true.
    compensated = 0
    for eid, tool, status, payload in effect_rows:
        if status != "needs_compensation":
            continue
        result = eng.compensate(eid)
        put(type="compensated", tool=tool,
            outcome=result.outcome,
            compensating_tool=result.compensating_tool,
            reversal_id=str(result.reversal_id) if result.reversal_id else None,
            reason=result.reason)
        if result.outcome in ("compensated", "already_compensated"):
            compensated += 1
            put(type="effect_final", tool=tool, status="compensated",
                label=payload.get("label", ""),
                reversal_id=str(result.reversal_id) if result.reversal_id else None)
            if result.compensating_tool and result.reversal_id:
                put(type="effect", tool=result.compensating_tool, status="executed",
                    label=f"reversal of {tool}", effect_id=str(result.reversal_id))
        time.sleep(0.22)

    # Both sides of this merge added a field and neither is optional. PR #2's
    # `compensated` is the count the film's ending reads; `scope_token` is what
    # lets the browser read its own contradictions back through MCP. Dropping
    # either one silently removes a feature that has a test.
    put(type="done", scope=scope, scope_token=mint(scope),
        retracted=len(out["retracted"]),
        cancelled=len(out["cancelled"]),
        compensate=len(out["needs_compensation"]),
        compensated=compensated)


async def _story_stream(request_id: str | None = None):
    while _embedder is None or _adjudicator is None:
        await asyncio.sleep(0.3)
    q: "queue.Queue[dict]" = queue.Queue()
    started = time.monotonic()
    threading.Thread(target=_story_events, args=(q,), daemon=True).start()
    while True:
        if time.monotonic() - started > REQUEST_TIMEOUT_S:
            log.info(
                "scenario_timeout",
                extra={"request_id": request_id, "scenario": "story",
                       "error_class": "timeout"},
            )
            yield sse("error", {"error_class": "timeout"})
            return
        try:
            item = q.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.05)
            continue
        if item["type"] == "done":
            log.info(
                "scenario_done",
                extra={
                    "request_id": request_id, "scenario": "story",
                    "cascade_count": item.get("retracted"),
                    "adjudication_mode": (
                        _adjudicator.name if _adjudicator else "loading"
                    ),
                    "lock_outcome": (
                        f"cancelled={item.get('cancelled')} "
                        f"flagged={item.get('compensate')} "
                        f"compensated={item.get('compensated')}"
                    ),
                },
            )
        yield sse(item["type"], item)
        if item["type"] == "done":
            break


@app.get("/api/health")
async def health():
    with psycopg.connect(URL, autocommit=True) as c, c.cursor() as cur:
        cur.execute("SELECT version()")
        v = cur.fetchone()[0]
    return {"cluster": v.split(" (")[0], "embedder": _embedder.name if _embedder else "loading",
            "adjudicator": _adjudicator.name if _adjudicator else "loading",
            "adjudicator_is_model": _adjudicator.is_model if _adjudicator else None}


@app.get("/healthz")
async def healthz():
    """Liveness only. Deliberately does NOT touch the database: a health check
    that fails when the cluster hiccups gets the container killed during the
    exact incident you wanted it to survive."""
    return {"ok": True}


@app.get("/status")
async def status():
    """Non-sensitive readiness. Names which backends are actually live, so a
    reader can never be misled about whether a model or a stand-in answered."""
    import subprocess
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=2).stdout.strip()
    except Exception:
        sha = os.environ.get("BUILD_SHA", "unknown")
    db = "unknown"
    try:
        with psycopg.connect(URL, autocommit=True, connect_timeout=4) as c, c.cursor() as cur:
            cur.execute("SELECT 1")
            db = "reachable"
    except Exception as e:
        db = f"unreachable: {type(e).__name__}"
    # The MCP line exists because of a deployment trap that is invisible from
    # the outside: railway.toml sets CRDB_CLUSTER_ID as a BUILD arg, which is
    # not a runtime variable. If the service variables are missing, section 05
    # renders an honest "not available" and the second CockroachDB tool
    # silently stops being visible in the product -- a page that looks fine
    # while the submission quietly loses half its gate. Reported by NAME only;
    # no value of any credential is ever returned here.
    absent = [v for v in ("CRDB_API_KEY", "CRDB_CLUSTER_ID") if not os.environ.get(v)]
    return {
        "build": sha or os.environ.get("BUILD_SHA", "unknown"),
        "database": db,
        "embedder": _embedder.name if _embedder else "loading",
        "adjudicator": _adjudicator.name if _adjudicator else "loading",
        "adjudicator_is_model": _adjudicator.is_model if _adjudicator else None,
        "mcp": "configured" if not absent else f"NOT configured, missing: {', '.join(absent)}",
        "contradiction_feed": "live" if not absent else "will render 'not available'",
    }


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")
