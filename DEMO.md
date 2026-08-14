# RETRACT — one-take shot script

Every timing below is measured, not estimated. Rehearsed end to end against the
live cluster on 12 Aug: act 1 renders in 0.63s, the naive race finishes in 0.90s,
the RETRACT race in 1.85s, and acts 3+4 run 9.16s start to finish. Total
interactive time is 9.2s inside a 180s budget, so the film is mostly holding
still on numbers that are already true.

**Re-measured 14 Aug against the deployed URL, and the numbers above no longer
describe it.** Seven passes of `experiments/rehearse.py` on
`retract-production.up.railway.app`, timed off the server-sent events rather
than off the DOM, are consistent to within 0.1s:

| Beat | Click to settled | Was |
|---|---|---|
| Reveal | 1.5s | 0.63s (act 1 render, a different span) |
| **Run both, live** | 8.3s | 0.90s / 1.85s per pane |
| **Run the story, live** | 27.7s | 9.16s for acts 3+4 |

Total interactive time is **37.5s**, not 9.2s. The claim that the film is mostly
holding still on finished numbers survives — 37.5s of system time inside a 180s
cut still leaves most of the runtime as holds — but the shot list can no longer
be timed off the old figures. The story alone eats 27.7s, and five beliefs build
at ~2.9s apart before the negation arrives at **17.2s**, not the 5.3s written at
act 3 below.

Both the old and new figures are wall-clock for what a viewer sees, but they are
not the same spans, so this table replaces rather than corrects them.

Rules: no talking head, no slides, no architecture diagram as the opener. Two
buttons drive the whole thing. If a number comes out wrong on a take, re-run the
take — never edit a number.

---

## SETUP (before recording)

**Rehearse on localhost. Shoot the take on the public URL.** This script used to
say to record against `localhost:8117`, and PLAN.md says in the same breath that
a judge who sees `localhost:8117` has watched a private demo. Both cannot be
right. The deployed URL wins: it is the only address that proves the thing runs
anywhere but this laptop, and it is free to look at now that `/api/distances` is
cached.

Rehearsal, as many times as you like:

    cd ~/CODE/retract
    set -a && . ./.env && set +a
    RETRACT_EMBEDDER=local uv run uvicorn app.main:app --port 8117

The take, and every take that reaches the cut:

    open https://retract-production.up.railway.app

**Wait ~8s** for the header to stop saying `loading` — the first page load warms
the embedding model. Then hard-refresh once so the recording starts warm. Record
at 1440 wide; the ruler needs the room.

Check the header strip reads a real cluster version before you roll. And check
the address bar is in frame — on this film the URL is evidence, so crop to
include it rather than cropping it out.

---

## 0:00 – 0:18 · THE NUMBER

Cold open on the ruler. No title card.

Hover two marks that nearly touch. Tooltips:

    0.531   "verified via passport"  /  "ID verification complete"
    0.532   "verified via passport"  /  "FAILED verification"

Hold three seconds on those two tooltips.

> Same distance. Opposite meaning. One is the same fact said twice; the other is
> its negation.

*Why it opens:* it is a fact about the world, not a claim about the product.

## 0:18 – 0:36 · THE CHALLENGE, THEN THE REVEAL

On screen already: *"7 pairs. 2 of them are the same fact said twice. Point at the 2."*

Let it sit five seconds. Nobody can.

Click **Reveal what each pair really is**. Marks separate into two clear colours.

> Nothing about the distances changed. Only something that read them.

## 0:36 – 1:08 · EIGHT AGENTS, ONE FACT

Click **Run both, live**. Do not cut. Do not speed up.

The left pane fills first (0.90s) and lands on **8**. The right takes a beat
longer (1.85s) and lands on **1** — correctness costs that beat, and the gap is
worth leaving in.

Hold on the two numbers together, then the line beneath them:
*"Same eight agents. Same cluster. Same instant. 8 beliefs on the left, 1 on the right."*

