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

    retract/adjudicate.py  Claude on Bedrock -- running since 14 Aug, 09:30 CEST

Both AWS services are live. `/status` on the deployed URL returns
`"adjudicator": "bedrock:claude"` and `"adjudicator_is_model": true`, and the
page prints whichever backend is running beside every verdict.

This section said the opposite earlier the same morning, and the history is
worth keeping rather than overwriting. Until the Anthropic use-case form on the
AWS account cleared, a Converse call returned `Model use case details have not
been submitted for this account` and the demo ran a labelled heuristic
stand-in. The form was the entire blocker; no code changed. The `auto` path
probes Bedrock at startup, so the next container restart picked the model up on
its own.

**And the honest part, which is not the good news.** Earlier drafts predicted
Claude would score 8/8 on `experiments/adjudicate_eval.py`. It does not. Run
against the real model on 14 Aug it scores **7/8** -- the same number the
stand-in got, on a *different* case. It passes the one the stand-in failed
("verified by passport" versus "verified by driving licence") and fails a case
the stand-in passed: shown a generic claim and a more specific version of the
same fact, it answers `superseded` where the eval expects `duplicate`. Its
stated reasoning is that the more detailed claim should replace the generic
one, which is a defensible reading -- the eval's expectation may be the thing
that is wrong. Either way the eval exits 1 and nothing here claims 8/8.

One further caveat on that 7/8, because the number is weaker than it looks:
the eval's not-duplicate arm asserts only `resolution != "duplicate"`. All five
not-duplicate cases came back `superseded`, so those five assertions confirm
the model did not say "duplicate" and nothing more. A negation answered
`superseded` rather than `rejected` would pass. The 7/8 is a real run of a real
model and it is not a strong measurement of adjudication quality.

### Open question: is the failing case a model error or an eval error?

Left open on purpose. It could be closed by editing one line of
`experiments/adjudicate_eval.py`, and editing it would make the number 8/8,
which is the reason not to.

The case: the incumbent is a generic claim and the challenger is the same fact
with more detail. The eval expects `duplicate`. Claude answers `superseded`,
reasoning that *"the challenger provides more specific information … making it
a more detailed version that should replace the generic incumbent statement."*

Both readings are coherent, and which one is right is a product decision this
project has not made:

- **`duplicate` is right** if a claim key holds *the fact*, and detail is a
  property of the sentence rather than of the belief. Then the specific version
  adds nothing to retract, and merging is correct.
- **`superseded` is right** if the memory is meant to hold the best available
  statement of a fact. Then replacing the vague version with the precise one is
  the memory improving, and `superseded` records exactly that — with the
  original still readable, because the schema is bitemporal and nothing is
  destroyed.

The consequence is not cosmetic. `superseded` closes the incumbent's
`valid_to`, so any effect justified by it becomes reachable by a retraction of
the newer belief. `duplicate` leaves the original standing and the challenger
unwritten. Two different derivation graphs, and this project's entire argument
is about what a retraction can reach through that graph.

What can be said without deciding: the model's answer is defensible, the eval
asserts one of the two readings without ever having argued for it, and the
score is 7/8 either way. Deciding this properly needs the question put to
someone who runs an agent fleet, not to whoever is holding the keyboard four
days before a deadline.

The credential on the deploy host carries `bedrock:InvokeModel` on two model
ARNs, and five escalation paths were probed and verified blocked.

---

## What it is, in one paragraph

Shared memory for agent fleets. Exactly one lock holder commits a given fact
at a time — and when a belief turns out to be wrong, it takes back everything built
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
