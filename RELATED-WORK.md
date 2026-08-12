# Convergent work

RETRACT was designed and built from a measurement: that embedding distance cannot
tell a rephrasing from a contradiction. Everything else followed from that — the
deterministic claim key, the write-time adjudication, the derivation graph, the
effect ledger.

After it was built, a competitive review turned up something worth reporting.

## Two teams, one month, the same conclusion

**MemTX: Transactional Belief Commit for Stateful Agent Memory**
([arXiv:2607.23929](https://arxiv.org/abs/2607.23929), 27 July 2026) argues, from
formal methods rather than from a database:

> "a memory write is not a belief commit... irreversible tool calls are gated on
> in-flight belief state, and retracting a belief triggers typed cascading repair
> of its derived records and tool side effects."

That is RETRACT's design, reached independently, in the same month, by people who
verified it across 5.5 million protocol states rather than by people who ran it
against a distributed cluster.

They are not alone. [LatticeMind](https://arxiv.org/abs/2608.08236) (8 Aug 2026)
makes contradiction a write-time concern. [Dependency-Guided Rollback
Repair](https://arxiv.org/abs/2608.10502) (11 Aug 2026) argues that removing a
faulty memory is not the same as recovering the state it produced.

**This is the useful part.** The largest empirical study of multi-agent failure we
found catalogues fourteen failure modes and does not include shared-belief
conflict among them. So the honest question about this problem has never been
whether it is hard — it is whether anyone actually has it.

Four independent groups arriving at the same protocol inside ten weeks is a better
answer to that question than any prevalence claim we could make on our own. The
problem is real, several people have now found it, and the field is converging on
the shape of the fix.

## Where the field agrees the work is not done

A 435-work survey of persistent memory and state in LLM agents
([arXiv:2606.30306](https://arxiv.org/abs/2606.30306), 29 June 2026) concluded:

> "the literature concentrates more heavily on accumulating and retrieving state
> than on governing, recovering, or relinquishing it."

It proposes scoring "state mutation and recovery obligations rather than answer
quality alone", because nobody currently does.

That is the sentence RETRACT is built against.

## What RETRACT contributes

**The measurement.** Every system above assumes records have identity. None asks
whether an embedding can establish it. We tested that and it cannot: on
all-MiniLM-L6-v2 a paraphrase and a flat negation of the same sentence sit 0.531
and 0.532 apart. On Amazon Titan Text Embeddings V2, a tense change is *nearer*
than a genuine paraphrase. The distributions overlap on both models, so no
threshold exists — which matters well beyond us, because most shipping
agent-memory systems deduplicate by exactly such a threshold. Method and limits in
[FINDINGS.md](FINDINGS.md).

**The implementation.** A protocol and a running system are different artifacts.
RETRACT is the second: a deployed application on CockroachDB Cloud where every
number on the page is a live transaction, including a second negative result —
an ANN read does *not* serialise concurrent adjacent writes (13% versus an 8%
control, Fisher p = 0.15), which is why the lock is explicit rather than inherited
from the index.

**Measured recovery.** The cascade is asserted on blast radius, not completion: an
unrelated customer's belief and pending effect must be untouched, because a
cascade that retracts everything fails as surely as one that retracts nothing.
By the survey's own count, recovery is the obligation the field does not score.

## Honest limits

- Evals with control arms are not machine-checked invariants. MemTX's assurance
  level is higher than ours and we will not blur the two.
- We cannot show this problem is common. We can show four groups independently
  decided it was worth solving.
- RETRACT currently reaches an already-executed side effect and flags it for
  compensation. Executing the reversal is in progress; until it lands, the ledger
  says `needs_compensation` and nothing here claims more.
