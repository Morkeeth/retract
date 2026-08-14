"""Drive the deployed demo end to end and time it. A REHEARSAL, not the take.

WHAT THIS IS NOT
It is not the video. DEMO.md specifies a film with the address bar in frame,
hover tooltips held for three seconds, and a spoken limit at 1:38. This is a
headless browser: no chrome, no cursor, no narration, no holds. The .webm it
leaves behind is a recording of the demo working, which is a different object
from a recording of the demo being shown. Nothing here should ever be described
as the take having been shot.

WHAT IT IS FOR
Two numbers that are worth more today than on Saturday evening.

1. Act 5's real duration. DEMO.md's own "what this script cannot tell you"
   section admits that every timing after 2:20 is estimated, because act 5 has
   never been run by anyone. It budgets 25 seconds for it. This measures the
   span from the ledger showing `needs_compensation` to the stream closing, off
   the wire, so the shot list can stop guessing.
2. Whether the public URL hiccups under the real sequence. Any non-2xx
   response, any failed request, any console error is collected and printed.
   A URL that stumbles once in ten runs is something to find out on a Thursday.

HOW THE TIMING IS TAKEN
By wrapping EventSource before the page's own scripts run, so every server-sent
event is stamped as the browser receives it. Reading the DOM instead would time
the page's animations, which is the wrong clock: the question is when the system
did the thing, not when the CSS finished saying so.

USAGE
Playwright is installed against the system python3, not the uv venv, so this
one script is deliberately run with plain python3 -- everything else in
experiments/ takes `uv run python`.

    DEMO_TOKEN=... python3 experiments/rehearse.py
    DEMO_TOKEN=... python3 experiments/rehearse.py --runs 3

The token is injected into sessionStorage before the first script runs, so it
is never typed and never reaches the address bar.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time

from playwright.sync_api import sync_playwright

URL = os.environ.get("RETRACT_URL", "https://retract-production.up.railway.app")

# DEMO.md shoots at 1440 wide because the ruler needs the room.
VIEWPORT = {"width": 1440, "height": 900}

# The header warms the embedding model on first load. DEMO.md says wait ~8s.
WARM_S = 10.0

# Stamp every server-sent event as it arrives, before the page's scripts run.
PROBE = """
window.__marks = [];
window.__t0 = {};
const Native = window.EventSource;
window.EventSource = function (url, opts) {
  const es = new Native(url, opts);
  const stream = String(url).split('?')[0];
  window.__t0[stream] = performance.now();
  const record = (type, raw) => {
    let status = null;
    try { status = JSON.parse(raw).status ?? null; } catch (e) {}
    window.__marks.push({
      stream, type, status,
      t: (performance.now() - window.__t0[stream]) / 1000,
    });
  };
  const addEventListener = es.addEventListener.bind(es);
  es.addEventListener = function (type, fn, o) {
    return addEventListener(type, (ev) => { record(type, ev.data); return fn(ev); }, o);
  };
  return es;
};
window.EventSource.prototype = Native.prototype;
"""


def redact(url: str) -> str:
    """Strip the demo token out of any URL before it is written down.

    The page passes the token as `?token=` because EventSource cannot set a
    header. That means the raw secret appears in every request URL, and the
    first version of this script copied those URLs verbatim into the report
    and printed them to the terminal. A rehearsal artefact is not a place to
    leave a live credential.
    """
    return re.sub(r"([?&]token=)[^&]*", r"\1REDACTED", url)


class Pointer:
    """Records where each action landed, in video-frame coordinates.

    WHY THIS EXISTS
    Playwright composites the page and not the pointer, so no frame in any
    rehearsal contains a cursor. That is the largest single gap between this
    output and a Screen Studio-class recording: in post you cannot draw a cursor
    you have no position for, and you cannot centre a zoom on a click you have to
    guess at. This track is the missing input for both.

    IT OBSERVES, IT DOES NOT DRIVE. Every position is read from the element the
    script was already going to act on, at the moment it was already going to act.
    No hold is shortened, no click is moved, no step is added or reordered -- the
    timings in DEMO.md exist so the DOM settles, and a video harness that edits
    them is editing the run rather than the recording.

    HONEST LIMITS, because a timeline that claims more precision than it has is
    worse than none:
      - `t_ms` is measured from the moment the page object is created, which is
        as close to the video's first frame as Playwright exposes. It is not
        frame-exact; expect tens of milliseconds of offset, in one direction for
        the whole track. Calibrate once against a visible transition rather than
        trusting it absolutely.
      - Reading a bounding box costs one CDP round-trip that the run did not
        previously make. Measured cost is reported per run as `probe_ms` so it
        can be compared against the run-to-run spread instead of assumed to be
        free.
      - Coordinates are viewport-relative, which equals frame-relative only
        because the recording size and the viewport are both 1440x900. If those
        are ever set differently, this mapping is wrong and silently so.
    """

    def __init__(self) -> None:
        self.marks: list[dict] = []
        self._t0: float | None = None
        self.probe_ms = 0.0

    def start(self) -> None:
        """Call immediately after the page is created -- video t0."""
        self._t0 = time.monotonic()

    def _stamp(self, kind: str, target: str, box: dict | None) -> None:
        if self._t0 is None or box is None:
            return
        self.marks.append({
            "t_ms": round((time.monotonic() - self._t0) * 1000),
            # Playwright acts on the element's centre unless told otherwise, so
            # the centre is the true pointer position, not the box origin.
            "x": round(box["x"] + box["width"] / 2),
            "y": round(box["y"] + box["height"] / 2),
            "kind": kind,
            "target": target,
        })

    def _box(self, locator):
        t = time.monotonic()
        box = locator.bounding_box()
        self.probe_ms += (time.monotonic() - t) * 1000
        return box

    def scroll(self, page, selector: str) -> None:
        loc = page.locator(selector)
        loc.scroll_into_view_if_needed()
        # After the scroll, not before: the box is what the frame will show.
        self._stamp("scroll", selector, self._box(loc))

    def click(self, page, selector: str) -> None:
        loc = page.locator(selector)
        # Before the click, because the click is what changes the page.
        self._stamp("click", selector, self._box(loc))
        loc.click()


def rehearse(page, out: dict, ptr: "Pointer | None" = None) -> None:
    """One full pass: warm, reveal, race, story. Mirrors DEMO.md's order."""
    page.goto(URL, wait_until="domcontentloaded")

    # DEMO.md pre-flight: the header must read a real cluster version, not
    # `loading`, before anything is worth recording.
    page.wait_for_function(
        "() => { const t = document.querySelector('#f-cluster')?.textContent || ''; "
        "return t && !/^[…\\s]*$/.test(t) && !/loading/i.test(t); }",
        timeout=60_000,
    )
    out["header"] = {
        sel: page.text_content(sel) for sel in ("#f-cluster", "#f-embed", "#f-adj")
    }

    # One warm-up reload so the take starts hot, exactly as the shot list says.
    time.sleep(WARM_S)
    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("#reveal", timeout=30_000)

    # 0:18 -- the reveal. No write path, so no token involved.
    ptr.scroll(page, "#reveal")
    t = time.monotonic()
    ptr.click(page, "#reveal")
    page.wait_for_timeout(1500)
    out["reveal_s"] = round(time.monotonic() - t, 2)

    # 0:36 -- both races, live. Waits on the button re-enabling rather than a
    # fixed sleep: the whole point of the beat is that the two panes differ.
    ptr.scroll(page, "#run")
    t = time.monotonic()
    ptr.click(page, "#run")
    page.wait_for_function(
        "() => !document.querySelector('#run').disabled", timeout=120_000
    )
    out["race_s"] = round(time.monotonic() - t, 2)
    out["race_result"] = {
        "naive_beliefs": page.text_content("#n-big"),
        "retract_beliefs": page.text_content("#r-big"),
        "naive_keys": page.text_content("#n-keys"),
        "retract_keys": page.text_content("#r-keys"),
        "contradictions": page.text_content("#r-con"),
    }

    # 1:08 through the end -- the story, including act 5's tail.
    # The predicate has to name the story stream. Both race streams also close
    # with `done`, and an unqualified check is satisfied by one of those the
    # instant the click lands -- which reports a 0.02s story and records no act
    # 5 at all.
    ptr.scroll(page, "#tell")
    t = time.monotonic()
    ptr.click(page, "#tell")
    page.wait_for_function(
        "() => (window.__marks || []).some("
        "m => m.type === 'done' && m.stream.endsWith('/story'))",
        timeout=180_000,
    )
    out["story_s"] = round(time.monotonic() - t, 2)

    # At 1440x900 the effects table sits below the fold, so a capture that never
    # scrolls records act 5 happening off screen -- which is what the first pass
    # of this script did. DEMO.md's shot list does not mention a scroll; the real
    # take needs one here too.
    ptr.scroll(page, "#fx")
    page.wait_for_timeout(2500)  # let the effects table settle before the cut
    out["effects_table"] = page.text_content("#fx")
    out["punch"] = page.text_content("#punch")
    out["marks"] = page.evaluate("() => window.__marks")


