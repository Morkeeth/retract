# RETRACT — the merged endgame plan

Synthesised 12 Aug from five independent plans (Codex, Grok, Cursor, Fable, and
my own). Deadline 18 Aug 23:00 CEST.

This supersedes my first draft. Where I changed position, I say so and why.

---

## What all five agreed on (so it is settled, not clever)

1. **Deploy + public repo first.** Unanimous, 5/5. They are pass/fail gates worth
   100% of eligibility, not 20% of a criterion.
2. **The LangGraph adapter is not the top move.** Also 5/5 — including me, who had
   argued for it earlier in the day and reversed before seeing the others.
3. **Cut multi-tenancy.** Unanimous. Costs a day, moves nothing a judge sees.
4. **Never imply Claude adjudicated when the heuristic ran.** Unanimous, and it is
   the fastest way to lose Technical Implementation.

Unanimity means obvious, not differentiating. The plan below is decided by the
disagreements.

---

## Where I changed my mind

### Deploy on AWS App Runner, not Fly.io

I said Fly. **Fable's argument beats mine:** App Runner upgrades the "AWS services
used" statement from one service to two, and that statement is a scored deliverable
in a hackathon co-sponsored by AWS. Fly is marginally faster and throws that away.
Cursor and Grok independently reached App Runner for the same optics reason.

Same region as the cluster (eu-west-1), container from ECR, **IAM instance role so
there are zero AWS keys in the environment**. Fly stays the fallback if App Runner
is not green by end of Day 1 — the gate is a working URL, not a particular host.

### Hardening is not third. It is the best score-per-hour on the board.

Every plan ranked Production Readiness as the weakest or second-weakest criterion,
then ranked hardening 3rd or 4th. That is inconsistent, and I made the same mistake.

Codex scored it **9/20**. It is a full 20% of the total, it is the cheapest axis to
move, and a half-day of unglamorous work takes it to roughly 16. Nothing else on the
list converts hours to points at that rate — not the adapter, not a new surface, not
another eval.

It also has a floor nobody else stated plainly: **an unauthenticated public endpoint
holding live database credentials and a Bedrock spend path does not score zero on
Production Readiness. It scores negative.** Fable is right that it is an
anti-pattern a sponsor engineer probes in thirty seconds.

### Do not build a contradiction feed

I had it at #5, Codex at #2. **Fable's counter wins:** act 3 of the existing demo
already shows a contradiction being raised and adjudicated. A new surface costs a
day and pushes the video past three minutes. Sharpen the act that exists instead.

---

## The thing all five of us missed, and it is the best move left

**Execute one compensation, on camera.**

Fable flagged the wording — *"a flag nobody watches fire is a claim, not a control"*
— but nobody made it a plan item. Every plan treats `needs_compensation` as
finished.

It is the single most original thing in the project. Every agent framework can
delete a memory. **None can tell you what that memory already caused, and none can
undo it.** Right now we stop one step short: we identify the executed refund and
flag it. We do not reverse it.

Closing that loop is roughly two hours — a compensation handler per tool type, an
idempotency key on the reversal so it cannot double-fire, and the ledger showing
`refund_issued → needs_compensation → compensated` with the reversal's own id.

It converts the strongest claim in the submission from *"we can find the damage"*
to *"we undo it, transactionally, and here is the receipt."* That is the sentence
the video ends on.

---

## The hostile-read pass — Fable's list, which is the highest-value critique received

Fix the words, not the code. Each of these is a sponsor engineer's 30-second probe.

| Claim we make | The problem | The fix |
|---|---|---|
| "durable lock" | CockroachDB locks are released at transaction end. A Cockroach engineer will read this as a claim about lock lifetime that we do not make. | Say **"a lock row taken inside the commit transaction, with durable locking enabled so a lease transfer cannot drop it"**. Precise and checkable. |
| "exactly one agent decides" | What if the holder crashes mid-hold? | Verify and then state it: the lock is held only inside a short transaction, so a crash aborts it and the key frees immediately. **No lease, no TTL, no wedge.** That is a feature — write it down. |
| "9 attack payloads refused" | Refused *by which layer*? | Be exact: the endpoint's `select_query` tool validates the statement and rejects non-SELECT. MCP does expose `create_table` / `insert_rows`, so **"structurally impossible to write"** is too strong — the true claim is that the lock cannot be expressed through MCP, so writes never route there. |
| the 8-vs-1 eval | Reads as a strawman unless the naive arm is identical infra minus the lock. | It is — same cluster, same table, same embeddings, no claim key. **State that explicitly in the README.** |
| "compensation" | Implies closed-loop sagas that do not exist. | Either build it (see above) or say "flagged for compensation; the handler is out of scope". Do not leave it ambiguous. |

---

## Day by day

Each day: one outcome, one observable check, one named cut.

### Day 1 — Wed 13 · The submission becomes hittable

**Outcome:** public repo, deployed URL, and a repo whose docs describe the code.

- Delete `retract/lsh.py`, `experiments/probe_lsh.py`, the `memory_bucket` table and
  its section in `schema.sql`. It is currently documented as *"the lock target, and
  the heart of the design"* and the engine never touches it. Fix `cascade.py`'s
  stale 384-dim import. Re-run all evals.
- **Scope the AWS key down before it goes anywhere near a public host.** It carries
  `AdministratorAccess` today. App Runner gets an instance role with
  `bedrock:InvokeModel` on the two model ARNs and nothing else.
- Separate CockroachDB demo database and least-privilege SQL user. No DDL, no admin.
- Deploy. Public repo with the Apache-2.0 licence visible in the About panel.
- Submit the Anthropic use-case form once, then stop thinking about it.

**Check:** incognito, on cellular, on a phone. All four acts complete against live
transactions. Fresh `git clone` follows the README to a running local instance.