Point at the left pane's second stat: **8 claim keys**. The agents also spelled
the customer eight different ways — `Customer 4471`, `cust 4471`, `4471`. The
memory fragmented before concurrency was even involved.

## 1:08 – 1:45 · THE CONTRADICTION THAT IS REAL

Click **Run the story, live**. Five beliefs build, three effects attach — one of
them a refund that **executes**.

At 5.3s the negation arrives: *"Customer 4471 FAILED identity verification —
passport is forged."* Same subject, same predicate.

It comes back **raised as a contradiction, not merged**, at L2 0.608 — against a
paraphrase baseline of 0.531 shown right beside it.

Then the adjudicator's verdict and its reasoning.

**Say the limit out loud here.** The database guarantees that exactly one agent
adjudicates a claim at a time and that the outcome is atomic. It does not
guarantee the verdict is right. That sentence buys more credibility than any
claim in the film.

## 1:45 – 2:20 · THE MONEY ALREADY MOVED

The cascade runs on screen. Four beliefs strike through as RETRACTED. Customer
9902 stays UNTOUCHED — say that out loud, it is the blast-radius proof.

Then the effects table flips:

    refund_issued    $1,240 sent to customer 4471    NEEDS COMPENSATION
    tier_upgrade     priority support queued          CANCELLED
    welcome_email    welcome email to customer 9902   PENDING

Linger. The pending effect is cancelled. The executed one is **not** — the money
is gone and the system says so.

> An agent memory that cannot reach its own side effects is a diary, not a
> system of record.

## 2:20 – 2:45 · THE MONEY COMES BACK

**This is the ending, and the film does not have it yet.** Every other act shows
a system noticing something. This is the only one where it acts. Cut the
receipts before you cut this.

**There is no button, and there should not be one.** An earlier draft of this
section said to click **Compensate**. That was wrong, and it was wrong because
it was written from PR #2's description of itself — which says the PR "did not
wire compensation into the UI" — rather than from PR #2's diff, which does.
`app/main.py` runs the compensation inside the story stream and the page already
renders the reversal. Read the diff, not the summary of the diff.

Keeping it automatic is also the better film. This script's own rule is that two
buttons drive the whole thing; a third click between the flag and the reversal
would put a human decision in the middle of the one moment that is supposed to
show the system acting on its own.

So act 5 needs nothing clicked. It is the tail of **Run the story, live**, and
what it needs instead is PR #2 merged and verified against the live cluster.

No click. The story keeps running, and the table settles — **this is what the
deployed URL actually renders, captured 14 Aug**:

    refund_issued     $1,240 sent to customer 4471      COMPENSATED
    tier_upgrade      priority support queued           CANCELLED
    welcome_email     welcome email to customer 9902    PENDING
    refund_reversed   reversal of refund_issued         EXECUTED

**There is no `card_charge` row, and this script asked you to hold on it for
two seconds.** An earlier draft of this act listed a fourth effect, `$89
processed / NEEDS COMPENSATION`, as "the most important row on screen and the
one that did not work". Grep says `card_charge` exists in exactly two places:
`experiments/compensate_eval.py`, where it is the control arm proving an
unregistered tool is refused, and this file. The story scenario in
`app/main.py` has three effects and none of them is it. So the film's honesty
beat — the failure left visible on purpose — has no object on screen.

That is a decision, not a typo, and it belongs to the owner:

- **Leave it.** The act ends on `COMPENSATED` + `EXECUTED`, which is a true and
  strong ending, and the film loses the row that separates a demo from a
  measurement.
- **Add it.** One executed effect with no registered handler in the story
  scenario. It invents no abstraction — `retract/compensate.py` already returns
  `no_handler` for exactly this, the page already renders `needs_compensation`,
  and MORNING-RUN's own hostile-read table asks every surface to say both
  halves: closed-loop for registered tools, flagged for unknown ones. Right now
  the page says only the first half.

