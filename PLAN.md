# RETRACT — endgame plan

My independent answer to the same six questions posed to the other models.
Written 12 Aug, deadline 18 Aug 23:00 CEST. ~5.5 working days.

---

## 1. Where this is weakest

Scored honestly against the five criteria, 20% each.

| Criterion | Estimate | Why |
|---|---|---|
| Agentic Memory Design | **strong** | claim key, bitemporal rows, derivation DAG, effect ledger, contradiction table |
| Technical Implementation | **strong, with a wound** | measured negatives, durable locking, 9 refused attack payloads — but see the dead code below |
| **Real-World Impact** | **weakest** | no user. The scenario is invented. Customer 4471 does not exist |
| **Production Readiness** | **second weakest** | no deployment at all, no auth, `scope` is an unenforced string, no metrics |
| Creativity & Originality | **strong** | a negative result as the centrepiece; the palette device |

### The wound, and it is self-inflicted

`schema.sql` still documents `memory_bucket` as *"the lock target, and the heart of
the design"*. It is not. `claim_key` is. The engine never touches `memory_bucket`,
the table is still live on the cluster, `retract/lsh.py` is imported by nothing in
the correctness path, and it declares `DIM = 384` while the embedder now runs at
512 — which `experiments/cascade.py` still imports.

A judge who reads the schema finds a table described as the heart of a design the
code abandoned. That does more damage than any missing feature: it makes every
other claim in the README suspect. **Delete it on day 1, before anything else.**

### The multi-tenancy hole nobody has looked at

`scope` is a string passed by the caller. Nothing enforces it. Any agent can read
or write any other tenant's memory by passing a different string. For a product
whose entire pitch is *governed* shared memory, that is the question a Production
Readiness judge asks first, and we currently have no answer.

---

## 2. Day by day

Each day has one outcome, one observable check, and a named cut.

### Day 1 (13 Aug) — DEPLOY, and delete the lie

**Outcome:** a public URL a stranger can press buttons on, and a repo whose docs
describe the code that exists.

Deploy first, not last. It is the only hard deliverable still unmet, it is the one
that cannot be faked at 22:00 on the 18th, and every team that leaves it to the end
loses a day to it. Everything after this is upside; this is survival.

- Delete `retract/lsh.py`, `experiments/probe_lsh.py`, the `memory_bucket` table and
  its section in `schema.sql`. Fix `cascade.py`'s import. Re-run all evals.
- Deploy the FastAPI app. Fly.io or Railway — both take a Dockerfile and a secret,
  both give a URL in minutes. Not Lambda: the app holds a warm embedder and a
  connection pool, and cold starts would make the demo feel broken.
- Put the repo public with the Apache-2.0 licence visible in the About section.

**Check:** open the URL on a phone, on cellular, logged out. Press both buttons.
Both complete. *(This is the `/stranger` test: I cannot see my own first run.)*

**Cut if long:** the repo can go public on day 2. The URL cannot.

### Day 2 (14 Aug) — REAL DATA. The impact fix.

**Outcome:** RETRACT catches contradictions between agents that actually exist.

This is the move I would defend hardest, and it is *not* the LangGraph adapter —
see section 3.

Oscar runs a fleet: multiple Claude sessions writing about shared projects, which
genuinely disagree with each other. Point RETRACT at it. Each session asserts claims
about project state (`project:retract · gate_1_status`, `project:favour · deploy_state`)
and RETRACT adjudicates the collisions.

Structural facts only — project names, statuses, decisions. No journal, no finance,
no wallet data, per the standing boundary.

**Check:** a number that was not invented. *"Pointed at our own agent fleet for one
night: N contradictions caught, M were real disagreements."* If N is zero, say so —
a null result here is still a real measurement and still beats a fictional customer.

**Cut if long:** run it on the transcript archive rather than live.

### Day 3 (15 Aug) — PRODUCTION READINESS, then shoot a complete rough video

**Outcome:** the second-weakest criterion answered, and a submittable video existing
three days early.

- Enforce `scope`. A tenant token, checked on every engine call, so a caller cannot
  read a scope it was not issued. This is the answer to the question above.
- Auth on the demo, even a shared token, so the deployed URL is not an open write
  endpoint to a live database.
- Emit metrics the audit log already implies: contradictions raised, adjudication
  latency, retry counts. `show_running_queries` through MCP is a free observability
  panel we already have access to.
- **Then shoot the whole video, rough, with whatever exists.**

**Check:** a video file exists that could be submitted today without embarrassment.

**Cut if long:** metrics. Never the video.

### Day 4 (16 Aug) — THE CONTRADICTION FEED

**Outcome:** disagreement becomes the product surface, not an implementation detail.

Open contradictions as a live stream: *these are the facts your fleet currently
disagrees about.* It inverts the pitch from silent infrastructure to a dashboard
with a number nobody else can produce — and by day 4 that number is populated by
real fleet data from day 2 rather than a scripted demo.

