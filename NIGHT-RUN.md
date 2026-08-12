# Night run brief — 13/14 Aug 2026

You are working alone overnight on a hackathon submission due **18 Aug 2026,
23:00 CEST**. The owner is asleep and will review in the morning. Nobody will
answer questions, so where this brief is ambiguous, choose the smaller reversible
option and write down what you chose and why.

Read `README.md`, `PLAN.md`, `FINDINGS.md` and `RELATED-WORK.md` before touching
anything. They are short and they contain the reasoning behind every decision
below.

---

## What you do not have, and what follows from it

You have the repository. You do **not** have the `.env`, the database password,
the AWS credentials, or the Railway token. So:

- **You cannot run the evals against the live cluster.** `race.py`, `cascade.py`,
  `day1_conflict.py`, `mcp_eval.py` and `probe_real_geometry.py` all need
  `CRDB_URL` or AWS. Do not try, and do not stub them out to make them pass.
- **You cannot deploy.** The live demo is at
  https://retract-production.up.railway.app and it stays as it is tonight.
- **You can** read it, run anything offline, write code, write tests, and reason
  about the design.

For offline work, `RETRACT_EMBEDDER=hash` gives a deterministic, semantics-free
embedder that exercises plumbing without a network call. It is explicitly *not*
semantic — never use it to make a claim about meaning, and never let it become a
default anywhere.

**Deliver one pull request against `main`. Do not merge it.**

---

## The standard everything here is held to

This project's whole argument is that it measured things other people assumed.
That standard applies to your work too:

- **Every claim needs a control.** A test that passes when the feature is removed
  proves nothing. If you add a guard, add the case that fires when the guard is
  absent.
- **Never state something you have not observed.** If you cannot verify it
  tonight, write "unverified" next to it. That is a complete and acceptable
  answer.
- **A green test that tested nothing has already happened twice on this project**
  and both times the harness was at fault, not the code. Both are documented at
  the end of `FINDINGS.md`. Read them; they are the failure mode most likely to
  catch you tonight.
- Match the surrounding code: full sentences in comments, reasoning rather than
  restatement, and no comment that just says what the next line does.

---

## Task 1 — Execute a compensation *(the most valuable thing in this brief)*

**Why this matters more than anything else here.** A competitive review of about
twenty agent-memory products found that **none of them has any concept of an
action attached to a memory**. A 435-work survey found 27 exposing rollback and
none scoring whether it worked. Reaching side effects a wrong belief already
caused is the one genuinely unoccupied position this project has.

Right now RETRACT stops one step short. `MemoryEngine.retract()` walks the
derivation DAG, cancels *pending* effects, and flags *already-executed* ones as
`needs_compensation`. It never reverses them. A flag nobody watches fire is a
claim, not a control.

**Build the compensation handler.**

- A registry mapping a tool name to its compensating action —
  `refund_issued → refund_reversed`, `tier_upgrade → tier_downgrade`,
  `welcome_email → correction_email`. Keep it small and obvious.
- Each compensation writes a **new** `effect` row carrying its own idempotency
  key derived from the original (e.g. `comp:<original key>`), so replaying a
  compensation cannot double-fire. The `UNIQUE (scope, idempotency_key)`
  constraint already in `schema.sql` is what enforces this — lean on it rather
  than checking in application code.
- The original row moves `needs_compensation → compensated` and records the id of
  the reversal, in the **same transaction** that writes the reversal.
- A tool with no registered compensation must stay `needs_compensation` and be
  surfaced. Silently marking it done would be the exact dishonesty this project
  exists to argue against.

**Then write `experiments/compensate_eval.py`** in the style of
`experiments/cascade.py` — assertions written from the task, not from the code,
with a control arm. At minimum:

- the executed refund ends `compensated`, with a reversal row that points back
- running the compensation twice produces **one** reversal, not two
- a tool with no handler stays `needs_compensation` — this is the control
- an unrelated customer's effects are untouched

It needs the live cluster, so it will not run for you. Write it to be correct and
say clearly in the PR that it is **unrun**.

---

## Task 2 — Harden the public demo

The deployed demo currently has **no authentication and writes to a live
database**, holding a credential that can call a paid API. That is the worst
thing in the build. It is also the cheapest points on the board: an independent
review scored Production Readiness 9/20, and this work takes it to roughly 16.

1. **Demo token on every write path.** `/api/story` and `/api/race` require a
   `DEMO_TOKEN`; the static page and read endpoints stay open. When `DEMO_TOKEN`
   is unset, fail **closed** with a clear error, not open.
2. **Per-IP rate limiting** on those endpoints, plus a request-size cap and a
   per-request timeout. In-process is fine; there is one instance.
3. **Preset scenarios only.** Three or four server-side scenario IDs. No text
   from a request may ever reach an embedding or a model call. This bounds spend
   by construction and removes prompt injection into a paid path as a category,
   rather than filtering for it.
4. **Structured JSON logs to stdout**: request id, claim id, adjudication mode,
   lock outcome, cascade count, error class. Never a connection string, never a
   raw prompt.
5. **`SECURITY.md`**, honest in both directions. Proven: MCP writes refused
   across nine escalating payloads (`experiments/mcp_eval.py`), serializable
   commit with a durable lock row, an AWS credential scoped to
   `bedrock:InvokeModel` on exactly two model ARNs with five escalation paths
   verified blocked. Demo scaffolding: single tenant, disposable data, no real
   authn, `scope` is a caller-supplied string with nothing enforcing it.

Put the middleware in `app/middleware.py` and keep the change in `app/main.py`
small.

---

## Task 3 — Reframe the README around the return arc

The current README leads with concurrency. The research says that is the wrong
lead: seven parties reached "agreement, not retrieval" this year, and MemTX
([arXiv:2607.23929](https://arxiv.org/abs/2607.23929)) published the full stack
three weeks ago. Concurrency is occupied territory.

**Lead instead with what a wrong belief already caused, and how to reach it.**
Same system, different first paragraph. The refund that already went out is the
opening image, not the third act.

While you are there:

- The layout block must match the files that actually exist.
- Nothing may imply Claude is adjudicating. It is a labelled heuristic stand-in
  pending a one-time Anthropic use-case form the owner has to submit. The page
  prints which one is live; keep the docs consistent with that.
- Do not write "production-ready" anywhere.

Do **not** rewrite `FINDINGS.md` or `RELATED-WORK.md`. They were rewritten
tonight against verified sources and their claims are calibrated deliberately.

---

## Task 4 — Only if 1 to 3 are genuinely finished

A `LICENSE`-detectable check, an architecture diagram in the README as a mermaid
block, and a `Makefile` or `justfile` with one command per eval.

Do not start Task 4 to avoid finishing Task 1.

---

## What not to do

- Do not merge your own PR.
- Do not touch `FINDINGS.md`, `RELATED-WORK.md` or `schema_v2.sql`.
- Do not add a dependency without saying why in the PR description.
- Do not add multi-tenancy, a LangGraph adapter, or a contradiction-feed UI. All
  three were considered and explicitly cut; the reasoning is in `PLAN.md`.
- Do not re-run or "fix" the evals to make them pass. They pass on the owner's
  machine against the live cluster.

## The PR description

State plainly: what you built, what you verified and how, what is **unrun** and
why, every judgement call you made where the brief was ambiguous, and anything
you believe is wrong with the plan. That last one is welcome — the owner has
changed direction twice today on evidence.
