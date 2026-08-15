# CODE FREEZE — 15 Aug, before the 20:00 recording

**Direct answer to the question asked: the code is good enough, it is frozen,
and it was never the risk. As of 12:32 today there is also only one version of
RETRACT — the branch was merged, pushed and deployed, and the live demo is
verified healthy on it.**

Everything below is verified against the object today, 15 Aug. Where it is not,
it says so.

---

## THE DECISION WAS TAKEN AT 12:32 — merged, pushed, deployed, verified

This section used to pose the question. It is answered. Recorded here rather
than deleted, because the reasoning is what a reader needs, not the suspense.

`origin/main` is **`7a873f2`** — the eight commits fast-forwarded onto `main`,
plus one commit carrying this file, the shoot guide and the comparison frames.
Railway redeployed. **I did not push it**; it happened while this lane was
mid-report.

**Verified after the fact, at the object, because nobody had:**

| Check | Result |
|---|---|
| Live page vs `7a873f2` | byte-identical — the new build is what serves |
| `/healthz` | 200, 0.17s |
| `race_retract` | 9.0s · 1 belief · 1 claim key · 7 contradictions |
| `story`, cold (first run post-deploy) | **completed**, 37.07s — did not hit the 60s cap |
| `story`, warm ×2 | 37.82s, 37.25s |
| Ending, rendered in Chromium | correct — `shoot/ending-NOW-LIVE-7a873f2.png` |
| `resolved` SSE beat | **present** at 27.1s — the verdict is now applied, not just printed |

**The demo is healthy on the new build. Shoot against it.**

### What actually changed on camera

| | **was live** (`0bcbaef`) | **live now** (`7a873f2`) |
|---|---|---|
| Look | dark sheet, alarm red | near-white paper, JetBrains Mono, one ramp |
| Claude's verdict | shown, then **ignored** — `retract()` ran unconditionally | applied — `resolve()` closes the contradiction under the claim lock |
| The ending | `refund_issued → COMPENSATED`, `refund_reversed → EXECUTED` | `NEEDS COMPENSATION`, `refund_reversal_requested · RECORDED · NOT DISPATCHED` |
| Story runtime, deployed | 32.0s | **37.4s** |

Both endings are in `shoot/` — `ending-OLD-0bcbaef.png` and
`ending-NOW-LIVE-7a873f2.png`. The old one is the better-looking shot: it
resolves to green. The new one has **no win state at all** — five rows and not
one says the system succeeded. That is the honest picture, it is a harder shot
to land, and the voice-over in `VIDEO-GUIDE.md` is written for it.

### A correction to this file's own earlier recommendation

The pre-push version of this document argued for pushing partly because "15
seconds of runtime come back". **That was wrong, and it was wrong in the way
that matters here.** It compared HEAD running on this laptop (17.3s) against the
old build running on Railway (32.0s) and reported the gap as a product
improvement. Two environments, one number. Measured properly, on Railway both
times: the old build ran **32.0s** and the new one runs **37.4s** — the new
build is **5.4s slower**, not 15s faster.

Nothing else in the recommendation depended on it, and the two reasons that did
the real work both held up at the object: the verdict is now genuinely applied
(`resolved` at 27.1s), and the ledger now refuses to say `compensated` without a
receipt. The push was right. The third reason was an artifact of comparing rooms
instead of builds.

The cost is real but small: 37.4s against the server's 60s cap leaves 23 seconds
of headroom instead of 28.

---

## MUST land before 20:00

**Nothing in the code.** This is the honest answer and it is the good news.

The three items are procedure, not commits:

1. **Warm-up run — this is the real risk tonight, not the code.**
   Ten attempts today: **2 of 3 cold runs failed, 6 of 6 warm runs passed.** The
   two cold failures were (a) `event: error {"error_class":"timeout"}` at the
   server's 60s cap, and (b) a browser run still unfinished at 55s with the
   effects table frozen pre-cascade and the punch line blank. Both are the
   film's ending, failing. The one cold success was on the new build, at 37.07s.
   Run the story once as a throwaway before rolling, and again after any break
   longer than ten minutes. It is a procedure, not a patch — do not change
   timeout code hours before a shoot.
2. **Shoot from `VIDEO-GUIDE.md`, not `DEMO.md`.** `DEMO.md` now describes a
   build that no longer exists: its ruler numbers (`0.531 / 0.532` against a
   live `1.074 / 1.073`), its timings, and — since 12:32 — its entire ending.
3. **Nothing else.** The push decision is closed.

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
| Live demo `GET /` | 200 · page byte-identical to `7a873f2` |
| Live `/healthz` | 200, 0.17s |
| Live `/status` | `adjudicator: bedrock:claude`, `adjudicator_is_model: true`, `database: reachable`, `mcp: configured` |
| Live `race_retract` (new build) | 9.0s · 1 belief · 1 claim key · 7 contradictions |
| Live `story` (new build) | 37.4s ±0.4 over three runs, full ending renders, `resolved` beat present |
| `experiments/reach_eval.py` (new) | **ALL PASS**, 7 checks, both arms |
| New build's ending, in Chromium | correct — `shoot/ending-NOW-LIVE-7a873f2.png` |

*`verify_live.sh` ran green **before** the deploy, on `2193cef`'s tree against
the same cluster. It has not been re-run since `7a873f2` landed. `7a873f2` adds
only docs and PNGs — no engine change — so re-running would exercise identical
paths, but that is an inference, not a run. Two minutes if you want it green
post-deploy.*

**Two caveats on that green, stated rather than buried:**

- `verify_live.sh` step 6 asserts a reversal exists with `status='compensated'`
  and a `comp:` key. It passed — on three rows whose keys are
  `rf-outbox-crash-*`, `rf-outbox-concurrent-*`, `rf-outbox-settling-*`. Those
  were written by `outbox_eval.py`, not by the demo path. The step is satisfied
  by eval-authored rows, so it does not prove the *product* path produced one.
  The live story run today did produce one; that is the evidence, not step 6.
- `experiments/rehearse.py` is stale against the new build: it looks for a
  `compensated` SSE event, which was renamed to `compensation_recorded`, so it reports
  `ACT 5 NOT MEASURED` on a run that was actually fine. Cosmetic, in a tool, not
  in the product — listed so nobody reads that line as a failure tonight.

---

## What is still uncommitted

`experiments/reach_eval.py` — the before/after measurement — is **untracked**.
The 12:32 commit took `VIDEO-GUIDE.md`, `FREEZE.md` and `shoot/`, but not the
eval. So the film puts a number card on screen at 2:05 and cites a file that is
not in the repo a judge would clone.

One line, and it is not mine to run:

```bash
cd ~/CODE/retract
git add experiments/reach_eval.py
git commit -m "The before/after the pitch was missing: same case, two arms"
git push origin main            # docs + eval only, no engine change
```

Rewriting this file and `VIDEO-GUIDE.md` to describe the deployed build has also
left the tree dirty again. Both now describe `7a873f2`.

**Rollback, if the new build reads worse under a camera:** Railway keeps the
previous deployment. Roll back in the Railway UI. Do not force-push.
