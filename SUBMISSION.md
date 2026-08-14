# RETRACT — Devpost submission

Answers to the CockroachDB × AWS Hackathon submission form, written from the
rules page rather than from memory of it. Fetched 13 Aug 2026 from
https://cockroachdb-ai.devpost.com/rules — re-read it before pasting, because
this file is a copy and the rules page is the object.

**Deadline: 18 August 2026, 5:00pm Eastern.** That is 23:00 CEST, which is what
PLAN.md says; the two agree. Internal submit target is Sunday 17 Aug 18:00, and
the gap is deliberate.

---

## Gate 1 — at least TWO CockroachDB tools

The rules list four qualifying tools. RETRACT uses three, and the first two are
load-bearing rather than demonstrated.

### 1. CockroachDB Distributed Vector Indexing — carries every read

    schema.sql:35        CREATE VECTOR INDEX memory_ann ON memory (scope, embedding)
    retract/engine.py:112,115   embedding <-> %s::vector ... ORDER BY  (the READ phase)
    retract/engine.py:156       the same search inside contradiction detection

Prefix columns come first because a vector index filter only accelerates on a
prefix. Every agent turn opens with an ANN search over this index at a recorded
snapshot.

**And we measured it rather than trusting it.** `experiments/day1_conflict.py`
tested whether the vector index alone serialises concurrent adjacent writes. It
does not — 13% versus an 8% control, p = 0.15, with the effect shrinking as
power increased. That null result is published in `FINDINGS.md` and is why the
claim lock is explicit instead of implied.

### 2. CockroachDB Cloud Managed MCP Server — the governed read path

    retract/mcp.py              client + GovernedMemoryReader
    app/main.py                 /api/contradictions, served entirely through MCP
    experiments/mcp_eval.py     nine escalating write payloads, all refused
    experiments/feed_eval.py    the feed answers with every SQL path raising

Reads go through the managed endpoint. Writes cannot: the claim lock needs
`SELECT ... FOR UPDATE` inside a multi-statement serializable transaction, and
MCP's write surface is `create_table` / `insert_rows`. Agents therefore read
memory through an endpoint they are structurally incapable of corrupting.

`/api/contradictions` is the only route in the app that does not speak SQL. Its
eval proves that by replacing psycopg with a version that raises on any
connection and asserting the feed still answers — reading the source proves
intent, breaking the other path proves behaviour.

### 3. ccloud CLI (Agent-Ready) — cluster introspection

Installed and authenticated; used for cluster introspection during the build.
**This is the weakest of the three and is claimed as third, not as one of the
required two.** The gate is satisfied by 1 and 2 without it.

## Gate 2 — at least ONE AWS service

**Amazon Bedrock**, generating every vector the index holds.

    retract/embed.py     Amazon Titan Text Embeddings V2, 512 dimensions -- running

Titan alone satisfies this gate: every embedding in the live cluster came from
it, and `/status` on the deployed URL names the model.

    retract/adjudicate.py  Claude on Bedrock -- code path built, NOT running

Say this plainly rather than let a judge find it. `RETRACT_ADJUDICATOR=auto`
resolves to a heuristic stand-in today, because Bedrock answers a Converse call
to `us.anthropic.claude-sonnet-4-5-20250929-v1:0` with `Model use case details
have not been submitted for this account` (probed 14 Aug, us-east-1). The
account has never submitted the Anthropic use-case form, so the model has never
once adjudicated. Every surface says so in the same words: `/status` returns
`"adjudicator": "heuristic (stand-in, not a model)"` and
`"adjudicator_is_model": false`, and the page prints it beside the verdict.

The stand-in scores 7/8 on `experiments/adjudicate_eval.py`, failing the case
that needs real reasoning -- "verified by passport" versus "verified by driving
licence". If the form clears before submission, `RETRACT_ADJUDICATOR=bedrock`
is the only change and the eval is re-run for the 8/8. If it does not clear,
this paragraph is the submission's answer and nothing on any surface claims
otherwise.

The credential on the deploy host carries `bedrock:InvokeModel` on two model
ARNs, and five escalation paths were probed and verified blocked.

---

## What it is, in one paragraph

Shared memory for agent fleets. Exactly one agent decides a given fact at a
time — and when a belief turns out to be wrong, it takes back everything built
on it, including the money that already moved. Concurrency control stops a bad
fact being written; the retraction cascade reaches the bad fact that was
written correctly, believed reasonably, and already paid out.

## The claim nobody else can make

Across roughly twenty agent-memory products examined at source level, none has
any concept of an action attached to a memory. A 435-work survey found 27
exposing rollback and none scoring whether the rollback worked. Every agent
framework can delete a memory; none can tell you what that memory already
caused.

---

## Checklist

Verified means someone ran a command and read the output. Everything else says
what it is.

| Item | State |
|---|---|
| Public repo | **verified** — `Morkeeth/retract`, PUBLIC, default `main` |
| Open-source licence, detectable | **verified** — GitHub REST reports `apache-2.0`. Note: `gh repo view --json licenseInfo` returns null for the same repo while `gh api repos/... -q .license` returns Apache-2.0; the REST answer and `/license` endpoint agree, so the licence IS detected |
| README with setup and run instructions | **unverified** — exists; never run by anyone who is not the author. `/stranger` before submitting |
| Live demo URL | **partly** — https://retract-production.up.railway.app is up, but the last three commits are undeployed |
| Video, under 3:00 | **NOT DONE** — script is `DEMO.md`, cut lands 2:55, nothing shot |
| Video public on YouTube or Vimeo | **NOT DONE** — hosting is a rules requirement, not a preference |
| Which CockroachDB tools + how | **done** — this file |
| Which AWS services + how | **done** — this file |
| Architecture diagram | optional, not doing. See `ROADMAP.md` on the second signature device |
| Feedback on CockroachDB AI tools | optional, and we have unusually specific feedback: the 0.80 reuse threshold in Cockroach's own agent-memory post is inverted on their partner's embedding model. Worth submitting |

## Open risks, named

1. **The video does not exist.** It is the only hard-fail on the list that
   cannot be produced in the last hour, and it needs PR #2 merged first so the
   film can end on the reversal rather than on a flag.
2. **Three commits are undeployed.** The scope fix, the Bedrock spend fix and
   the contradiction feed are all on local `main` only. A judge opening the URL
   today sees none of them.
3. **The contradiction feed needs runtime variables on Railway.** `railway.toml`
   sets `CRDB_CLUSTER_ID` as a BUILD arg; the feed needs it and `CRDB_API_KEY`
   as service variables. Load `/status` after deploying — it now reports which
   are missing by name.
4. **PR #2 has never run against the live cluster.** `experiments/verify_live.sh`
   settles it in one pass and refuses to apply the migration on its own.
5. **`scope` enforcement is not authentication.** It proves the caller was
   granted a scope, not who the caller is. Stated in `retract/scope.py` rather
   than left to be found by a judge.
