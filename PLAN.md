# RETRACT — build plan

Updated end of 13 Aug 2026. Deadline **18 Aug 23:00 CEST**. Four working days
left and we are one day ahead of the plan written yesterday.

---

## Day 1 — DONE, and it went further than planned

| | |
|---|---|
| Public repo | https://github.com/Morkeeth/retract — Apache-2.0 |
| Live demo | https://retract-production.up.railway.app |
| Database | reachable, CockroachDB Cloud Basic v26.2.5, eu-west-1 |
| Embeddings | Amazon Titan Text Embeddings V2 at 512 dims, live |
| AWS credential on the host | `bedrock:InvokeModel` on two model ARNs; 5/5 escalation paths verified blocked |
| Gate 1 | satisfied — Distributed Vector Indexing **and** Managed MCP Server, both load-bearing |
| Gate 2 | satisfied — Bedrock, generating every vector the index holds |

Also cleared, none of it planned for Day 1:

- **The MCP governed read path**, with an eval that fires nine escalating write
  payloads at the read tool. All refused. That eval caught itself reporting a
  false breach first, because our own client had defused the payload before it
  reached the endpoint — the harness was testing us, not them.
- **The dead v1 design deleted.** `schema.sql` had been documenting
  `memory_bucket` as "the lock target, and the heart of the design" while the
  engine used `claim_key`. Also found `cascade.py` calling a `commit()` signature
  that no longer existed — it could not run at all, and the README was citing its
  result.
- **Three research sweeps** on competitors, practitioner evidence and the
  sponsor. They changed the positioning; see below.
- **App Runner ruled out in 90 seconds** by a kill-move probe rather than at hour
  three with a built image. `SubscriptionRequiredException` on a new account.

---

## What the research changed

**Lead with the return arc, not with concurrency.**

Across roughly twenty agent-memory products examined at source level, **none has
any concept of an action attached to a memory**. A 435-work survey found 27
exposing rollback and **none** scoring whether the rollback worked. That is the
only cell in the map where the count is genuinely zero.

Concurrency, by contrast, is occupied: seven parties reached "agreement, not
retrieval" this year, and [MemTX](https://arxiv.org/abs/2607.23929) published the
full stack on 27 July. We cite it as convergent evidence — four groups converging
in ten weeks is better proof the problem is real than any prevalence claim we
could make alone, and we need that, because the largest multi-agent failure study
(MAST, 1,600+ traces, 14 failure modes) does not list shared-belief conflict at
all.

**The findings were reordered accordingly.** Finding 1 is now the C-SPANN
conflict-detection null — unpublished, sponsor-specific, and the only result here
nobody else can produce. The embedding result moved to Finding 2 and is now a
*reproduction* citing Yadav and Frias, who reached it first.

**And it gained a sharper edge.** Against the 0.80 reuse threshold in Cockroach's
own published agent-memory post, two different customers score **0.985** on
MiniLM and **0.912** on Titan. On Titan a genuine paraphrase scores **0.745** —
*below* the cutoff. The gate is not imprecise, it is inverted: it merges different
customers and separates identical facts.

---

## Day 2 — Thu 14 Aug · The return arc lands

**Outcome:** a wrong belief reaches the money it caused, and reverses it.

- Review and merge the overnight PR. Task 1 is the compensation handler; if it
  arrives unrun, run it against the live cluster before merging anything.
- The reversal writes a new effect row with its own idempotency key derived from
  the original, so replay produces one reversal and not two. A tool with no
  registered compensation stays `needs_compensation` — that is the control.
- Merge the hardening lane: demo token, rate limits, preset scenarios, structured
  logs, `SECURITY.md`.
- **Submit the Anthropic use-case form.** One console screen, and it is the only
  thing between the video and a labelled stand-in.

**Check:** on the public URL, retract a forged-passport belief and watch a real
reversal execute and land in the ledger with its own id.

**Cut if long:** the structured logs.

## Day 3 — Fri 15 Aug · Act 5, and the honesty pass

**Outcome:** the demo ends on the reversal, and every overclaim is gone.

- Add act 5 to the demo surface: the compensation executing. The film currently
  ends on a flag; it should end on the money coming back.
- Enforce `scope`. It is a caller-supplied string with nothing checking it — any
  agent can read another tenant's memory by passing a different one. For a
  product whose pitch is *governed* shared memory this is the first question a
  Production Readiness judge asks.
- Run the hostile-read table from the earlier review across every document:
  "durable lock" is imprecise, "exactly one agent decides" is really "exactly one
  lock holder commits", "refused by which layer" needs an answer.

**Check:** grep the repo for each flagged phrase; every one is fixed or footnoted.

**Cut if long:** scope enforcement, documented as a known gap.

## Day 4 — Sat 16 Aug · The video

**Outcome:** a public sub-3-minute film, shot against the deployed URL.

Structure per `DEMO.md`, with the new ending: the 0.985-versus-0.80 threshold
defect (30s) → 8 beliefs versus 1 (45s) → the negation raised, not merged (30s) →
retraction reaching the executed refund **and reversing it** (60s) → the URL.

Never localhost in the address bar. A judge who sees `localhost:8117` has watched
a private demo.

**Cut if long:** second takes, music, any intro over five seconds.

## Day 5 — Sun 17 Aug · Stranger pass, then submit

Written tools-and-services statement. Hand the repo, URL and video to someone who
has never seen them. Re-run every eval and paste real output into the README.

**Submit by 18:00 Sunday.** Not Monday.

## Mon 18 Aug — buffer

Repair only. If everything is green, the surplus move is the dogfood run: point
RETRACT at the real agent fleet and report how many genuine disagreements it
catches. Structural facts only.

---

## Hard deadlines

- **Thu 14, 20:00** — compensation executing on the public URL
- **Fri 15, 18:00** — feature freeze
- **Sat 16, 20:00** — video uploaded
- **Sun 17, 18:00** — submitted
- **Mon 18** — repair only

---

## Still true, still cut

Multi-tenancy. A LangGraph adapter. A separate contradiction-feed UI. Multi-region
survivability. Further work on the heuristic adjudicator once Claude is live.
Reasoning for each is in the git history of this file.

## The biggest risk

Still the video, and its dependency on the URL. It cannot be parallelised,
delegated, or rushed, and it needs everything else finished. The mitigation is
structural and already in place: the URL went up on Day 1, so the film can be
shot any time from Day 4 and a complete submission exists before Monday.
