#!/usr/bin/env python3
"""RETRACT wordmark generator — the signature device, rendered from tokens.

WHY THIS IS A SCRIPT AND NOT A PNG
The wordmark died once already (14 Aug) because it existed only as a file under a
gitignored path, and a harness re-run took the directory with it. The judgement in
the wordmark is not the pixels; it is the device and its palette citation. So the
durable form is the generator, committed. Whatever the page identity settles to,
`python brand/wordmark.py` re-renders the mark on that ground in one command.

THE DEVICE
The recorded strike: RETRACT struck through in the retraction red, the word left
fully legible. A retraction records the reversal, it does not erase the fact — that
is the product's whole thesis, made in the mark. The reversal id beneath it is the
real one from the shipped ledger, so the mark is evidence, not decoration.

PALETTE IS CITED, NEVER INVENTED
Every colour is an oklch token lifted from app/static/index.html, named to the row
it comes from. Two presets because the identity is mid-flip (dark shipped -> paper
proposal); both render from the same device. Update the tokens here when the page's
:root changes, and the mark stays locked to the page.
"""
from __future__ import annotations

import math
import pathlib

from PIL import Image, ImageDraw, ImageFont

OUT = pathlib.Path(__file__).resolve().parent
HEAVY = "/System/Library/Fonts/SF-Mono-Heavy.otf"
MED = "/System/Library/Fonts/SF-Mono-Medium.otf"
REG = "/System/Library/Fonts/SF-Mono-Regular.otf"
REVERSAL_ID = "reversal 4b5528d5-5234-4297-8da8-2de9614e8a02"  # real, from the shipped ledger


def oklch_to_rgb(L: float, C: float, h_deg: float) -> tuple[int, int, int]:
    """oklch -> sRGB 0..255, so the mark renders the page's own :root tokens."""
    h = math.radians(h_deg)
    a, b = C * math.cos(h), C * math.sin(h)
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_
    g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_
    bl = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_

    def enc(x: float) -> int:
        x = max(0.0, min(1.0, x))
        x = 1.055 * x ** (1 / 2.4) - 0.055 if x > 0.0031308 else 12.92 * x
        return round(max(0.0, min(1.0, x)) * 255)

    return (enc(r), enc(g), enc(bl))


# ---- presets: tokens copied from app/static/index.html :root, cited per line ----
PALETTES = {
    # the shipped dark build (the design that is live in the 12:21 recordings)
    "dark": {
        "ground": (0.135, 0.020, 208),   # --ground
        "ink": (0.95, 0.008, 208),       # --ink
        "strike": (0.635, 0.233, 25),    # --strike = NEEDS COMPENSATION vermilion
        "receipt": (0.80, 0.150, 168),   # --ok, teal-green
        "receipt_upper": False,
    },
    # the paper identity now in the working tree on design/brand-identity
    "paper": {
        "ground": (0.977, 0.002, 250),   # --ground (the sheet)
        "ink": (0.235, 0.012, 265),      # --ink
        "strike": (0.555, 0.216, 27),    # --strike / --corrupt
        "receipt": (0.545, 0.010, 265),  # --ink-dim (matches live .brcpt)
        "receipt_upper": True,
    },
}


def render(name: str, pal: dict) -> None:
    S = 2
    W, H = 1600 * S, 620 * S
    ground = oklch_to_rgb(*pal["ground"])
    ink = oklch_to_rgb(*pal["ink"])
    strike = oklch_to_rgb(*pal["strike"])
    receipt = oklch_to_rgb(*pal["receipt"])

    im = Image.new("RGB", (W, H), ground)
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(HEAVY, 150 * S)
    word = "RETRACT"
    track = 12 * S
    ws = [d.textlength(c, font=f) for c in word]
    total = sum(ws) + track * (len(word) - 1)
    x0 = (W - total) // 2
    y0 = 150 * S

    def draw_word():
        x = x0
        for c, w in zip(word, ws):
            d.text((x, y0), c, font=f, fill=ink)
            x += w + track

    draw_word()
    sy = int(y0 + f.size * 0.60)
    d.rectangle([x0 - 10 * S, sy - 3 * S, x0 + total + 10 * S, sy + 3 * S], fill=strike)
    draw_word()  # redraw so the word stays legible THROUGH the strike (recorded, not erased)

    fr = ImageFont.truetype(MED, 34 * S)
    r = "reversal recorded, not erased"
    if pal["receipt_upper"]:
        r = r.upper()
    rw = d.textlength(r, font=fr)
    d.text(((W - rw) // 2, y0 + f.size + 44 * S), r, font=fr, fill=receipt)

    fi = ImageFont.truetype(REG, 24 * S)
    iw = d.textlength(REVERSAL_ID, font=fi)
    dim = oklch_to_rgb(pal["ink"][0] * 0.7 + pal["ground"][0] * 0.3, pal["ink"][1], pal["ink"][2])
    d.text(((W - iw) // 2, y0 + f.size + 94 * S), REVERSAL_ID, font=fi, fill=dim)

    im = im.resize((W // S, H // S), Image.LANCZOS)
    path = OUT / f"retract-wordmark-{name}.png"
    im.save(path)

    # square crop for avatars/tiles
    sq = Image.new("RGB", (1080, 1080), ground)
    scale = 980 / im.width
    nw, nh = int(im.width * scale), int(im.height * scale)
    sq.paste(im.resize((nw, nh), Image.LANCZOS), ((1080 - nw) // 2, (1080 - nh) // 2))
    sq.save(OUT / f"retract-mark-square-{name}.png")
    print("rendered", path.name, "+ square")


if __name__ == "__main__":
    for name, pal in PALETTES.items():
        render(name, pal)
