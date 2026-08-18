# RETRACT

**A wrong belief has already moved money. RETRACT is the shared memory that can
reach what that belief caused — and reverse it.**

Shared memory for agent fleets, built for the CockroachDB × AWS Hackathon,
August 2026. Live demo: https://retract-production.up.railway.app

---

## The problem

By the time a forged passport is discovered, the refund it justified has been
sent. Deleting the memory does not un-send the money. A memory that cannot reach
its own side effects is a diary, not a system of record.

Run more than one agent against a shared memory and a second thing breaks that a
single-agent memory never surfaces: concurrent agents corrupt shared beliefs.
Eight agents learn the same fact about a customer at the same moment, each
phrasing it differently, and a naive memory ends up holding eight contradictory
beliefs — and eight different *keys* — for one customer.

Both failures matter. The one almost nobody else has a concept for is the first.

Across roughly twenty agent-memory products examined at source level, **none has
any concept of an action attached to a memory**. A 435-work survey found 27
exposing rollback and none scoring whether it worked. Reaching the side effects
a wrong belief already caused — and reversing them — is the unoccupied cell.

---

## The approach

**Retraction walks a derivation DAG, then compensation closes the loop.**
Retracting a belief retracts every belief derived from it, cancels their
*pending* side effects, and flags the *already-executed* ones as
`needs_compensation`. A registered handler then writes a reversal effect with
its own idempotency key (`comp:<original>`), moves the original to
`compensated`, and records the reversal id — in the same transaction. A tool
with no handler stays flagged; silently greening it would be the failure mode
this project exists to argue against. Unrelated beliefs are left alone — the
blast radius is asserted in the tests, because a cascade that retracts
everything is as wrong as one that retracts nothing.

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
exactly one agent holds a given claim key inside the commit transaction at a
time (a lock row taken with durable locking enabled so a lease transfer cannot
drop it), and that the outcome is recorded atomically with the memory and the
side effects it touches. It does not guarantee the adjudication is correct — a
model does that, and the page says so. As of **14 Aug 2026, 09:30 CEST** the
live adjudicator is **Claude on Bedrock** — `/status` returns
`"adjudicator": "bedrock:claude"` and `"adjudicator_is_model": true`. Until
that morning it was a labelled heuristic stand-in, blocked on a one-time
Anthropic use-case form; the form cleared and the next container restart picked
the model up through the `auto` path. A stand-in must never be able to pass as
the real thing, which is why the page prints whichever one is running rather
than what this file hopes is running.

Read the next section before treating that as good news: on
`experiments/adjudicate_eval.py` the model scores **7/8**, the same score the
stand-in got, on a different case.

---

## Architecture

```mermaid
flowchart TB
    FLEET["Agent fleet — concurrent agents"]

    subgraph aws["AWS Bedrock"]
        TITAN["Titan Text Embeddings V2 — 512-dim vectors"]
        CLAUDE["Claude adjudicator — reads the two claims"]
    end

    subgraph crdb["CockroachDB Cloud"]
        MCP["Cloud Managed MCP Server — governed read path, mcp:read"]
        VEC["Distributed Vector Index — C-SPANN"]
        MEM["Memory + derivation DAG — bitemporal rows"]
        COMMIT["COMMIT — serializable txn, claim-key lock, durable locking"]
        RETRACT["Retraction cascade — walks the DAG"]
        HANDLER["Compensation handler — writes reversal comp:key"]
        LEDGER["Effect ledger + append-only audit log"]
    end

    FLEET -->|"READ: ANN search at a snapshot"| VEC
    FLEET -->|"inspect beliefs, read-only"| MCP
    FLEET -->|"THINK: name the claim, no txn"| CLAUDE
    TITAN -->|"embeds every claim"| VEC
    MCP --> MEM
    VEC --> MEM
    CLAUDE -->|"verdict on contradiction"| COMMIT
    COMMIT --> MEM
    MEM -->|"belief proven wrong"| RETRACT
    RETRACT -->|"cancel pending effects"| LEDGER
    RETRACT -->|"flag executed as needs_compensation"| HANDLER
    HANDLER -->|"reversal, same txn"| LEDGER
    LEDGER -->|"status: compensated"| MEM
```