**Check:** the feed shows a contradiction that came from a real agent, not a fixture.

**Cut if long:** all of it. This is the first genuinely optional day.

### Day 5 (17 Aug) — RESHOOT AND WRITE

Final video with Claude adjudication live. Devpost copy. Architecture diagram.
Re-run every eval and paste real output into the README.

**Check:** a stranger who has never seen the repo can clone, run, and reach the
same numbers.

### Day 6 (18 Aug, to 23:00) — SUBMIT BY 18:00

Five hours of buffer, deliberately unallocated. Submit early. The deadline is the
one thing on this list that does not negotiate.

---

## 3. Score per hour — and where I now disagree with myself

Earlier today I said the LangGraph adapter was the top non-gate item. **I think that
was wrong**, and the other models will probably say the same thing I did, so this is
where an independent answer earns its keep.

| Rank | Work | Why |
|---|---|---|
| 1 | Deploy | pass/fail. A missing demo URL is an incomplete submission, not a weak one |
| 2 | Delete the dead v1 code | costs an hour, removes a credibility wound that taints everything |
| 3 | Real fleet data | converts the weakest 20% from fiction to fact |
| 4 | Scope enforcement + auth | the first question a Production Readiness judge asks |
| 5 | Contradiction feed | the strongest *product* move, but only after 3 makes it real |
| 6 | LangGraph adapter | good, and beaten by 3 |

**Why the adapter loses to dogfooding.** An adapter is *evidence that someone could*
use this. Real fleet data is *evidence that someone did*. The judging criterion says
"how big of an impact could the project have on real users or workflows" — a judge
reading "we pointed it at our own agent fleet and it caught N real disagreements"
gets a fact. A judge reading "implements the LangGraph memory interface" gets an
integration they will not run. And the adapter costs a day; the dogfood costs half
of one, because the fleet already exists.

The honest counter-argument: an adapter is *reusable* and dogfooding is *anecdote*.
If day 2 finishes early, build the adapter too — but not first.

---

## 4. The deploy decision

FastAPI, holds a warm embedding model, a psycopg connection to CockroachDB Cloud,
and calls Bedrock. It is a stateful long-running process, not a function.

**Fly.io.** Dockerfile, `fly secrets set`, a URL in under an hour, and a persistent
machine that keeps the embedder warm. Railway is the equivalent second choice.
**Not Lambda** — the ~8s cold start on the embedder would make a judge's first click
feel like a broken page, and first impressions are the entire game in a 3-minute
review.

**The security implications, named plainly, because the deployed thing holds live
credentials and anyone can hit it:**

- The demo writes to a real cluster. Every visitor's run inserts rows. Mitigate with
  a per-visit scope and a row-level TTL so the table self-cleans, plus a rate limit.
- Bedrock calls cost money and the endpoint is public. Cap it: a request budget per
  IP per hour, and a hard daily ceiling that degrades to the local model rather than
  spending without bound.
- `CRDB_URL` and the AWS keys go in the platform's secret store, never the image.
- The AWS key currently carries `AdministratorAccess`. **Scope it down before deploy**
  to Bedrock-invoke only. A public endpoint holding an admin key is the single worst
  thing in this plan if left as is.
- Delete the IAM user after 18 Aug.

---

## 5. What I would cut

- **`lsh.py`, `probe_lsh.py`, `memory_bucket`.** Not deprioritised — deleted. They
  describe a design the code abandoned. Cost of keeping: every other claim looks
  less reliable.
- **The `AS OF SYSTEM TIME` fast path.** Vestigial. The audit substrate is explicit
  rows and the 4-hour GC window makes time travel a footnote. Keeping it invites a
  question we gain nothing by answering.
- **The Agent Skills repo integration.** Both gates are met. It would be a third
  tool for its own sake.
- **Multi-region anything.** Correct, expensive, and invisible on camera — documented
  failover is ~4.5s of nothing happening.
- **Further work on the heuristic adjudicator.** Once Claude is live it is a fallback,
  not a feature. Freeze it.

---

## 6. The biggest risk, and the mitigation

**Not the build. The video.**

It is the only deliverable that needs a contiguous uninterrupted block, cannot be
parallelised, cannot be delegated, and depends on everything else being finished
first. It is also the one every team leaves until the last night, which is exactly
why the last night is when the demo breaks.

**Mitigation: shoot a complete, submittable rough cut on day 3**, with the heuristic
adjudicator if Claude is still gated. From that moment a valid submission exists and
every further day is optional improvement rather than a race.

**Second risk:** the Anthropic use-case form is the only thing between the video and
a labelled stand-in appearing in the final take. It is a one-screen console form and
it is not mine to fill. If it is not done by day 3, shoot with the stand-in and
reshoot only the 30 seconds that show the verdict box.
