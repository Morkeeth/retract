# RETRACT — one-take shot script

Every timing below is measured, not estimated. Rehearsed end to end against the
live cluster on 12 Aug: act 1 renders in 0.63s, the naive race finishes in 0.90s,
the RETRACT race in 1.85s, and acts 3+4 run 9.16s start to finish. Total
interactive time is 9.2s inside a 180s budget, so the film is mostly holding
still on numbers that are already true.

Rules: no talking head, no slides, no architecture diagram as the opener. Two
buttons drive the whole thing. If a number comes out wrong on a take, re-run the
take — never edit a number.

---

## SETUP (before recording)

    cd ~/CODE/retract
    set -a && . ./.env && set +a
    RETRACT_EMBEDDER=local uv run uvicorn app.main:app --port 8117

Open `http://localhost:8117` and **wait ~8s** for the header to stop saying
`loading` — the first page load warms the embedding model. Then hard-refresh once
so the recording starts warm. Record at 1440 wide; the ruler needs the room.

Check the header strip reads a real cluster version before you roll.

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

## 0:18 – 0:40 · THE CHALLENGE, THEN THE REVEAL

On screen already: *"7 pairs. 2 of them are the same fact said twice. Point at the 2."*

Let it sit five seconds. Nobody can.

Click **Reveal what each pair really is**. Marks separate into two clear colours.

> Nothing about the distances changed. Only something that read them.

## 0:40 – 1:15 · EIGHT AGENTS, ONE FACT

Click **Run both, live**. Do not cut. Do not speed up.

The left pane fills first (0.90s) and lands on **8**. The right takes a beat
longer (1.85s) and lands on **1** — correctness costs that beat, and the gap is
worth leaving in.

Hold on the two numbers together, then the line beneath them:
*"Same eight agents. Same cluster. Same instant. 8 beliefs on the left, 1 on the right."*

Point at the left pane's second stat: **8 claim keys**. The agents also spelled
the customer eight different ways — `Customer 4471`, `cust 4471`, `4471`. The
memory fragmented before concurrency was even involved.

## 1:15 – 1:55 · THE CONTRADICTION THAT IS REAL

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

## 1:55 – 2:30 · THE MONEY ALREADY MOVED

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

## 2:30 – 2:45 · RECEIPTS

Three cuts, four seconds each:

1. `FINDINGS.md` — the negative result. We tested whether the vector index alone
   serialises concurrent adjacent writes. It does not: 13% vs an 8% control,
   p = 0.15, and the effect shrank as power increased. Published anyway, and the
   lock built explicitly instead.
2. `experiments/` — every eval has a control arm.
3. The live URL. "Press the buttons yourself."

---

## THE BEDROCK SWAP — exactly where it changes the film

One line changes, in one shot, at **1:45**: the adjudicator verdict box.

Today it reads `by heuristic (stand-in, not a model)`. The page prints that
honestly and the eval scores it 7/8, failing the one case that needs real
reasoning — "verified by passport" versus "verified by driving licence".

**Do not shoot the final take with the stand-in visible.** A judge reads that box.

When Bedrock model access lands:

    RETRACT_ADJUDICATOR=bedrock AWS_REGION=us-east-1 \
      RETRACT_EMBEDDER=bedrock uv run uvicorn app.main:app --port 8117

Confirm the header strip now names a Claude model, re-run
`experiments/adjudicate_eval.py` and expect 8/8, then reshoot **from 1:15**.
Acts 1, 2 and 4 are unaffected and their takes remain valid.

Nothing else in this script changes.

---

## PRE-FLIGHT

- [ ] Header shows a real cluster version, not `loading`
- [ ] One warm-up run so the embedder is hot
- [ ] Adjudicator line checked — stand-in for rehearsal, Claude for the final
- [ ] 1440 wide
- [ ] Both buttons re-enabled (they disable while running)