**Cut if long:** nothing. This day is the gate.

### Day 2 — Thu 14 · The demo stops being an open wallet

**Outcome:** Production Readiness moves from its weakest score to a defensible one.

- Shared demo token or Cloudflare Access in front of any write path.
- Per-IP rate limits on THINK/COMMIT. Request-size cap. Per-request timeout.
- **Preset scenarios only** (Codex): three or four server-side scenario IDs, no
  arbitrary user text reaching an embedding or a model call. Kills prompt injection
  into an expensive path and bounds spend by construction.
- AWS Budgets alarm with a kill threshold; max-token caps on every invoke.
- `/healthz` and a non-sensitive `/status` showing database, adjudication mode, and
  build SHA (Codex).
- Structured logs: request id, claim id, adjudication mode, lock outcome, cascade
  count, error class. **Never** connection strings or raw prompts.
- A `SECURITY.md` naming the blast radius honestly: what is proven (MCP writes
  refused, serializable commit, compensation ledger) and what is demo scaffolding.

**Check:** ungated write fails; gated four-act demo still works; a burst of 100
commits returns 429; hammering the URL does not move the Bedrock bill past the cap.

**Cut if long:** the observability panel. Stdout JSON logs plus a README section is
enough.

### Day 3 — Fri 15 · Close the compensation loop, then the honesty pass

**Outcome:** the most original claim in the project becomes a demonstrated control,
and every overclaim is removed from the copy.

- **Execute one compensation.** `refund_issued → needs_compensation → compensated`,
  with the reversal carrying its own idempotency key, visible in the effect ledger
  on the deployed URL.
- Run the hostile-read table above across README, FINDINGS, DEMO and the UI copy.
- Adjudicator honesty lock: Claude live, or the UI and every document say
  "heuristic stand-in; Claude adapter wired, pending Amazon use-case approval."
  Never a silent substitute.

**Check:** on the public URL, retract a forged-passport belief and watch a real
reversal execute and land in the ledger. Grep the repo for every phrase in the
hostile-read table; each one is either fixed or footnoted.

**Cut if long:** the dogfood run below moves to Day 4's surplus.

### Day 4 — Sat 16 · The video, shot against the deployed URL

**Outcome:** a complete, public, under-three-minute video that a cold viewer
understands.

Structure, from `DEMO.md`: the 0.531/0.532 finding (30s) → 8 versus 1 (45s) →
retraction reaching the executed refund **and reversing it** (60s) → MCP refusing a
write (20s) → the URL (15s).

Shot against the deployed URL, never localhost. Grok, Cursor and Fable all
independently insisted on this and they are right: a judge who sees `localhost:8117`
in the address bar has watched a private demo.

**Check:** plays without login, under 3:00, and someone who has never heard of this
can say what it does afterwards.

**Cut if long:** second takes, music, B-roll, any brand intro over five seconds.
Audio clarity beats production value.

### Day 5 — Sun 17 · Stranger pass, then submit

**Outcome:** submitted, complete, a full day early.

- Written CockroachDB tools + AWS services statement.
- `/stranger`: hand the repo, URL and video to someone who has never seen them.
- Re-run every eval; paste real output into the README.
- **Submit by 18:00 Sunday.** Not Monday.

**Check:** a submission confirmation exists while a day of buffer remains.

**Cut if long:** every fix below the line ships as-is.

### Day 6 — Mon 18 · Buffer, and the surplus move

Only repair demonstrated failures. If — and only if — everything above is green:

**The dogfood run.** Point RETRACT at Oscar's actual agent fleet: several Claude
sessions writing structural claims about shared project state, which genuinely
disagree. *"We ran it against our own agent fleet and it caught N real
disagreements"* is a fact where every competitor has a story. Structural facts only
— project names, statuses, decisions. Nothing from journal, finance or wallets.

No other plan proposed this, and none argued against it, because none saw it. It is
the highest-ceiling item left and the least certain, which is exactly why it belongs
in surplus rather than on the critical path.

---

## Score per hour, final ranking

| Rank | Work | Why |
|---|---|---|
| 1 | Public repo + deployed URL | Pass/fail. Without it every other number is an anecdote |
| 2 | Delete the dead v1 code | One hour; removes a wound that taints every other claim |
| 3 | Harden the demo | Cheapest 20% on the board: ~9/20 → ~16/20 in half a day |
| 4 | Execute one compensation | Converts the most original claim from a flag to a control |
| 5 | Hostile-read wording pass | Free. Prevents the specific deductions a sponsor engineer makes |
| 6 | Video against the deployed URL | Gate, and the only channel Creativity is scored through |
| 7 | Dogfood on the real fleet | Highest ceiling, lowest certainty. Surplus only |
| 8 | LangGraph adapter | Real engineering, weak judging leverage. After submit, or never |
| 9 | Contradiction feed | Act 3 already shows it. Cut |
| 10 | Multi-tenancy | Unanimous cut |

---

## Hard internal deadlines

- **Wed 13, 20:00** — public URL responds, repo public.
- **Fri 15, 18:00** — feature freeze. Nothing new after this.
- **Sat 16, 20:00** — video recorded and uploaded.
- **Sun 17, 18:00** — submitted.
- **Mon 18** — repair only.

---

## The biggest risk

Not the build. **The video, and its dependency on the URL.**

It cannot be parallelised, cannot be delegated, needs everything else finished, and
is what every team leaves to the final night — which is exactly when the demo
breaks, the cluster throttles, or the recording fails.

Mitigation is structural and already in the plan: deploy on Day 1, shoot against the
deployed URL on Day 4, and have a complete submission by Sunday evening so Monday is
upgrade time and never rescue time.
