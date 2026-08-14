# RETRACT — brand assets

These live here, **committed**, on purpose. The wordmark was lost once (14 Aug) because
it existed only as a PNG under the gitignored `rehearsal/` path and a harness re-run took
the directory. An artifact that exists nowhere but one disk is one command from never having
existed. Everything here is regenerable from source and tracked in git.

## The signature device — the recorded strike

RETRACT struck through in the retraction red, the word left **fully legible**. A retraction
records the reversal, it does not erase the fact. That is the product's thesis, made in the
mark rather than in a sentence. The reversal id beneath the word is the real one from the
shipped ledger, so the mark is evidence, not decoration. It is also live on the page:
retracted belief rows carry the same strike.

## Files

- `wordmark.py` — the generator. `python brand/wordmark.py` re-renders every asset below.
  Palette is **cited** from `app/static/index.html` `:root`, oklch tokens converted to sRGB
  in-script, so the mark stays locked to the page. Two presets because the identity is
  mid-flip:
  - `retract-wordmark-dark.png` / `retract-mark-square-dark.png` — the shipped dark build.
  - `retract-wordmark-paper.png` / `retract-mark-square-paper.png` — the paper identity now
    on `design/brand-identity`.

## When the page palette changes

Update the token values in `wordmark.py`'s `PALETTES` to match the new `:root`, then re-run.
Do **not** hand-edit the PNGs. If a third identity lands, add a preset; the device does not
change, only the ground it sits on.
