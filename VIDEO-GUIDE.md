# RETRACT — the shoot guide

**For the 20:00 recording, Fri 15 Aug. Devpost closes Tue 18 Aug 17:00 EDT.**

This is the operating document for one evening. It is written against
CockroachDB's own judging prompts, not against instinct, and every timing in it
was measured against the deployed URL today (15 Aug), not estimated. Where a
number is not measured it says so.

**The eight commits were merged and pushed at 12:32 today.** `origin/main` is
`7a873f2`, Railway has redeployed, and the live URL now serves it — verified:
page byte-identical to `7a873f2`, `/healthz` 200, race and story both run clean.
Every timing and every table below describes **that** build.

`DEMO.md` is the older shot script and is now written against a build that no
longer exists — including its ending. **Do not shoot from it.** See
[What DEMO.md gets wrong now](#what-demomd-gets-wrong-now).

---

## The judging prompts, and where each one is satisfied

| The prompt | Where this film answers it |
|---|---|
| Show, don't tell. Live demo inside the first 20–30s | Live URL on screen at **0:09**, first click at **0:22** |
| Name the AWS services and CockroachDB features **on screen** | 7 overlays, exact strings in [Overlay text](#overlay-text-copy-these-strings-exactly) |
| Show the memory in action visibly — storing, retrieving, acting | Acts 2–4 are the store / retrieve / act loop, run live, not narrated |
| State the problem and who it is for, in one sentence, up front | Second zero, on camera. [The sentence](#0000009--on-camera-the-only-talking-head) |
| Demo it the way a real user would | Two buttons. No CLI, no editor, no architecture diagram |
| 3:00 hard limit, readable resolution, public, upload early | [Production](#production) |

---

## BEFORE YOU ROLL — the six-minute pre-flight

Do these in order. Item 2 is the one that will otherwise cost you take one.

1. **Open the live URL and wait for the header strip.**
   `https://retract-production.up.railway.app`
   The three fields must read real values, not `…`:
   `cluster <version>` · `embedder bedrock:amazon.titan-embed-text-v2:0` ·
   `adjudicator bedrock:claude`
   *Verified 15 Aug: `/status` returns `"adjudicator_is_model": true`.*

2. **RUN THE STORY ONCE AS A THROWAWAY, THEN HARD-REFRESH.**
   **This is the single item most likely to cost you take one.** Measured today,
   six attempts:

   | Container state | Attempts | Outcome |
   |---|---|---|
   | Cold / idle ~20min, **old build** | 2 | **2 failed.** One returned `event: error {"error_class":"timeout"}` at the server's 60s cap. One was still unfinished in the browser at 55s — effects table frozen on `EXECUTED / EXECUTED / PENDING / PENDING`, no cascade, `#punch` empty |
   | Cold, **new build** (first run after the 12:32 deploy) | 1 | completed, 37.07s |
   | Warm | 6 | **6 completed** — 31.9 / 32.2 / 32.6s on the old build, 37.8 / 37.2s and a clean browser run on the new |

   **2 of 3 cold runs have failed. 6 of 6 warm runs have passed.** The one cold
   success was on the new build, so the picture may have improved — but 37.4s
   against a 60s server cap leaves 23 seconds of headroom, not a lot. Run the
   story once before you roll, and again after any break longer than ten
   minutes. Do not let take one be the warm-up.

3. **Paste the demo token** into the header field. Both buttons fail closed
   without it. It lives in `.env` as `DEMO_TOKEN`. It is stored in
   `sessionStorage`, so a hard refresh keeps it but a new tab does not.

4. **Record at 1440 wide.** The ruler needs the room, and the effects table sits
   below the fold at 1440×900 — you will scroll once between the cascade and the
   table. Plan the scroll; do not discover it.

5. **Address bar in frame.** On this film the URL is evidence. Crop to include
   it. The token must not be visible in the address bar — it is typed into the
   page, not passed in the URL, so this is satisfied by default. Check anyway.

6. **Mic test on the first sentence.** Not on "testing one two".

---

## THE CUT — 2:40, with 20 seconds of margin

Timings marked **(measured)** are wall-clock from the deployed URL today, timed
off the server-sent events on the build now live (`7a873f2`), three runs,
consistent to ±0.4s.

### 0:00–0:09 · ON CAMERA — the only talking head

You, to camera. No title card, no logo, no "hi my name is".

**The sentence at second zero, verbatim:**

> When an agent learns something false, deleting the memory doesn't un-send the
> money it already moved. RETRACT is shared memory for agent fleets that can
> reach what a wrong belief caused — and reverse it.

Then one breath, and:

> Here it is running.

**Cut to screen on the word "running."** Nine seconds of face is the entire
budget. The prompt says judges lose interest during long intros; this is the
shortest intro that still states the problem and who it is for.

---

### 0:09–0:22 · THE RULER — why similarity cannot decide

Screen recording begins. Live URL, header strip legible for two seconds.

**Do not click yet.** Section 01 has already measured seven claim pairs against
the live embedder — the page loads with the numbers on it *(measured: the
`/api/distances` endpoint answers in 0.19s, cached; the first load of a cold
container takes ~8s and the pre-flight already paid it)*.

**Hover these two marks. They are the film's opening fact:**

| Distance | Pair | What it is |
|---|---|---|
| **1.074** | "verified via passport" / "ID verification complete" | the same fact said twice |
| **1.073** | "verified their identity" / "FAILED identity verification" | its exact negation |

Hold three seconds on both tooltips together.

> Same distance. Opposite meaning.

Then hover the third mark, which is the harder one:

| **0.636** | "Customer 4471 verified" / "Customer 4472 verified" | a *different customer* |

> And a different customer sits closer than the same fact said twice.

**OVERLAY 1** goes up here.

*Why it opens the film:* it is a fact about the world, measured on a production
embedding model, not a claim about the product.

---

### 0:22–0:38 · THE REVEAL — first click

**CLICK: `Reveal what each pair really is`** (the ghost button under the ruler).

The marks separate into two colours. Nothing moves.

> Nothing about the distances changed. Only something that read them.

That is the whole architectural argument, said once, over a live page.

---

### 0:38–1:08 · EIGHT AGENTS, ONE FACT — the race

**CLICK: `Run both, live`.** *(measured: 9.0s end to end on the new build, both panes.)*

Do not cut and do not speed it up.

- Left pane, **Naive shared memory**, lands on a big red **8**
- Right pane, **RETRACT**, lands on a big **1**, with **7 contradictions raised**
- Both panes: the **claim keys** stat. Left says **8**. Right says **1**

Point at the left pane's claim-key count and say the line most people miss:

> The eight agents also spelled the customer eight different ways. The memory
> fragmented before concurrency was even involved.

**OVERLAY 2** goes up as the panes fill.

---

### 1:08–1:45 · THE STORY — store, retrieve, act, and be wrong

**CLICK: `Run the story, live`.** *(measured on the deployed build 15 Aug:
**37.4s ±0.4** to `done`, three runs — 37.07 / 37.82 / 37.25.)*

This single click is the "memory in action, visibly" prompt, answered. Do not
cut inside it. Beat map, measured, with the film clock alongside so you know
what you are holding on:

| Run | Film | On screen | Say |
|---|---|---|---|
| 3.0–15.7s | 1:11–1:24 | five beliefs build, one every ~3.1s, drawn as a chain | *"Five beliefs. Each one derived from the one above it."* |
| 17.1–18.1s | 1:25–1:26 | four effects attach — two **executed**, two **pending** | *"Three of them already did something. A refund of $1,240 has been sent."* |
| 18.9s | 1:27 | the negation is injected: *"Customer 4471 FAILED identity verification — passport is forged"* | *"The passport was forged."* |
| 21.5s | 1:30 | `verdict_pending` — same subject, same predicate, **raised as a contradiction, not merged**, L2 0.977 | *"Same claim key. So it is not stored alongside. It is raised."* |
| 24.3s | 1:32 | the adjudicator's verdict — `superseded` — and Claude's reasoning | **OVERLAY 4.** Then say the limit, below. |
| **27.1s** | **1:35** | the contradiction is **resolved** under the same claim lock | *"And the verdict is applied, not just displayed."* |
| 27.6–31.0s | 1:36–1:39 | `retracting`, then five fallout rows strike through | *"Four beliefs retracted. Customer 9902 — untouched."* |
| 32.4–33.1s | 1:40–1:41 | the effects table settles | **scroll here**, then [the money shot](#the-money-shot) |
| 34.8s / 36.9s | 1:43 / 1:45 | the two compensation boxes: the failure first, the reversal second | |

**The 27.1s beat is new as of today's deploy** and it is the one worth naming
out loud. Until this morning the deployed build printed Claude's verdict and
then retracted regardless — invert the answer and nothing changed. It now calls
`resolve()` under the claim lock. You can say "the verdict decides something"
and it is true.

**Say this out loud at 22.7s. It is the most credible sentence in the film:**

> The database guarantees that exactly one agent adjudicates a claim at a time,
> and that the outcome is recorded atomically. It does not guarantee the verdict
> is right. A model does that, and it scores seven out of eight on our own eval.

Do not round 7/8 up and do not imply the model fixed the score — the heuristic
stand-in also scored 7/8, on a different case.

---

### 1:45–2:05 · THE MONEY SHOT

No click. This is the tail of the same run.

**Scroll to the effects table before 32.4s of the run (film 1:40).** It is below
the fold at 1440×900, and the first rehearsal pass on 14 Aug recorded this act
entirely off screen.

What the deployed URL renders, in this row order *(photographed in a browser
after today's deploy — `shoot/ending-NOW-LIVE-7a873f2.png`)*:

```
refund_issued              $1,240 sent to customer 4471                    NEEDS COMPENSATION
card_charge                $89 processed for customer 4471                 NEEDS COMPENSATION
tier_upgrade               priority support queued                         CANCELLED
welcome_email              welcome email to customer 9902                  PENDING
refund_reversal_requested  reversal of refund_issued — recorded, not dispatched   RECORDED · NOT DISPATCHED
```

*(DEMO.md predicts a different order from `ORDER BY tool`, and an ending that
says `COMPENSATED`. Both are the old build. Trust the screenshot.)*

**This ending has no win state, and that is the point.** Five rows and not one
says the system succeeded. Do not fight it in the edit — narrate it:

> The pending effect was cancelled. The executed one could not be — the money
> was already gone — so the system recorded a reversal request under its own
> idempotency key, `comp:` the original, exactly once, in the same transaction.
> It stays flagged as needing compensation until a payment provider returns a
> receipt, and no provider is wired here, so nothing settles. And the second
> charge has no registered handler at all — not even a request. The system will
> not pretend it reached something it cannot.

**Say "a reversal is recorded", never "the money came back."** As of this
morning the ledger enforces that itself: it will not print the word
`compensated` without a provider receipt. That is the strongest thing on screen
and a judge cannot catch you on it.

The two boxes above the table land failure-first, reversal-second, so the spoken
punch line ends on the reversal.

**OVERLAY 5** goes up over the table.

---

### 2:05–2:25 · THE NUMBER — before RETRACT, after RETRACT

This is a card, not the live page. It is the only slide in the film.

It exists because until today the pitch had no comparison in it — only a
description. `experiments/reach_eval.py` runs the identical scenario twice on
the same cluster: once where the wrong belief is simply corrected, the way any
agent memory would, and once through RETRACT.

**Put this on screen, unedited:**

```
                                     no RETRACT     RETRACT
  derived beliefs still active                3           0
  pending effects still live                  1           0
  executed effects nobody reached             2           0
  spent $ with a reversal RECORDED           $0      $1,240
  spent $ unreachable AND named              $0         $89
  spent $ SETTLED with a provider            $0          $0
  collateral damage to customer 9902          0           0
```

> Same case, same cluster. Correcting the belief reaches nothing: three wrong
> beliefs stay active, a pending effect still runs, and none of the $1,329
> already spent is reached by anything. RETRACT reaches all of it — records a
> reversal for $1,240, names the other $89 as unreachable, and settles zero
> dollars, because no payment provider is wired and the ledger will not say
> otherwise.

**Read the last clause out loud.** The $0-settled row is the row that makes the
other six believable.

**OVERLAY 6.**

---

### 2:25–2:40 · CLOSE

Three seconds each, or the flipbook — see below.

1. `FINDINGS.md`, the negative result: we tested whether the vector index alone
   serialises concurrent adjacent writes. It does not — 13% against an 8%
   control, p = 0.15. Published anyway, and the lock built explicitly instead.
2. The live URL. *"Press the buttons yourself."*

**On the flipbook:** it goes here or nowhere. It cannot replace any of
0:09–2:25 — the prompt asks for the live demo and the live demo is the
submission's whole argument. If the flipbook runs longer than 8 seconds, cut
the `FINDINGS.md` beat rather than the money shot. If it is not finished by
20:00, the film is complete without it and shipping beats decorating.

---

## Overlay text — copy these strings exactly

Judges confirm sponsor tech by reading the frame, not by inferring it. Every
service gets its full product name at least once. Bottom-left, mono, 2–3 seconds
each, no animation.

| # | Goes up at | Exact text |
|---|---|---|
| 1 | 0:14, over the ruler | `Amazon Bedrock · Titan Text Embeddings V2 (512-dim)`<br>`CockroachDB · Distributed Vector Index (C-SPANN)` |
| 2 | 0:42, as the race panes fill | `CockroachDB · SERIALIZABLE transactions + durable locking`<br>`SELECT … FOR UPDATE · enable_durable_locking_for_serializable = true` |
| 3 | 1:12, as beliefs build | `CockroachDB · bitemporal memory + append-only audit log` |
| 4 | 1:32, over the verdict | `Amazon Bedrock · Claude Sonnet 4.5`<br>`us.anthropic.claude-sonnet-4-5-20250929-v1:0` |
| 5 | 1:45, over the effects table | `CockroachDB · one serializable transaction:`<br>`retract the DAG · cancel pending · flag executed · write the reversal` |
| 6 | 2:08, over the number card | `experiments/reach_eval.py · same case, two arms, live cluster` |
| 7 | 2:30, over the closing URL | `CockroachDB Cloud Managed MCP Server · read-only, scoped mcp:read`<br>`retract-production.up.railway.app` |

**Overlay 7 is doing real work.** The Managed MCP Server is the second
CockroachDB tool the submission's gate needs, and it is the one least visible on
screen — it serves section 05, the fleet's contradiction receipt, which this cut
never opens. If you have ten spare seconds in the edit, scroll to section 05
after the money shot instead of putting MCP in a closing card. **Section 05 only
populates after a story run**, so it must come after act 4, never before.

---

## Production

- **3:00 is a hard reject on Devpost.** This cut is 2:40 — twenty seconds of
  margin, all of it bought by the story running 37.4s and the film not padding
  around it. Do not spend the margin on a title card at the front.
- **Public or unlisted, playable without a login.** Unlisted YouTube is fine;
  Drive links that ask for access are the classic disqualification.
- **Upload tonight, not Monday.** Then open the Devpost submission, paste the
  link, and **watch it back from the project page itself** in a logged-out
  window. The prompt asks for exactly this and it is the check nobody runs.
- **Never edit a number.** If a take produces a wrong figure, re-run the take.
- **Both buttons disable while running.** They re-enable on `done`. If a take
  breaks mid-run, hard-refresh and re-paste the token.

---

## What DEMO.md gets wrong now

Three stale things, all of which would land in a take:

1. **The ruler numbers.** DEMO.md opens on `0.531 / 0.532` as the near-touching
   pair. The live `/api/distances` today returns **1.074** (paraphrase) and
   **1.073** (negation). The *fact* survives and is stronger — a different
   customer at **0.636** is nearer than the same fact reworded at **1.074** —
   but the two figures spoken in that act are wrong.
   **This does not affect act 3.** The `0.531` the page prints next to the live
   L2 in the adjudication box is a different corpus — the story's own sentences,
   not the ruler's fragments — and it holds: measured today on Titan against the
   story's incumbent, three paraphrases came back at **0.378 / 0.456 / 0.699**
   and the negation at **1.003**. It is hardcoded in `index.html`, which is a
   smell, but it is inside the measured range and the sentence on camera is
   true. If a judge asks, those are the numbers.
2. **The timings.** DEMO.md's second table has the story at 35.2s and the
   negation arriving at 17.2s. On the build deployed at 12:32 today the story
   runs **37.4s** and the negation lands at **18.9s**.
3. **The ending.** DEMO.md's act 5 ends on `refund_issued → COMPENSATED` and
   `refund_reversed → EXECUTED`. That was the old build. The build that is live
   now ends on **`NEEDS COMPENSATION`** and
   **`refund_reversal_requested · RECORDED · NOT DISPATCHED`** — the ledger will
   not print `compensated` without a provider receipt. Shooting DEMO.md's ending
   would put a table on screen that no longer exists.
4. **The cold-run timeout is not in it at all**, because it had not happened
   yet. Pre-flight item 2 exists because of it.

DEMO.md's *rules* are still right and are inherited here: no talking head over
the demo, two buttons drive everything, never edit a number.

---

## What this guide cannot tell you

- **Whether the cold-start timeout recurs on the new build.** 2 of 3 cold runs
  have failed overall, but the only cold run on the currently-deployed build
  passed at 37.07s. One data point is not a trend in either direction. The
  warm-up run costs nothing and covers both cases, which is why the fix is in
  the pre-flight rather than in the code an hour before a shoot.
- **How the page behaves under a screen recorder.** Every timing here came from
  a terminal reading the event stream, not from a browser with a capture running.
  The beats are server-side and should not move; the render might.
- **Whether the flipbook exists.** Not built as of writing.