**READ** searches the distributed vector index (and can inspect the fleet's
beliefs through the governed Cloud MCP read path, which is structurally
write-incapable). **THINK** happens outside any transaction; Claude on Bedrock
adjudicates a contradiction. **COMMIT** takes the claim-key lock in a
serializable transaction. When a belief is later proven wrong, the retraction
cascade walks the derivation DAG, cancels *pending* effects, and flags
*already-executed* ones `needs_compensation`; the compensation handler writes a
reversal with its own `comp:<key>` idempotency key in the same transaction.
Titan embeddings feed the index; every belief, effect and reversal is a durable
row in the ledger.

---

## Run it

```bash
git clone <this repo> && cd retract
uv sync

# CockroachDB connection string (Cloud: verify-full + cluster CA; local insecure OK for offline)
export CRDB_URL='postgresql://user:pass@host:26257/defaultdb?sslmode=verify-full'
uv run python -c "
import psycopg,os,pathlib
for f in ('schema.sql','schema_v2.sql','schema_v3.sql'):
    sql='\n'.join(l for l in pathlib.Path(f).read_text().splitlines() if not l.strip().startswith('--'))
    with psycopg.connect(os.environ['CRDB_URL'],autocommit=True) as c,c.cursor() as cur:
        for s in [x.strip() for x in sql.split(';') if x.strip()]: cur.execute(s)
"

# Write paths fail closed without a token.
export DEMO_TOKEN='some-long-random-string'

# no AWS account? this runs entirely offline (hash is plumbing-only — not semantic):
RETRACT_EMBEDDER=hash RETRACT_ADJUDICATOR=heuristic \
  uv run uvicorn app.main:app --port 8117
```

Open http://localhost:8117. Paste the demo token into the header field before
clicking either write button. First load takes a few seconds while the embedder
warms.

With AWS configured, `RETRACT_EMBEDDER=bedrock` swaps in Titan embeddings.
Everything else is identical. Do not point `RETRACT_EMBEDDER=local` at a
512-dim schema: MiniLM is 384-dim and the engine will refuse the write rather
than pad.

`RETRACT_ADJUDICATOR=bedrock` gives you Claude, as of 14 Aug. Before that
morning it did not, and this paragraph said so; the blocker was the one-time
Anthropic use-case form on the AWS account, not the code. Two things are worth
keeping from that history:

- The **default model id is pinned for a reason**. The host IAM user is scoped
  to specific model ARNs, so `us.anthropic.claude-sonnet-4-5-20250929-v1:0`
  works and a newer id does not — a Converse call to
  `us.anthropic.claude-sonnet-4-6` with that credential returns
  `AccessDeniedException ... not authorized to perform: bedrock:InvokeModel`
  (probed 14 Aug, us-east-1). Changing `RETRACT_ADJUDICATOR_MODEL` means
  widening the IAM policy too, or the demo fails closed at the first
  contradiction.
- The explicit `bedrock` path does **not** warm up or fall back the way the
  embedder's `auto` does. It constructs a client and raises on the first real
  adjudication. `auto` probes at startup and degrades to the labelled stand-in,
  which is how the deployed demo survived the days before access landed.

---

## The evals

Every eval has a control arm. A number without one proves nothing.

```bash
uv run python experiments/race.py --mode naive     # 8 agents, no lock  -> 8 beliefs
uv run python experiments/race.py --mode retract   # 8 agents, RETRACT  -> 1 belief
uv run python experiments/cascade.py               # 8 assertions on the blast radius
uv run python experiments/compensate_eval.py       # flag -> reversal; no-handler control
uv run python experiments/probe_real_geometry.py   # why distance cannot decide
uv run python experiments/day1_conflict.py         # does the ANN read serialise? (no)
uv run python experiments/adjudicate_eval.py       # paraphrase vs contradiction
```

