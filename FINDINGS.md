# Findings

Three results. Two are negative, one is a reproduction of a defect in a published
pattern. Each one changed the design, and each carries a control arm — a number
without one proves nothing.

The order matters. **Finding 1 is the one nobody else can produce**, because it is
a question about CockroachDB's own vector index that only gets answered by running
it. Findings 2 and 3 are measurements where other people got there first, and we
say so.

---

# Finding 1 — An ANN read does not usefully participate in conflict detection

*Unpublished as far as we can find. Sponsor-specific. This is the one to read.*

## The claim under test

C-SPANN vector index partitions are ordinary key-value rows inside CockroachDB
ranges. So a serializable transaction performing an ANN search should acquire read
spans over the touched partitions, and a concurrent insert of a *semantically near*
vector should force a `40001` retry, while a *far* insert should not.

If true, the vector index would hand you concurrency control for free. It is an
attractive claim, and exactly the kind a hackathon submission asserts without
testing.

## Method

`experiments/day1_conflict.py`. Two arms against a seeded, vector-indexed table.
**NEAR** is the treatment; **FAR** is the control. In both, session B commits inside
session A's open window — after A's ANN read, before A's write. Outcomes are counted
as abort / commit / error, and errored trials **void the run** rather than being
folded silently into a rate.

## Results

| n per arm | hold | NEAR | FAR | lift | Fisher one-sided p |
|---|---|---|---|---|---|
| 25 | 150ms | 28% | 8% | 3.5× | 0.14 |
| 120 | 400ms | **13%** | **8%** | 1.6× | **0.1495** |

**Not significant.** And the effect estimate *shrank* toward the control as power
increased — 28% → 13%, 3.5× → 1.6×. That is noise regressing to a null, not a real
effect awaiting more data.

Even granting the point estimate: **a mechanism that catches 13% of collisions is
not conflict detection.** So the conclusion is robust to whether the residual gap is
real. Correctness rests on an explicit lock row taken inside the commit transaction,
with `enable_durable_locking_for_serializable = true`, because unreplicated
`FOR UPDATE` locks are documented as best-effort and "should not be relied upon for
correctness".

**The sequence, stated plainly so it cannot be misread:** the lock was made the
primary path *before* this experiment ran, deliberately, so no result could sink the
project. The honest claim is not "this finding motivated the lock" — it is *we
tested whether the lock could be dropped in favour of the index, and it cannot.*

## Instrument

`inject_retry_errors_enabled` is available on this cluster and injects `40001` on
demand, so the client retry loop is proven by observation rather than asserted. A
control never seen to fire is a claim, not a control.

## Honest limits

Rules out a large effect — the 60%+ that would make the ANN read usable as a
guarantee. Does not rule out a small one at n=120. Single region, one index
configuration, one dimensionality. Version stability untested, which is a further
reason not to build correctness on it.

---

# Finding 2 — A published similarity threshold merges facts it should separate

*A reproduction, on the sponsor's own pattern and the co-sponsor's own model.*

## The pattern under test

Cockroach Labs' published agent-memory architecture reuses a cached prior result
when similarity crosses a configured threshold — 0.80 in their worked example
([agentic-ai-architecture-memory-control](https://www.cockroachlabs.com/blog/agentic-ai-architecture-memory-control/)).
This is the standard design; most shipping agent-memory systems do some version of
it.

## Results, measured live

Cosine similarity against that 0.80 reuse threshold:

| Pair | all-MiniLM-L6-v2 | Titan Text Embeddings V2 |
|---|---|---|
| Different customer — `4471` vs `4472` | **0.985** → reused | **0.912** → reused |
| Tense change — `lives in` vs `used to live in` | **0.956** → reused | **0.941** → reused |
| Negation — `verified` vs `FAILED verification` | **0.858** → reused | 0.504 |
| *A genuine paraphrase, for reference* | 0.859 | **0.745 → NOT reused** |

Two things to see here.

On MiniLM, a **negation scores 0.858 and a real paraphrase scores 0.859**. One
thousandth apart, opposite meanings, both above the threshold.

On Titan, the gate is **inverted**: a genuine paraphrase (0.745) falls below the
cutoff and is treated as new, while a different customer (0.912) and a reversed
tense (0.941) sail over it and are merged. Two distinct customers' identity checks
collapse into one belief.

## What this does and does not show

It shows that **at the threshold as published, on these two models, this gate merges
facts that mean different things.** It does not show that embeddings can never
separate meaning. Encoders differ, and a matched-overlap audit reports the strongest
configurations reaching AUROC 0.79–0.90 ([Frias, arXiv:2608.10216](https://arxiv.org/abs/2608.10216),
10 Aug 2026). A calibrated study finds cosine separating contradiction from
duplication at AUROC 0.59, near chance, and notes that "contradictions are often
more embedding-similar to the original than rephrased duplicates"
([Yadav, arXiv:2606.26511](https://arxiv.org/abs/2606.26511), 25 Jun 2026).

So the general question is settled in the literature and we are not claiming it.
What we add is the reproduction on a specific shipped artifact, at its specific
threshold, on a model the co-sponsor supplies.

## Honest limits — read this before quoting the numbers

- Three fact groups, five adversarial pairs. Small.
- **The pairs are not matched for lexical overlap.** Frias shows precisely this
  corpus construction can invert a verdict, and reports being caught by it twice.
  Our results point the same direction as both published studies, which is
  reassuring, but n=5 unmatched pairs is a reproduction and not a benchmark.
- A model fine-tuned for entity discrimination might separate these. We did not
  test one, and the design does not depend on the answer.

## What the design does about it

RETRACT never asks distance to establish identity. Identity comes from a canonical
`(subject, predicate)` key, normalised deterministically in `retract/claim.py`, so
`Customer 4471`, `cust 4471`, `CUSTOMER#4471` and `4471` take the same lock while
`4472` does not. Vectors do retrieval, which is what they are good at. Distance is
recorded beside a contradiction as a hint for whoever adjudicates it, never as the
decision.

That deterministic-key approach is also not ours alone: Yadav's MemStrata reaches a
"deterministic (subject, relation, object) supersession rule — with no similarity
threshold and no LLM call" from the same measurement. Convergent, and worth saying.

---

# Finding 3 — The claim key holds under concurrency

`experiments/race.py`. Eight agents assert the same fact simultaneously, phrasing it
differently *and* extracting the subject differently — `Customer 4471`, `cust 4471`,
`4471`, `CUSTOMER#4471`.

| | naive arm | RETRACT |
|---|---|---|
| Active beliefs about one fact | **8** | **1** |
| Distinct claim keys written | **8** | **1** |
| Contradictions raised | 0 | 7 |

The naive arm is **the same infrastructure minus the lock** — same cluster, same
table, same embeddings, same eight concurrent writers. It is not a strawman drawn in
CSS; it is the implementation most systems ship.

The second row is the one people miss: spelling variance alone fragments a shared
memory into eight keys before concurrency is even involved.

---

# A process note

The first run of Finding 1 reported a confident **REFUTED** that was worthless.
Every trial had died on a `25001` — psycopg opens a transaction implicitly, so an
explicit `BEGIN` is illegal — and the reporting printed voided trials as
"committed". A broken harness produced a clean-looking negative result.

The fix that mattered was not the `BEGIN`. It was making the verdict function refuse
to conclude anything when any trial is void, and computing rates over valid trials
rather than attempted ones. Every eval in `experiments/` now carries a control arm
for the same reason, and the MCP security eval was caught by the same discipline:
it reported a breach that turned out to be our own client normalising the payload
before it reached the endpoint.