Until that is ruled on, shoot the four rows that exist and do not read the
missing one aloud.

> The reversal is a new effect with its own id, not a deletion. And the tool
> with no registered compensation stays flagged — the system will not pretend
> it fixed something it cannot reach.

*Why the failure stays in the film:* every agent-memory product can show you a
happy path. Leaving `card_charge` red is the difference between a demo and a
measurement, and it is the same reason `FINDINGS.md` publishes a null result.

**Do not shoot this act until `experiments/verify_live.sh` is green against the
live cluster.** A reversal that has only ever run locally is a claim.

## 2:45 – 2:55 · RECEIPTS

Compressed to make room for act 5. Three cuts, three seconds each:

1. `FINDINGS.md` — the negative result. We tested whether the vector index alone
   serialises concurrent adjacent writes. It does not: 13% vs an 8% control,
   p = 0.15, and the effect shrank as power increased. Published anyway, and the
   lock built explicitly instead.
2. `experiments/` — every eval has a control arm.
3. The live URL. "Press the buttons yourself."

---

## THE BEDROCK SWAP — exactly where it changes the film

One line changes, in one shot, at **1:38**: the adjudicator verdict box.

Today it reads `by heuristic (stand-in, not a model)`. The page prints that
honestly and the eval scores it 7/8, failing the one case that needs real
reasoning — "verified by passport" versus "verified by driving licence".

**Do not shoot the final take with the stand-in visible.** A judge reads that box.

When Bedrock model access lands:

    RETRACT_ADJUDICATOR=bedrock AWS_REGION=us-east-1 \
      RETRACT_EMBEDDER=bedrock uv run uvicorn app.main:app --port 8117

Confirm the header strip now names a Claude model, re-run
`experiments/adjudicate_eval.py` and expect 8/8, then reshoot **from 1:08**.
Acts 1, 2 and 4 are unaffected and their takes remain valid.

Nothing else in this script changes.

---

## PRE-FLIGHT

- [ ] **Address bar reads the Railway URL, not `localhost`** — and is in frame
- [ ] Header shows a real cluster version, not `loading`
- [ ] One warm-up run so the embedder is hot
- [ ] Adjudicator line checked — stand-in for rehearsal, Claude for the final
- [ ] 1440 wide
- [ ] Both buttons re-enabled (they disable while running)
- [ ] **PR #2 merged and `verify_live.sh` green** — act 5 is already wired in
      that PR; what it lacks is a live run, not a button
- [ ] **Total runtime under 3:00** — Devpost rejects over. This cut lands 2:55,
      so there is five seconds of margin and no room for an intro card

---

## WHAT THIS SCRIPT STILL CANNOT TELL YOU

Stated here rather than discovered on the day:

- ~~**Every timing above 2:20 is estimated, not measured.** Act 5 has never been
  run by anyone, so its 25 seconds is a guess.~~ **Measured 14 Aug, seven
  passes.** Act 5 — from the ledger flagging `needs_compensation` to the stream
  closing — is **2.6s**, not 25s. The two numbers are different clocks: 25s was
  film time including holds and narration, 2.6s is the system. The consequence
  for the shoot is concrete: the reversal lands **2.4s** after the red flag
  appears, so "linger on the executed effect that is still red" cannot be done
  in the run. Hold it in the edit, or lose it.
- **The effects table sits below the fold at 1440x900.** The first rehearsal
  pass recorded act 5 happening entirely off screen. The shot list above never
  mentions a scroll, and the take needs one between the cascade and the table.
- **Whether the public URL behaves like localhost under recording.** The demo
  has only ever been driven locally. Network latency on the two race panes is
  the number most likely to move, and the race is the act that depends on a
  visible 0.90s / 1.85s gap.
- **Whether PR #2's demo token gates the buttons on the public URL.** If it
  does, the take needs the token in the session and the address bar must not
  show it.
