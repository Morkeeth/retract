# RETRACT — roadmap

Written 12 Aug 2026, end of day one. Submission deadline **18 Aug 2026, 23:00 CEST**.

---

## Where it stands tonight

Committed at `7180546`. Engine, schema, demo surface, six evals with control
arms, README, FINDINGS, Apache-2.0 licence. Titan embeddings live through
Bedrock. Claude adjudication wired and blocked only on a one-time console form.

**The one open decision for Oscar:** the public repo and the deploy target. Both
outward-facing, both untouched.

---

## The honest gap, before any ambition

**Gate 1 is not satisfied.** The rules require **two** CockroachDB tools used
load-bearing. RETRACT uses one — Distributed Vector Indexing. I said this was
locked earlier today and I was wrong; the Agent Skills repo counts only if it is
actually integrated, and it is not.

This is pass/fail. It outranks every item below. A brilliant submission that
misses a stated requirement scores zero.

---

## STRANGER — who is the first person this reaches who is not Oscar

**A CockroachDB engineer reading the submission.** Not a hypothetical user — a
named, reachable reader with a specific reason to care, arriving next week.

Their thesis in public all year has been that agents will overwhelm databases and
that the database has to move into the reasoning loop. RETRACT is a working
counter-example to their own blog's recommended pattern: they publish the
vector-similarity memory design, and we measured that it cannot hold identity —
on *their partner's* embedding model as well as an open one.

**The single move that gets it there:** finish the submission with `FINDINGS.md`
as the centrepiece rather than an appendix. The negative result is the thing a
Cockroach engineer would forward internally. Nobody forwards another demo.

**The stranger after that is a developer with two agents and one database.** They
arrive through the second move below, not through the hackathon.

---

## MOONSHOT

**The consistency layer for multi-agent systems — the thing you put underneath a
fleet so its agents cannot disagree with themselves.**

Today's agent-memory market optimises recall: store more, retrieve better. That
is a single-agent problem and it is nearly solved. The unsolved problem starts at
agent number two, and it is not retrieval — it is *agreement*. Two agents, one
customer, incompatible beliefs, and no mechanism that notices.

Taken as far as it goes, RETRACT becomes the layer that makes a claim about a
fleet that no vector store can make:

> Every fact your agents believe has exactly one writer at a time, a provenance
> chain to its source, and a reachable list of every side effect it caused.

Three properties nobody currently ships together: **serialised belief formation**,
**derivation-tracked provenance**, and **side-effect reachability**. The third is
the one with no competitor — every agent framework can delete a memory, none can
tell you what that memory already caused.

The end state is boring and large: a `pip install`, a connection string, and a
`memory.assert(subject, predicate, claim)` call that a platform engineer puts
under an existing fleet in an afternoon. The database does the hard part.

---

## NEXT 3 MOVES, ranked

### 1. Managed MCP Server as the agents' governed read path — **do this first**

Closes Gate 1, and it is the right architecture rather than a checkbox. Agents
read memory through Cockroach's managed MCP endpoint: read-only by default,
permission-scoped, audit-logged. Writes continue through the engine's own locked
path, because MCP's write surface cannot express the claim lock.

That split is itself the story — *"agents read through a governed endpoint they
cannot write through"* — and it lands directly on Production Readiness, a full
20% of the rubric and currently our weakest axis. It also uses the sponsor's
flagship 2026 release in the way they designed it.

Roughly a day. Non-negotiable, because the alternative is disqualification.

### 2. Ship it as a LangGraph / LangChain memory backend

Real-World Impact is another 20% and today it is a story, not a fact. Cockroach
already ships a LangChain integration; RETRACT implementing the memory interface
means a judge can point an existing agent at it without reading our code.

This is also the move that turns the stranger from "a judge" into "a developer" —
the difference between a project that wins a prize and a project that gets used.
It is the highest-leverage item that is not a gate.

### 3. The contradiction feed — make disagreement the product surface

Right now contradictions are raised and adjudicated invisibly. Expose the open
ones as a stream: *these are the facts your fleet currently disagrees about.*

That inverts the pitch. RETRACT stops being infrastructure you trust silently and
becomes a dashboard with a number on it that nobody else can produce. It is the
`0 open contradictions` badge a platform team would actually check in the morning,
and it is the shortest path from "database feature" to "thing with a user".

---

## Deliberately not doing

- **Multi-region survivability.** Correct, expensive to demo, and the drama is
  invisible — documented failover RTO is ~4.5s of nothing happening on camera.
- **Retrieval quality work.** The crowded centre. Cockroach's own blog calls
  vector-recall memory "first-generation architecture" that "breaks in production".
- **A second signature device.** The page has one — the two accent colours that
  differ by exactly as much as the embeddings do. Adding a second would bury it.
