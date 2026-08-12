# RETRACT

**Shared memory for agent fleets. Exactly one agent decides a given fact at a
time — and when a belief turns out to be wrong, it takes back everything built
on it, including the money that already moved.**

Built for the CockroachDB × AWS Hackathon, August 2026.

---

## The problem

Run more than one agent against a shared memory and two things break that a
single-agent memory never surfaces.

**Concurrent agents corrupt shared beliefs.** Eight agents learn the same fact
about a customer at the same moment, each phrasing it differently. A naive
memory ends up holding eight contradictory beliefs about one fact — and eight
different *keys* for one customer, because the agents also spell the subject
eight different ways.

**A belief that turns out wrong has already been acted on.** By the time a
forged passport is discovered, the refund it justified has been sent. Deleting
the memory does not un-send the money, and a memory that cannot reach its own
side effects is a diary, not a system of record.

## The approach

**Identity does not come from the embedding.** We measured this rather than
assumed it: on two independent production embedding models, a paraphrase and a
flat negation can sit 0.001 apart, and a different customer can be *nearer* than
the same fact reworded. Full data in [FINDINGS.md](FINDINGS.md). So identity
comes from a canonical `(subject, predicate)` claim key, and vectors do retrieval
— the job they are actually good at.

**A turn is three phases**, because a transaction cannot be held open across LLM
inference:

| | |
|---|---|
| **READ** | ANN search over the distributed vector index at a recorded snapshot. No locks survive. |
| **THINK** | The model decides, and names the claim it wants to assert. Entirely outside any transaction. |
| **COMMIT** | A short serializable transaction: lock the claim key, look at what is already believed, then write — or raise a contradiction. |

**What the database guarantees, and what it does not.** It guarantees that
exactly one agent adjudicates a claim key at a time, and that the outcome is
recorded atomically with the memory and the side effects it touches. It does not
guarantee the adjudication is correct — a model does that, and the page says so.

**Retraction walks a derivation DAG.** Retracting a belief retracts every belief
derived from it, cancels their *pending* side effects, and flags the
*already-executed* ones as `needs_compensation` rather than silently cancelling
them. Unrelated beliefs are left alone — the blast radius is asserted in the
tests, because a cascade that retracts everything is as wrong as one that
retracts nothing.

## Run it

```bash
git clone <this repo> && cd retract
uv sync

# CockroachDB Cloud connection string
export CRDB_URL='postgresql://user:pass@host:26257/defaultdb?sslmode=verify-full'
uv run python -c "
import psycopg,os,pathlib
for f in ('schema.sql','schema_v2.sql'):
    sql='\n'.join(l for l in pathlib.Path(f).read_text().splitlines() if not l.strip().startswith('--'))
    with psycopg.connect(os.environ['CRDB_URL'],autocommit=True) as c,c.cursor() as cur:
        for s in [x.strip() for x in sql.split(';') if x.strip()]: cur.execute(s)
"

# no AWS account? this runs entirely offline:
RETRACT_EMBEDDER=local RETRACT_ADJUDICATOR=heuristic uv run uvicorn app.main:app --port 8117
```

Open http://localhost:8117. First load takes ~8s while the embedding model warms.

With AWS configured, `RETRACT_EMBEDDER=bedrock RETRACT_ADJUDICATOR=bedrock` swaps
in Titan embeddings and Claude adjudication. Everything else is identical.

## The evals

Every eval has a control arm. A number without one proves nothing.

```bash
uv run python experiments/race.py --mode naive     # 8 agents, no lock  -> 8 beliefs
uv run python experiments/race.py --mode retract   # 8 agents, RETRACT  -> 1 belief
uv run python experiments/cascade.py               # 8 assertions on the blast radius
uv run python experiments/probe_real_geometry.py   # why distance cannot decide
uv run python experiments/day1_conflict.py         # does the ANN read serialise? (no)
uv run python experiments/adjudicate_eval.py       # paraphrase vs contradiction
```

| Eval | Result |
|---|---|
| `race --mode naive` | **8** active beliefs, **8** distinct claim keys, 0 contradictions seen |
| `race --mode retract` | **1** active belief, **1** claim key, 7 contradictions raised |
| `cascade` | 8/8 — including *"9902 untouched"* and *"executed refund → needs_compensation"* |
| `day1_conflict` | NEAR 13% vs FAR 8%, p = 0.15 — **not significant**, published anyway |

## CockroachDB tools used

**Distributed Vector Indexing (C-SPANN)** — `CREATE VECTOR INDEX ON memory
(scope, embedding)`, prefix-ordered so the scope filter accelerates. Every agent
turn opens with an ANN search over it. Load-bearing: remove it and the READ phase
has nothing to read.

**Serializable transactions + durable locking** — the claim lock runs with
`enable_durable_locking_for_serializable = true`, because unreplicated
`FOR UPDATE` locks are documented as best-effort and must not be relied on for
correctness. The commit phase is multi-round-trip, so automatic retry never
fires and the client owns the `40001` loop; `inject_retry_errors_enabled` is how
we prove that loop works instead of asserting it.

**Bitemporal memory + append-only audit** — `AS OF SYSTEM TIME` is bounded by a
4-hour GC window on this cluster, so time travel is a fast path and never the
record. The audit substrate is explicit rows, which is also the stronger artifact:
a reviewer can query a table and cannot query an engine feature.

## AWS services used

**Amazon Bedrock — Titan Text Embeddings V2** at 512 dimensions, generating every
vector CockroachDB indexes. (Titan accepts 256/512/1024 and *rejects* 384, which
forced a schema migration — measured, not assumed.)

**Amazon Bedrock — Claude** as the adjudicator, via the `us.` inference profile;
the bare model id is not invocable on demand.

Both sit behind interfaces (`retract/embed.py`, `retract/adjudicate.py`) so the
whole project runs with no AWS account at all. The fallbacks are labelled
`is_model = False` where they are not models, and the running backend is printed
on the page — a stand-in must never be able to pass as the real thing.

## Layout

```
retract/engine.py    three-phase commit, contradiction detection, retraction cascade
retract/claim.py     canonicalisation — the guarantee lives here, so it is boring by design
retract/embed.py     Titan / local / hash, each declaring its own dimension
retract/adjudicate.py Claude / heuristic stand-in
schema.sql           memory (bitemporal), derivation DAG, effect ledger, audit log
schema_v2.sql        the claim key and contradiction tables
app/                 the demo surface — every number is a live transaction
experiments/         evals, each with a control arm
FINDINGS.md          two negative results that changed the design
DEMO.md              shot-by-shot script for the video
```

## Licence

Apache 2.0.
