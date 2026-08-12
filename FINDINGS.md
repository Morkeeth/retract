# Findings

Two negative results, both measured, both load-bearing for the design. They are
here rather than buried because each one killed an approach we had already built,
and because a submission that only reports what worked is not reporting.

---

# Finding 1 — Embedding distance cannot tell a rephrasing from a contradiction

**This is the finding the whole product is built around.** It reproduces across
two independent, production-grade embedding models.

## The claim under test

The obvious way to deduplicate an agent's memory is cosine or L2 distance: if a
new claim is close enough to one you already hold, it is the same fact. Almost
every agent-memory system ships some version of this.

## Method

`experiments/probe_real_geometry.py`. Three groups of paraphrases (the same fact
said 4-5 different ways) measured against each other, and against **adversarial
pairs** — near-identical wording, genuinely different fact. The adversarial set
is the point: a threshold that survives ordinary comparisons but merges
"verified" with "FAILED verification" is worse than no deduplication at all.

## Results

| | all-MiniLM-L6-v2 (384d) | **Titan Text Embeddings V2 (512d)** |
|---|---|---|
| Same fact, reworded | 0.323 – **0.843** | 0.237 – **0.919** |
| Different fact, similar words | **0.172** – 0.573 | **0.344** – 0.996 |
| Genuinely unrelated facts | 0.916+ | 1.039+ |

**The same-fact and different-fact ranges overlap on both models.** No cut point
exists on either axis.

The individual pairs are worse than the ranges suggest:

| Pair | MiniLM | Titan |
|---|---|---|
| `4471 verified` vs `4472 verified` — *different customer* | **0.172** | 0.419 |
| `lives in Berlin` vs `used to live in Berlin` — *tense* | 0.296 | **0.344** |
| `$1,240 approved` vs `$2,140 approved` — *digits swapped* | 0.317 | 0.540 |
| a genuine paraphrase, for comparison | 0.531 | 0.714 |

On MiniLM the sharpest case is a single character apart in meaning and
**0.001 apart in distance**: a paraphrase measures 0.531, a flat negation
measures 0.532. On Titan, a *tense change* (0.344) sits at less than half the
distance of a *true paraphrase* (0.714) — the different fact is nearer than the
same one.

## Why it holds

An embedding model encodes topic and register. "Customer 4471 verified" and
"Customer 4472 verified" are about the same subject matter, in the same voice,
differing by one digit that carries the entire meaning. The model has no reason
to separate them and every reason not to.

## What we did about it

RETRACT never asks distance to establish identity. Identity comes from a
canonical `(subject, predicate)` key, extracted at think time and normalised
deterministically (`retract/claim.py`) — so `Customer 4471`, `cust 4471`,
`CUSTOMER#4471` and `4471` all take the same lock, while `4472` does not.

Vectors keep the job they are good at: retrieval in the READ phase, through
CockroachDB's distributed vector index.

When two agents assert claims on the same key, the second is raised as a
**contradiction** and adjudicated by a model. Distance is recorded beside it as
a hint for the adjudicator and never as a decision.

## Honest limits

- Three fact groups, five adversarial pairs, two models. Small.
- The direction is unambiguous and consistent across both models, but the exact
  thresholds are not a benchmark and should not be quoted as one.
- A model fine-tuned for entity discrimination might separate these. We did not
  test one, and the design does not depend on the answer.

---

# Finding 2 — An ANN read does not usefully participate in conflict detection

## The claim under test

C-SPANN vector index partitions are ordinary key-value rows inside CockroachDB
ranges. So a serializable transaction performing an ANN search should acquire
read spans over the touched partitions, and a concurrent insert of a
*semantically near* vector should force a `40001` retry, while a *far* insert
should not.

If true, the vector index would hand us concurrency control for free. It is an
attractive claim, and exactly the kind a hackathon submission asserts without
testing.

## Method

`experiments/day1_conflict.py`. Two arms against a seeded, vector-indexed table.
**NEAR** is the treatment; **FAR** is the control. In both, session B commits
inside session A's open window — after A's ANN read, before A's write. Outcomes
are counted as abort / commit / error, and errored trials void the run rather
than being silently folded into a rate.

## Results

| n per arm | hold | NEAR | FAR | lift | Fisher one-sided p |
|---|---|---|---|---|---|
| 25 | 150ms | 28% | 8% | 3.5× | 0.14 |
| 120 | 400ms | **13%** | **8%** | 1.6× | **0.1495** |

**Not significant.** And the effect estimate *shrank* toward the control as power
increased — 28% → 13%, 3.5× → 1.6×. That is noise regressing to a null, not a
real effect awaiting more data.

## Why the design does not depend on the statistics

Even granting the point estimate: **a mechanism that catches 13% of collisions is
not conflict detection.** RETRACT needs a guarantee and 13% is not one. So the
conclusion is robust to whether the residual gap is real.

Correctness rests on an explicit durable lock over the claim key, with
`enable_durable_locking_for_serializable = true` — because unreplicated
`FOR UPDATE` locks are documented as best-effort and explicitly "should not be
relied upon for correctness".

This is why the fallback was made the primary path *before* the experiment ran.
Had the headline rested on the vector index, this result would have cost the
project a day. Instead it cost nothing and produced a finding.

## Instrument

`inject_retry_errors_enabled` is available on this cluster and injects `40001` on
demand, so the client retry loop is proven by observation rather than asserted.
A control never seen to fire is a claim, not a control.

## Honest limits

- Rules out a large effect (the 60%+ that would make the ANN read usable as a
  guarantee). Does not rule out a small one at n=120.
- Single region, one index configuration, one dimensionality.
- Version stability untested — a further reason not to build correctness on it.

---

# A process note

The first run of Finding 2 reported a confident **REFUTED** that was worthless:
every trial had died on a `25001` (psycopg opens a transaction implicitly, so an
explicit `BEGIN` is illegal) and the reporting printed voided trials as
"committed". A broken harness produced a clean-looking negative result.

The fix that mattered was not the `BEGIN`. It was making the verdict function
refuse to conclude anything when any trial is void, and computing rates over
valid trials rather than attempted ones. Every eval in `experiments/` now carries
a control arm for the same reason.