def act_five(marks: list[dict]) -> dict:
    """Act 5 is the tail: ledger says needs_compensation, then the money returns.

    Measured from the effect_final that flags the executed refund to the stream
    closing. That is the span DEMO.md budgets 25 seconds for without ever
    having run it.
    """
    story = [m for m in marks if m["stream"].endswith("/story")]
    flag = next(
        (m for m in story if m["type"] == "effect_final"
         and m.get("status") == "needs_compensation"), None
    )
    comp = next((m for m in story if m["type"] == "compensated"), None)
    done = next((m for m in story if m["type"] == "done"), None)
    if not (flag and comp and done):
        return {"measured": False,
                "why": "story stream did not carry flag + compensated + done"}
    return {
        "measured": True,
        "flag_at_s": round(flag["t"], 2),
        "compensated_at_s": round(comp["t"], 2),
        "stream_end_s": round(done["t"], 2),
        "act5_duration_s": round(done["t"] - flag["t"], 2),
        "demo_md_budget_s": 25.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1,
                    help="repeat the sequence; more than one is how a hiccup shows up")
    ap.add_argument("--out", default="rehearsal",
                    help="directory for the video and the timing report")
    args = ap.parse_args()

    token = os.environ.get("DEMO_TOKEN")
    if not token:
        print("DEMO_TOKEN is unset; the write paths return 401 without it",
              file=sys.stderr)
        return 1

    outdir = pathlib.Path(args.out)
    outdir.mkdir(exist_ok=True)
    report = {"url": URL, "runs": []}

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for i in range(args.runs):
            hiccups: list[dict] = []
            ctx = browser.new_context(
                viewport=VIEWPORT,
                record_video_dir=str(outdir),
                record_video_size=VIEWPORT,
            )
            # Never typed, never in the address bar, never in frame.
            ctx.add_init_script(
                f"sessionStorage.setItem('demo_token', {json.dumps(token)});"
            )
            ctx.add_init_script(PROBE)
            page = ctx.new_page()
            # Start the pointer clock as close to the video's first frame as
            # Playwright lets us stand: the page object is what the recorder
            # attaches to.
            ptr = Pointer()
            ptr.start()
            page.on("console", lambda m: m.type == "error"
                    and hiccups.append({"kind": "console", "text": m.text}))
            # A completed EventSource is closed by the page, which Chromium
            # reports as ERR_ABORTED on the stream URL. That is the demo working,
            # not the URL stumbling, so it is recorded as expected rather than
            # counted against the run.
            page.on("requestfailed", lambda r: hiccups.append(
                {"kind": "sse_closed" if (r.failure or "").startswith("net::ERR_ABORTED")
                 and "/api/run/" in r.url else "requestfailed",
                 "url": redact(r.url), "error": r.failure or "unknown"}))
            page.on("response", lambda r: r.status >= 400 and hiccups.append(
                {"kind": "http", "status": r.status, "url": redact(r.url)}))

            run: dict = {"n": i + 1, "hiccups": hiccups}
            try:
                rehearse(page, run, ptr)
                run["act5"] = act_five(run.get("marks", []))
            except Exception as exc:  # noqa: BLE001 - a failed pass is a result
                run["error"] = f"{type(exc).__name__}: {exc}"
            run["pointer"] = ptr.marks
            run["pointer_probe_ms"] = round(ptr.probe_ms, 1)
            video = page.video
            ctx.close()  # the video is only finalised on close
            if video:
                run["video"] = video.path()
            report["runs"].append(run)
            real = [h for h in hiccups if h["kind"] != "sse_closed"]
            print(f"-- run {i + 1}/{args.runs}: "
                  f"{'ERROR ' + run['error'] if 'error' in run else 'completed'}, "
                  f"{len(real)} hiccup(s)")
        browser.close()

    path = outdir / "rehearsal.json"
    path.write_text(json.dumps(report, indent=2))

    # One pointer track per run, named after its video, because the pair is what
    # post needs and a track without its footage is not usable.
    for run in report["runs"]:
        if not run.get("pointer") or not run.get("video"):
            continue
        track = pathlib.Path(run["video"]).with_suffix(".pointer.json")
        track.write_text(json.dumps({
            "video": run["video"],
            "frame": VIEWPORT,
            "t0": "page creation; not frame-exact -- calibrate once against a visible transition",
            "marks": run["pointer"],
        }, indent=2))
        run["pointer_track"] = str(track)

    print("\n=== REHEARSAL (not the take) ===")
    for run in report["runs"]:
        print(f"\nrun {run['n']}")
        if "error" in run:
            print(f"  ERROR   {run['error']}")
        for key in ("reveal_s", "race_s", "story_s"):
            if key in run:
                print(f"  {key:<12} {run[key]}s")
        if run.get("race_result"):
            r = run["race_result"]
            print(f"  race         naive={r['naive_beliefs']} beliefs / "
                  f"{r['naive_keys']} keys · retract={r['retract_beliefs']} / "
                  f"{r['retract_keys']} keys · {r['contradictions']} contradictions")
        a5 = run.get("act5", {})
        if a5.get("measured"):
            print(f"  ACT 5        {a5['act5_duration_s']}s measured "
                  f"(DEMO.md budgets {a5['demo_md_budget_s']}s) -- "
                  f"flag {a5['flag_at_s']}s, compensated {a5['compensated_at_s']}s, "
                  f"end {a5['stream_end_s']}s")
        elif a5:
            print(f"  ACT 5        NOT MEASURED: {a5.get('why')}")
        real = [h for h in run["hiccups"] if h["kind"] != "sse_closed"]
        expected = len(run["hiccups"]) - len(real)
        print(f"  hiccups      {len(real)}"
              + (f"  ({expected} expected SSE close ignored)" if expected else ""))
        for h in real[:8]:
            print(f"               {h}")
        if run.get("video"):
            print(f"  video        {run['video']}")
        if run.get("pointer"):
            print(f"  pointer      {len(run['pointer'])} marks, "
                  f"{run['pointer_probe_ms']}ms of probes across the run")
    print(f"\nreport  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
