# Related work, and what is actually ours

Written 13 Aug 2026, five days before submission, after a competitive review
turned up prior art we had not seen. Every paper below was verified directly
against the arXiv API — titles, dates and abstracts retrieved, not summarised
from search results.

We are publishing this because a reviewer who finds MemTX and sees no citation
would be right to conclude we either did not look or chose not to say. Both are
worse than the finding itself.

---

## The paper that covers most of our thesis

**MemTX: Transactional Belief Commit for Stateful Agent Memory**
[arXiv:2607.23929](https://arxiv.org/abs/2607.23929), 27 July 2026 — three weeks
before this submission.

From the abstract, verbatim:

> "LLM agents increasingly coordinate through persistent shared memory: one
> agent's write becomes another agent's premise, and eventually a tool call with
> real side effects. Current agent memory systems treat every accepted write as
> immediately actionable truth... We argue that a memory write is not a belief
> commit. We present MemTX, a transactional belief-commit protocol. Each record
> carries evidence, permissions, provenance, and validity. Writes are staged
> inside snapshot-isolated transactions and admitted by a validate-and-commit
> pipeline, irreversible tool calls are gated on in-flight belief state, and
> retracting a belief triggers typed cascading repair of its derived records and
> tool side effects."

That is our design. Both halves — write-time admission control, and retraction
that cascades to side effects. They verified two invariants across 5.5 million
protocol states with zero violations. We did not know this existed when we built
RETRACT, and it is a stronger formal treatment than ours.

**So RETRACT did not invent transactional agent memory. MemTX got there first
and proved more.**

## The rest of the neighbourhood

| Work | Date | What it covers |
|---|---|---|
| [LatticeMind](https://arxiv.org/abs/2608.08236) | 8 Aug 2026 | A conflict-aware memory primitive for multi-agent systems; contradiction handled at write time |
| [From Faulty Memories to Corrected Actions](https://arxiv.org/abs/2608.10502) | 11 Aug 2026 | Dependency-guided rollback repair. Two days before this file |
| [Robust Agent Compensation](https://arxiv.org/abs/2605.03409) | May 2026 | Compensating actions for agent frameworks |
| [Always-On Agents (survey)](https://arxiv.org/abs/2606.30306) | 29 Jun 2026 | 435-work corpus on persistent memory, state and governance |

## What the survey says the field is missing

The survey coded 435 works and concluded, verbatim:

> "the literature concentrates more heavily on accumulating and retrieving state
> than on governing, recovering, or relinquishing it."

It proposes an evaluation protocol that scores "state mutation and recovery
obligations rather than answer quality alone" — because that is not currently
measured.

**That sentence is the gap RETRACT actually occupies.**

---

## What is genuinely ours

Three things survive contact with the prior art. We claim these and nothing more.

### 1. A measured argument that identity cannot come from the embedding

MemTX assumes records with identity. It does not ask whether an embedding can
*establish* that identity. We measured it, and it cannot:

On all-MiniLM-L6-v2 a paraphrase and a flat negation of the same sentence sit
**0.531 and 0.532** apart — one thousandth, opposite meanings. On Amazon Titan
Text Embeddings V2, a tense change (`lives in Berlin` → `used to live in Berlin`,
0.344) is **nearer** than a genuine paraphrase (0.714). Same-fact and
different-fact distributions overlap on both models, so no threshold exists.

This is why RETRACT's identity comes from a canonical `(subject, predicate)` key
and never from a distance cutoff. Full method, both models, and the honest limits
in [FINDINGS.md](FINDINGS.md).

It matters beyond us: most shipping agent-memory systems deduplicate by
similarity threshold. If this measurement generalises, they are merging facts
with their own negations.

### 2. A running implementation on a distributed SQL database

MemTX is a protocol with property-based verification. RETRACT is a deployed
system on CockroachDB Cloud where every number is a live transaction, including
a second negative result: we tested whether an ANN read alone would serialise
concurrent adjacent writes — a free-lunch shortcut the vector index appears to
offer — and it does not (13% versus an 8% control, Fisher p = 0.15). That is why
the lock is explicit.

A protocol and an implementation are different artifacts. We are the second.

### 3. Measured recovery

The survey's finding is that recovery obligations are not scored. RETRACT's
retraction cascade is asserted on **blast radius**, not just on completion: the
eval checks that an unrelated customer's belief and pending effect are left
untouched, because a cascade that retracts everything fails as surely as one that
retracts nothing.

---

## What we do not claim

- **Not first.** MemTX precedes us and formalises more.
- **Not formally verified.** They machine-checked 5.5 million states. We have
  evals with control arms. Those are different levels of assurance and we will
  not blur them.
- **Not proven prevalent.** The largest empirical study of multi-agent failure we
  found (MAST, 1,600+ traces, 14 failure modes) does **not** include shared-memory
  belief conflict among its failure modes. We think the problem is real and
  growing; we cannot show it is common, and we will not pretend otherwise.
- **Not a full compensation engine.** Today RETRACT reaches an already-executed
  side effect and flags it for compensation. Executing the reversal is in
  progress; until it lands, the ledger says `needs_compensation` and nothing in
  our copy will claim more than that.

---

## Why publish this at all

A hackathon submission is not a paper and nobody required a related-work section.
We wrote one because the alternative — a judge discovering a three-week-old paper
that does what we say is novel — costs more than the admission does. And because
the honest version is still a good position: the protocol exists in the
literature, almost nobody has built it on real infrastructure, and by the
survey's own count essentially nobody measures whether the recovery works.
