# CODE FREEZE — 15 Aug, before the 20:00 recording

**Direct answer to the question asked: the code is good enough, and it is not
the risk. The risk is that two versions of RETRACT exist and only one of them
can be on camera.**

Everything below is verified against the object today, 15 Aug. Where it is not,
it says so.

---

## The one decision, and it is Oscar's

There are eight commits on `design/brand-identity` (HEAD `2193cef`) that have
never been pushed. `origin/main` is `0bcbaef`, and **`0bcbaef` is exactly what
the live URL serves** — byte-identical page, diffed today.

Those eight commits are not cosmetic. Two of them change what the film shows.

| | **LIVE now** (`0bcbaef`) | **HEAD unpushed** (`2193cef`) |
|---|---|---|
| Look | dark sheet | near-white paper, JetBrains Mono, wordmark |
| Claude's verdict | shown, then **ignored** — `eng.retract()` runs unconditionally outside the `if contradiction` branch | applied: `eng.resolve()` closes the contradiction under the same claim lock |
| Contradiction after the story | left **open** | resolved |
| The ending | `refund_issued → COMPENSATED`, `refund_reversed → EXECUTED` | `refund_issued → NEEDS COMPENSATION`, `reversal … recorded, not dispatched → PENDING` |
| Story runtime | **32.0s** (±0.3, two runs, deployed) | **17.3s** (two runs, local, same cluster) |

**The verdict row is the problem.** The shoot guide has you saying, over the
adjudication at 22.7s, that a model decides and the database only guarantees
atomicity. On the deployed build that sentence is theatre: invert Claude's
answer and nothing observable changes. A judge who asks *"what if it had said
duplicate?"* gets "nothing" from the code that is live.

**The ending is the trade.** LIVE shows the stronger punch line and the ledger
says a word — `COMPENSATED` — that no payment provider earned. HEAD refuses the
word and shows a recorded, undispatched reversal. Commit `671be37` exists to
remove that overclaim. The shoot guide's voice-over already says *"a reversal is
recorded, not the money came back"* — **on LIVE the screen contradicts the
narration; on HEAD it agrees with it.**

### Look at both endings before you rule

Rendered in a real browser today, 1440×900, against the same live cluster:

- `shoot/ending-LIVE-origin-main.png` — dark sheet, alarm-red `card_charge`,
  green `COMPENSATED`, green `refund_reversed EXECUTED`
- `shoot/ending-HEAD-unpushed.png` — paper sheet, both money rows orange
  `NEEDS COMPENSATION`, `refund_reversal_requested · RECORDED · NOT DISPATCHED`
- `shoot/fullpage-LIVE.png` and `shoot/fullpage-HEAD.png` — the whole page

**LIVE is the better-looking ending and the weaker claim.** It resolves to
green. HEAD's ending has no win state at all — five rows and not one of them
says the system succeeded. That is the honest picture and it is a harder shot to
land. Knowing that is the point of putting both files in front of you.

### My recommendation

**Merge and push before you shoot, then re-verify, then record.** Three reasons,
in order of weight: the verdict sentence becomes true; the screen stops
disagreeing with the voice-over; and 15 seconds of runtime come back inside a
3:00 limit. The brand identity is the least of it.

**I have not pushed and will not.** A push here is a merge to `main` plus a
Railway redeploy of the demo the submission points at — outward, irreversible,
and yours. The exact commands are at the bottom.

**If you decide not to push**, the film is still shootable exactly as written —
change one thing: at 22.7s, say *"a model decides"* and **do not** claim the
verdict changes the outcome. Do not describe `resolve()`. Everything else in
`VIDEO-GUIDE.md` was measured against the deployed build and holds.

**Deadline for this decision: 17:00.** A redeploy needs a health check, one
story run, and one race run before you can trust it — call it 30 minutes — and
you do not want that happening at 19:50.

---

## MUST land before 20:00

**Nothing in the code.** This is the honest answer and it is the good news.

The three items are procedure, not commits:

1. **Warm-up run — this is the real risk tonight, not the code.**
   Measured today over six attempts: **2 of 2 cold runs failed, 4 of 4 warm runs
   passed.** The two cold failures were (a) `event: error
   {"error_class":"timeout"}` at the server's 60s cap, and (b) a browser run
   still unfinished at 55s with the effects table frozen on the pre-cascade
   state and the punch line blank. Both are the film's ending, failing.
   Run the story once as a throwaway before rolling, and again after any break
   longer than ten minutes. It is a procedure, not a patch — do not change
   timeout code hours before a shoot.
