# Morning run brief — Thu 14 Aug 2026

You are the owner plus Claude Code. Deadline **18 Aug 2026, 23:00 CEST**.
Feature freeze **Fri 15, 18:00**. Today's hard gate: **compensation executing on
the public URL by 20:00**.

Read, in this order, before touching anything:

1. `OVERNIGHT-HANDOFF.md` — what landed overnight, what is unrun, every judgement
2. `PLAN.md` — Day 2 and Day 3 (you are about to compress both into today)
3. `README.md`, `FINDINGS.md`, `RELATED-WORK.md` — short; they carry the argument
4. PR https://github.com/Morkeeth/retract/pull/2 — do **not** merge until Gate 0
   below is green

The overnight agent had **no secrets**. You do. That is the whole difference.
Use them. Do not spend the morning re-deriving what is already in the PR.

---

## The standard (same as the night brief — non-negotiable)

This project's argument is that it measured things other people assumed. That
standard applies to your work too:

- **Every claim needs a control.** A test that passes when the feature is removed
  proves nothing.
- **Never state something you have not observed.** Unverified is a complete answer.
- **A green test that tested nothing has already happened twice on this project**
  (end of `FINDINGS.md`). Both times the harness was at fault. Read them before
  you trust any number you produce today.
- Match the surrounding code: full sentences in comments, reasoning rather than
  restatement, no comment that just narrates the next line.
- **Do not stub evals green.** An unrun test honestly labelled beats a passing
  one that tests nothing. You have the cluster now — so *run* them, against Cloud,
  with Titan if Bedrock is up.

Where this brief is ambiguous, choose the smaller reversible option and write
down what you chose and why. Disagreement with the plan is welcome — the owner
has reversed twice on evidence already. Put it in the PR description.

**Deliver one pull request against `main` for net-new morning work** (or extend
PR #2 if still open and not yet merged). Do not merge your own PR. The owner
merges after Gate 0.

---

## Gate 0 — Land the overnight PR *(first 45 minutes, nothing else until done)*

PR #2 already contains compensation, hardening, and the README reframe. It is
worthless until it runs on Cloud and is live.

1. **Apply `schema_v3.sql` on the live CockroachDB Cloud cluster.** Fresh
   installs get it from `schema.sql`; the live DB needs the ALTER path. Confirm
   `compensated` is a legal `effect.status` and `compensated_by` exists.
2. **Set `DEMO_TOKEN` on Railway** to a long random value. Without it, write
   paths fail closed by design — the deployed demo's buttons will appear broken
   until this is set *and* the new static page is deployed.
3. **Redeploy PR #2** (or merge-then-deploy if you prefer merge-first; either
   way the public URL must be running this code before Gate 0 closes).
4. **Run against Cloud, with the real embedder:**
   ```bash
   RETRACT_EMBEDDER=bedrock RETRACT_ADJUDICATOR=heuristic \
     uv run python experiments/compensate_eval.py
   RETRACT_EMBEDDER=bedrock uv run python experiments/cascade.py
   RETRACT_EMBEDDER=bedrock uv run python experiments/race.py --mode retract
   RETRACT_EMBEDDER=bedrock uv run python experiments/race.py --mode naive
   ```
   Paste real output into the README table. The overnight local `hash` numbers
   do **not** count. If `compensate_eval` fails on Cloud, **stop and fix — do
   not start Task A.**
5. **Incognito check on https://retract-production.up.railway.app** with the
   demo token: Run the story, live → ledger shows
   `needs_compensation → compensated` with a reversal id. Screenshot it.
6. **Edit `RELATED-WORK.md`** — the sentence that says reversal is "in progress"
   and the ledger stops at `needs_compensation` is now false. Fix it. The night
   brief forbade the overnight agent from touching this file; you are not under
   that constraint.
7. **Merge PR #2** only after steps 4–6 are green.

**Gate 0 check:** a stranger with the demo token, on cellular, watches a real
reversal land in the ledger on the public URL. Until that is true, every later
task is theatre.

