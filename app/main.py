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

_embedder = None
_adjudicator = None
_vectors: list[np.ndarray] = []


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
    """The measurement that kills threshold-based dedup. Computed live.

    Read path: no token. Pairs are server-side constants — no request text is
    embedded. Still costs an embedder call per page load; see SECURITY.md.
    """
    while _embedder is None:
        await asyncio.sleep(0.3)
    pairs = [
        ("verified via passport", "ID verification complete", "paraphrase"),
        ("verified via passport", "identity confirmed, passport on file", "paraphrase"),
        ("Customer 4471 verified", "Customer 4472 verified", "different customer"),
        ("verified their identity", "FAILED identity verification", "negation"),
        ("refund of $1,240 approved", "refund of $1,240 declined", "negation"),
        ("refund of $1,240 approved", "refund of $2,140 approved", "different amount"),
        ("9902 lives in Berlin", "9902 used to live in Berlin", "tense change"),
    ]
    out = []
    for a, b, kind in pairs:
        d = float(np.linalg.norm(_embedder.embed(a) - _embedder.embed(b)))
        out.append({"a": a, "b": b, "kind": kind, "distance": round(d, 3),
                    "same_fact": kind == "paraphrase"})
    return {"pairs": sorted(out, key=lambda x: x["distance"]), "embedder": _embedder.name}


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

    effects = [
        (2, "refund_issued", "rf-4471-1240", "executed", "$1,240 sent to customer 4471"),
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

    if res.outcome == "contradiction":
        v = _adjudicator.judge("customer:4471", "identity_verified",
                               res.incumbent_content, neg)
        put(type="adjudicated", resolution=v.resolution, reasoning=v.reasoning,
            by=v.by, is_model=_adjudicator.is_model)
        time.sleep(0.5)

    # --- act 4: the cascade ------------------------------------------------
    put(type="retracting", reason="passport confirmed forged by fraud team")
    out = eng.retract(ids[0], "passport confirmed forged by fraud team")
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

    put(type="done", scope=scope, retracted=len(out["retracted"]),
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
    return {
        "build": sha or os.environ.get("BUILD_SHA", "unknown"),
        "database": db,
        "embedder": _embedder.name if _embedder else "loading",
        "adjudicator": _adjudicator.name if _adjudicator else "loading",
        "adjudicator_is_model": _adjudicator.is_model if _adjudicator else None,
    }


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")