2. **The ruler numbers in the script.** `DEMO.md`'s opening act names `0.531 /
   0.532`. The live endpoint returns **1.074** and **1.073**. `VIDEO-GUIDE.md`
   has the current figures; shoot from that file, not `DEMO.md`.
3. **The push decision above, by 17:00.**

## Explicitly OUT OF SCOPE now

- **Anything in `PRODUCT-V2-PLAN.md`.** Not tonight.
- **`schema_v3` migration with `APPLY_SCHEMA=1`.** `verify_live.sh` skips it and
  the `compensated_by` column already exists on the cluster. Applying a schema
  change to the demo database on shoot day buys nothing and can cost the demo.
- **Wiring a real payment provider.** `settle()` exists and no provider is
  configured. That is a *feature* of the pitch — the $0-settled row is what
  makes the other six believable.
- **A compensation handler for `card_charge`.** The red row is the honesty beat.
  Registering a handler for it would delete the best thing in the film.
- **The flipbook.** Optional, goes at 2:44 or nowhere, cannot replace any live
  demo footage. If it is not done by 20:00 the film is complete without it.
- **Anything that touches `app/main.py` after 17:00.** A change after the
  re-verify window is a change that ships unverified.

---

## What is verified green, and by what

Run today, 15 Aug, against the live CockroachDB Cloud cluster
(`CockroachDB CCL v26.2.5`):

| Check | Result |
|---|---|
| `experiments/verify_live.sh` | **10 passed · 0 failed · 1 skipped** (the skip is the deliberate `APPLY_SCHEMA` gate) |
| Live demo `GET /` | 200, 0.31s |
| Live `/status` | `adjudicator: bedrock:claude`, `adjudicator_is_model: true`, `database: reachable`, `mcp: configured` |
| Live `race_retract` | 8.1s · 1 belief · 1 claim key · 7 contradictions |
| Live `story` | 32.0s ±0.3 over two runs, full ending renders |
| `experiments/reach_eval.py` (new) | **ALL PASS**, 7 checks, both arms |
| HEAD story, local, same cluster | 17.3s over two runs, ending renders `needs_compensation` + recorded reversal |

**Two caveats on that green, stated rather than buried:**

- `verify_live.sh` step 6 asserts a reversal exists with `status='compensated'`
  and a `comp:` key. It passed — on three rows whose keys are
  `rf-outbox-crash-*`, `rf-outbox-concurrent-*`, `rf-outbox-settling-*`. Those
  were written by `outbox_eval.py`, not by the demo path. The step is satisfied
  by eval-authored rows, so it does not prove the *product* path produced one.
  The live story run today did produce one; that is the evidence, not step 6.
- The HEAD UI is verified **rendered, in Chromium, against the live cluster** —
  see `shoot/ending-HEAD-unpushed.png`. It paints the new ending correctly, so
  pushing does not blank the page. What is *not* verified is HEAD running on
  Railway: it has only ever run on this laptop. That gap is why the push
  decision has a re-verify step and a 17:00 cut-off rather than being free.
- `experiments/rehearse.py` is stale against HEAD: it looks for a `compensated`
  SSE event, which HEAD renamed to `compensation_recorded`, so it reports
  `ACT 5 NOT MEASURED` on a run that was actually fine. Cosmetic, in a tool, not
  in the product — listed so nobody reads that line as a failure tonight.

---

## The exact commands, for when you decide

Read them, do not paste them blind — they are here so the decision is not also a
research task at 19:00.

```bash
cd ~/CODE/retract
git checkout main && git merge --ff-only design/brand-identity   # 8 commits
git push origin main                                             # triggers Railway

# then, and only then, re-verify — do not skip this
sleep 90
curl -s https://retract-production.up.railway.app/status
set -a && . ./.env && set +a
./experiments/verify_live.sh
uv run python /path/to/beat_timer.py story 1     # or click through the page once
```

The `.gitignore` has one uncommitted modification. Look at it before any of the
above; it is the only dirty file in the tree.

**Rollback:** Railway keeps the previous deployment. If the redeploy is worse,
roll back in the Railway UI rather than force-pushing anything.
