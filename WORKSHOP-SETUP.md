# RETRACT — submission workshop

**Type `/grilling` and say "run the RETRACT workshop". This file is the design tree it works.**

Rules: one round at a time. Every question has a recommended answer underneath it. **A single word resolves each one.** Say "no" and I have the counter ready — some of these I expect you to reject.

---

## Facts, not questions. Verified at 15 Aug, this tick.

- **Demo live and healthy** — `GET /` 200, `/status` reports `bedrock:claude`, `adjudicator_is_model: true`, database reachable, MCP configured. `main` = `origin/main` = `7a873f2`.
- **`verify_live.sh` 10 passed / 0 failed / 1 skipped** (the skip is a deliberate migration gate).
- **Cold start still bites.** 2 of 3 first-runs-on-a-cold-container failed. One throwaway story run before you roll. Not negotiable, not fixable tonight.
- **`experiments/reach_eval.py` is untracked and the film cites it at 2:05.** One command, listed at the end.

## The design tree

**The claim gates everything.** What you assert decides what a hostile judge attacks, what survives the cut, and what the sealed prediction predicts. So it is round 1, alone with one independent item that does not wait on it.

```
Q1  What is the claim?  ──┬── what a hostile judge attacks first
                          ├── the 2:40 cut and second zero
                          └── the sealed prediction
Q2  The stale Devpost paragraph  (independent — does not wait on Q1)
```

Rounds 2 and 3 get written after you answer, because their questions change shape depending on Q1.

---

# ROUND 1

## ❓ Q1 — Is the claim the PROBLEM or the MECHANISM?

These pitch differently and a judge repeats one of them to another judge.

**A · The problem.** *"An assistant read a passport, called it genuine, approved a $1,240 refund and sent the money. The passport was forged. Deleting the note does not bring the money back — and nothing connects the note to the payment. The system has no idea the refund was ever its idea."*

**B · The mechanism.** *"Shared memory for agent fleets. Exactly one agent commits a given fact at a time, and when a belief turns out to be wrong it takes back everything built on it — including the side effects that already executed."*

**The evidence that they are genuinely different, not two phrasings:**

- **A is falsifiable by a judge's intuition and B is not.** A judge who has never run an agent fleet can decide whether A is a real problem. Only someone who has can judge B.
- **B is what four other groups also built.** MemTX, LatticeMind and Dependency-Guided Rollback Repair all reached the same mechanism within ten weeks. **Leading with B puts you in a crowded field in a month.** Leading with A puts the mechanism in as your answer to a problem you stated first.
- **A is the better film.** The cut opens on a fact about embeddings and ends on a table where the money did not come back. That is A's shape.
- **B is what the sponsors' gates ask for.** The CockroachDB and AWS requirements are mechanism questions.

➡️ **Recommended: A, with B as the second sentence.** State the problem, then say the mechanism is your answer to it. It costs nothing — the mechanism still gets named on screen for the gates — and it stops the submission being read as the fourth paper this summer with the same architecture.

**One word: A, B, or "both".**

---

## ❓ Q2 — Approve the Devpost fix?

`SUBMISSION.md` says the reversal row carries **`status='executed'`** and then spends four paragraphs explaining why that is ledger lifecycle rather than settlement.

**The build deployed today never writes `executed` on a reversal.** Commit `671be37` changed it: the reversal is a **request** (`refund_reversal_requested`, pending, rendered `RECORDED · NOT DISPATCHED`) and the original stays `needs_compensation`.

**Why this is not cosmetic:** that paragraph explicitly invites a judge to query the cluster and check. They will not find what it describes. **It is the one place the answers promised to be checkable and currently are not.**

Replacement, already drafted in full at `~/Downloads/RETRACT-SUBMISSION-2026-08-15/04-repo-and-links/DEVPOST-ANSWERS-FIXES-NEEDED.md`:

> Every belief, contradiction, effect and reversal is a durable row in CockroachDB Cloud, written in a serializable transaction, with the reversal carrying its own idempotency key derived as `comp:<original>`. **The ledger will not print the word `compensated` without a provider receipt.** The original stays `needs_compensation` and the reversal stays a recorded request. There is no HTTP client, no SDK and no provider credential in the repository. Until an identifier arrives that this process did not generate, nothing here says the money moved.

➡️ **Recommended: approve as drafted.** The new behaviour is the stronger version of the same argument — the ledger now enforces the honesty the old paragraph had to promise in prose.

**One word: yes, or what to change.**

---

# WHAT ROUND 2 WILL ASK — so you can see where this goes

Written now, asked after Q1, because Q1 changes their shape.

**Your five stated limits. Which do you say on camera, and in what order?**
1. `$0` settles — no payment provider, no HTTP client, no credential in the repo
2. `card_charge` stays red — $89, no registered handler, reached but not reversible
3. The database does not guarantee the verdict is right — the model scores **7 of 8**, not 8
4. Scope is not authentication
5. The before/after is n=1, architectural not statistical

**And the harder half: what does a hostile judge find next?** The 14 Aug hostile pass found two P0s — the verdict displayed but never applied, and money that never moved. **Both are closed.** So the question is what the third one is, and my candidates are ready.

**Round 3 is the cut and the sealed prediction**, written last because the prediction has to be made against the artifact that actually exists.

---

## The one command, whenever you want it

`experiments/reach_eval.py` is the number card at 2:05 and a judge cloning the repo does not get it.

```bash
cd ~/CODE/retract
git add experiments/reach_eval.py
git commit -m "The before/after the pitch was missing: same case, two arms"
git push origin main
```

*(`FREEZE.md` and `VIDEO-GUIDE.md` are also modified in the tree — they were rewritten to describe the deployed build. Same commit or separate, your call.)*