| Eval | Result |
|---|---|
| `race --mode naive` | **8** active beliefs, **8** distinct claim keys, 0 contradictions seen — same cluster, same table, same embeddings, no claim lock |
| `race --mode retract` | **1** active belief, **1** claim key, 7 contradictions raised |
| `cascade` | 8/8 — including *"9902 untouched"* and *"executed refund → needs_compensation"* |
| `compensate_eval` | refund ends `compensated` with one reversal row; unregistered tool stays `needs_compensation`; unrelated customer untouched. Run against the live Cloud cluster on 14 Aug with the real Titan embedder (step 3 of `experiments/verify_live.sh`); the no-handler control arm was also watched failing when a handler was patched in |
| `day1_conflict` | NEAR 13% vs FAR 8%, p = 0.15 — **not significant**. We tested whether the explicit lock could be dropped in favour of the vector index. It cannot |

---

## CockroachDB tools used

**Cloud Managed MCP Server** — the agents' governed read path. Reads go through
the managed endpoint at `https://cockroachlabs.cloud/mcp`, authenticated by a
Cloud service account and scoped `mcp:read`. Writes never do, and *cannot*: the
claim lock needs `SELECT ... FOR UPDATE` inside a multi-statement serializable
transaction, which MCP's surface has no way to express.

So agents inspect the fleet's beliefs through an endpoint they are structurally
incapable of corrupting via the read tool, while every mutation is funnelled
through the one code path that takes the lock. `experiments/mcp_eval.py`
verifies this rather than asserting it — nine escalating write attempts through
the read tool (plain DML, stacked statements, a CTE-wrapped DELETE, comment-
and newline-obscured payloads), all nine refused, with the memory re-read
afterwards to confirm nothing changed.

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

---

## AWS services used

**Amazon Bedrock — Titan Text Embeddings V2** at 512 dimensions, generating every
vector CockroachDB indexes. (Titan accepts 256/512/1024 and *rejects* 384, which
forced a schema migration — measured, not assumed.)

**Amazon Bedrock — Claude as the adjudicator: running since 14 Aug, scoring
7/8.** The state belongs in the bold line, because a sponsor-tech list is read
by skimming and a correction two sentences down does not survive a skim. It
adjudicates every contradiction the live demo raises, via
`us.anthropic.claude-sonnet-4-5-20250929-v1:0`; the `us.` inference profile is
required, as the bare model id is not invocable on demand. It scores 7/8 on
`experiments/adjudicate_eval.py` — not 8/8, which earlier drafts of this repo
predicted it would — and the eval's exit code says so.

Both sit behind interfaces (`retract/embed.py`, `retract/adjudicate.py`) so the
whole project runs with no AWS account at all. The fallbacks are labelled
`is_model = False` where they are not models, and the running backend is printed
on the page.

---

## Layout

```
retract/engine.py        three-phase commit, contradiction detection, retraction cascade
retract/compensate.py    registry + handler: needs_compensation → compensated
retract/claim.py         canonicalisation — the guarantee lives here, so it is boring by design
retract/embed.py         Titan / local / hash, each declaring its own dimension
retract/adjudicate.py    Claude / heuristic stand-in
retract/mcp.py           the governed read path — reads only, structurally
schema.sql               memory (bitemporal), derivation DAG, effect ledger, audit log
schema_v2.sql            the claim key and contradiction tables
schema_v3.sql            compensated status + compensated_by (ALTER path)
app/main.py              demo surface — every number is a live transaction
app/middleware.py        demo token, rate limit, size cap, structured logs
app/static/index.html    the page
Dockerfile               Bedrock-only image; no torch, no silent fallback
experiments/             evals, each with a control arm
SECURITY.md              what is proven and what is demo scaffolding
FINDINGS.md              two negative results that changed the design
RELATED-WORK.md          convergent work, and what is actually ours
DEMO.md                  shot-by-shot script for the video
NIGHT-RUN.md             overnight brief this change set answered
```

## Licence

Apache 2.0.

See [SECURITY.md](SECURITY.md) for the blast radius, honestly described.