**Submit the Anthropic use-case form in parallel with Gate 0.** One console
screen. It is the only thing between the video and a labelled model. Do it
before coffee gets cold.

---

## Task A — Act 5 on the demo surface *(the film ending)*

The story scenario already *calls* `compensate()`. The page still *reads* like
the film ends on a flag. Fix the surface so a cold viewer understands the money
came back.

- Dedicated visual beat after the cascade: the refund row flips
  `NEEDS COMPENSATION → COMPENSATED`, the `refund_reversed` row appears with its
  own id, and the punch line ends on the reversal — not on the flag.
- Update `DEMO.md` shot list: the 60s retraction beat becomes retraction **and
  reversal**. Timings measured against the deployed URL, not localhost.
- Header / copy honesty: if Claude is still pending the Anthropic form, every
  surface that names the adjudicator still says heuristic stand-in. Never a
  silent substitute. When Bedrock Claude is approved mid-day, flip
  `RETRACT_ADJUDICATOR=bedrock`, re-run `experiments/adjudicate_eval.py`
  (expect 8/8), and reshoot only the adjudication beat.

**Check:** a person who has never seen the project can, from the public URL
alone, say: *"it found the refund the bad belief caused, and reversed it."*

**Cut if long:** polish. The beat existing and ending the story is the gate;
motion design is not.

---

## Task B — Enforce `scope` *(do not cut this)*

`PLAN.md` Day 3 marks this cut-if-long. **Override that cut.** For a product
whose pitch is *governed* shared memory, a caller-supplied `scope` with nothing
checking it is the first Production Readiness question a sponsor engineer asks.
Leaving it open after compensation ships is how the scoreboard undoes Gate 0.

Minimum viable enforcement (pick the smallest thing that is real):

- Demo scenarios mint an unguessable scope server-side and never accept one from
  the query string.
- Engine / MCP read path reject a scope that is not on an allowlist *or* not
  derived from a signed demo session. Document the exact rule in `SECURITY.md`.
- An eval with a control arm: agent A writes under scope S1; agent B's attempt
  to read or compensate under S1 with the wrong credential/token fails; S2 is
  untouched. **If the guard is removed, the eval must fail.**

Do not build multi-tenancy. Do not build a user table. Close the hole the pitch
creates.

**Check:** `SECURITY.md` no longer lists "scope is a caller-supplied string with
nothing enforcing it" under demo scaffolding without a "fixed as of …" note.
The eval is green on Cloud.

---

## Task C — Bound Bedrock spend on the read path

Overnight hardening gated write paths and left `/api/distances` ungated. Every
page load invokes the embedder. That is the residual open wallet.

- Cache the distance pairs in process (they are server-side constants; the
  vectors do not change for a given embedder). Invalidate on embedder name
  change.
- Soft rate-limit `/api/distances` per IP (stricter than write paths is fine;
  one load per visitor is the happy path).
- Confirm from Railway logs / Bedrock metrics that hammering the URL does not
  move the bill. If you cannot observe the bill, say unverified.

**Check:** 100 hard-refreshes after a cold boot produce **one** embedder batch
for the ruler, not 100. Write paths still require the token.

---

## Task D — Hostile-read pass across every surface

Fable's table from the earlier review. Fix the words, not the code, unless the
words reveal a real lie.

| Phrase | Required end-state |
|---|---|
| "durable lock" | "a lock row taken inside the commit transaction, with durable locking enabled so a lease transfer cannot drop it" — or footnoted |
| "exactly one agent decides" | "exactly one lock holder commits"; crash frees the key (no lease, no TTL, no wedge) — verified or marked unverified |
| "9 attack payloads refused" | refused **by the MCP `select_query` tool's statement validator**; lock cannot be expressed through MCP; do not overclaim "structurally impossible to write" |
| the 8-vs-1 eval | README already states same infra minus the lock — keep it explicit in the UI copy too |
| "compensation" | now closed-loop for registered tools; unknown tools stay flagged — say both |

Grep the repo (README, DEMO, SECURITY, UI copy, comments that a judge will
read). Every hit is fixed or footnoted. Do **not** rewrite `FINDINGS.md`'s
calibrated claims; only touch wording that overclaims.

**Check:** `rg -n 'durable lock|exactly one agent decides|structurally impossible|production-ready' ` returns either nothing or a footnote on the same line.

---

## Task E — Only if A–D are genuinely finished before 18:00

Pull Saturday forward so Friday is buffer, not panic:

1. **Tools-and-services statement** written as a short section ready for the
   submission form (CockroachDB: MCP + C-SPANN + serializable/durable lock +
   bitemporal/audit; AWS: Titan + Claude + the scoped IAM story).
2. **Pre-visualise the video against the deployed URL.** One full rehearsal
   recording, even if rough. If the URL hiccups, you want to know on Thursday —
   not Saturday at 19:00.
3. **Makefile or `justfile`:** one command per eval, plus `make demo` that
   refuses to start without `CRDB_URL` and `DEMO_TOKEN`. Boring; saves strangers.
4. **Dogfood prep (do not run yet):** list the structural claims you would point
   RETRACT at in the real agent fleet on Monday surplus. Names, statuses,
   decisions. Nothing from journal/finance/wallets. Having the list means Monday
   is execute, not invent.

Do not start Task E to avoid finishing Task B.

---

## What not to do

- Do not merge a PR whose Cloud `compensate_eval` you have not watched pass.
- Do not deploy without `DEMO_TOKEN` set — fail-closed will look like an outage.
- Do not add multi-tenancy, a LangGraph adapter, or a contradiction-feed UI.
  Still cut. Reasoning in `PLAN.md`.
- Do not invent a second compensation abstraction. The registry in
  `retract/compensate.py` is the product; keep it boring.
- Do not let the heuristic pass as Claude. When the form clears, flip the env
  var and the page; until then the stand-in stays labelled.
- Do not spend the morning polishing overnight code that already has a control
  arm and a Cloud-green eval. Move the scoreboard.

---

## Score order for today

| Rank | Work | Why |
|---|---|---|
| 0 | Gate 0 — Cloud-green + live reversal on public URL | Without it PR #2 is a diary entry |
| 1 | Anthropic use-case form | Unblocks the only labelled-model path to the video |
| 2 | Task A — act 5 / film ending | Creativity is scored through the video; the ending is the claim |
| 3 | Task B — scope enforcement | Production Readiness; the pitch creates the question |
| 4 | Task C — distances spend bound | Closes the residual open wallet |
| 5 | Task D — hostile-read wording | Free points; prevents 30-second sponsor deductions |
| 6 | Task E — video rehearsal + submission prose | Pulls Saturday left; only after A–D |

---

## The PR description (morning PR, or update to #2)

State plainly:

- what you built beyond overnight
- what you verified **on Cloud** and how (paste commands + outcomes)
- what is still unrun and why
- every judgement call where this brief was ambiguous
- anything you believe is wrong with *this* plan or with `PLAN.md`

The last one is welcome.

---

## Shutting down tonight's agent — known Day-1 state

Restated so the morning does not re-litigate it (from `PLAN.md`, owner's Day 1;
not re-verified by the overnight agent):

- Repo public: https://github.com/Morkeeth/retract — Apache-2.0
- Demo live: https://retract-production.up.railway.app
- Database reachable: CockroachDB Cloud Basic v26.2.5, eu-west-1
- Titan embeddings running on real Bedrock at 512 dims
- AWS credential scoped to `bedrock:InvokeModel` on two model ARNs; five
  escalation paths verified blocked

Your job at 20:00 Thursday is to add one more sentence to that list:

> On the public URL, a forged-passport retraction reverses the executed refund
> and the ledger shows `compensated` with the reversal's own id.
