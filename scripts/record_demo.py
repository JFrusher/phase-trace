"""Record the tracer demo GIF: one real possession, traced through the real app.

    python scripts/record_demo.py                        # carry_pass_carry_kick
    python scripts/record_demo.py --fixture phase_chain_5

Drives a tracer/fixtures.py scenario through a headed browser against a live
`python -m tracer.app`, records it with Playwright's own video capture, and
converts the webm to a GIF. Nothing is mocked: the line is classified by the
real recognizer as it is drawn, and the run fails loudly if the classification
does not match the fixture's own expectation.

Swap the fixture and rerun to record a different possession - waypoints, pace,
taps and Shift intervals all come from the Scenario, so a trace promoted from a
real match records the same way a synthetic one does.

ffmpeg: the system one if it is on PATH, else the build Playwright ships for
its own video capture. That build is `--disable-everything` with a whitelist -
it can decode VP8 and write PNGs, but has no GIF encoder and no palettegen /
paletteuse / fps filters. So frames come out of ffmpeg and Pillow assembles the
GIF. Flat SVG fill, ~6 colours, nowhere near the 256 limit, so the cheaper
quantizer costs nothing visible here.
"""

import argparse
import dataclasses
import math
import random
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageColor
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tracer import config                          # noqa: E402
from tracer.canvas import ACTION_COLORS            # noqa: E402
from tracer.fixtures import SCENARIOS, Scenario, noisy_path   # noqa: E402
from tracer.pitch import IMAGE_W                   # noqa: E402

PORT = 8099
# wide enough that the header stays one row when the status text grows from
# "0 events" to "won on kick - 1 events" mid-take; a wrap there shifts the
# pitch down and the crop clips its bottom edge
VIEWPORT = {"width": 1280, "height": 700}
MOVE_SLEEP = 0.02                           # ~30Hz once round-trip overhead is counted
LEAD_IN_S, LEAD_OUT_S = 0.9, 1.4            # kept either side of the drag

# Playwright's video capture draws no cursor, so an uncommented recording shows
# a line growing on its own rather than someone tracing it. This puts the
# pointer back - decoration over a real trace, not a substitute for one.
CURSOR_JS = """
const dot = document.createElement('div');
dot.style.cssText = 'position:fixed;z-index:99999;width:15px;height:15px;' +
  'margin:-7px 0 0 -7px;border-radius:50%;background:rgba(255,255,255,.92);' +
  'box-shadow:0 0 0 2px rgba(0,0,0,.5);pointer-events:none;left:-99px;top:-99px';
document.body.appendChild(dot);
addEventListener('mousemove', e => {
  dot.style.left = e.clientX + 'px';
  dot.style.top = e.clientY + 'px';
}, true);
addEventListener('mousedown', () => { dot.style.transform = 'scale(.65)'; }, true);
addEventListener('mouseup', () => { dot.style.transform = 'scale(1)'; }, true);
"""
LIVE_TRACE_KEYS = ("s", "z")                # see _preamble
SCRATCH = REPO / "scratch" / "demo_recording"
OUT_GIF = REPO / "docs" / "marketing" / "tracer_demo.gif"


def find_ffmpeg() -> tuple[Path, str]:
    """(binary, where it came from). Playwright's own build is the fallback."""
    system = shutil.which("ffmpeg")
    if system:
        return Path(system), "system PATH"
    from playwright._impl._driver import compute_driver_executable  # noqa: PLC0415
    driver = Path(compute_driver_executable()[0]).parent
    for pattern in ("ffmpeg-win64.exe", "ffmpeg-*"):
        found = sorted(Path.home().glob(
            f"AppData/Local/ms-playwright/ffmpeg-*/{pattern}"))
        if found:
            return found[0], "bundled with Playwright"
    for found in sorted(driver.rglob("ffmpeg*")):
        if found.is_file():
            return found, "bundled with Playwright"
    sys.exit("no ffmpeg: not on PATH and none bundled with Playwright. "
             "Install one (winget install Gyan.FFmpeg) and rerun.")


def wait_for_app(url, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except OSError:
            time.sleep(0.5)
    sys.exit(f"app never came up on {url}")


def _preamble(page):
    """Clear the pending kickoff so the fixture's own geometry is what shows.

    A fresh match is legitimately waiting on a kickoff, which snaps the start to
    the centre spot and force-KICKs segment 0. S starts the possession from a
    scrum instead; a scrum is awarded against the carrier, so Z hands it back to
    home. Both are real keys a real user presses - no state is being staged.

    Not used with --kickoff, which wants that pending kickoff.
    """
    for key in LIVE_TRACE_KEYS:
        page.keyboard.press(key)
        page.wait_for_timeout(120)


# centre spot -> deep into the away half. The clock reads 00:00 and the match
# state is a pending kickoff, so the app snaps the press to the centre spot and
# force-KICKs the chain whatever the geometry says - the laws settle it.
#
# 0.8s, not the 0.55s a kick fixture uses: at the ~30Hz the round trip sustains,
# a 0.55s leg is only 17 points, and the tail of it bunches. Never wobbled
# either - see record(). Both together were splitting the kick into KICK-PASS in
# the browser while classifying clean offline, which is a sampling artefact
# rather than anything the recognizer got wrong.
KICKOFF = Scenario(name="kickoff", waypoints=((60, 35), (92, 42)),
                   durations=(0.8,), expect={"actions": ["KICK"]})


def translated(sc, origin):
    """The fixture's shape and pace, moved to start where the ball was taken.

    The receiving team's press start-snaps to the origin mark the kickoff left,
    so the fixture has to be positioned there or the snap records the gap as
    real movement. Translation preserves every leg vector and duration, so it
    is still the fixture's possession, just played where the kick landed.
    """
    dx = origin[0] - sc.waypoints[0][0]
    dy = origin[1] - sc.waypoints[0][1]
    return dataclasses.replace(
        sc, waypoints=tuple((x + dx, y + dy) for x, y in sc.waypoints))


def _sines(rng, n, amp, lo_hz, hi_hz):
    """n sine components, random amplitude/frequency/phase -> f(t) -> offset."""
    parts = [(amp * rng.uniform(0.35, 1.0), rng.uniform(lo_hz, hi_hz),
              rng.uniform(0, 2 * math.pi)) for _ in range(n)]

    def value(t):
        return sum(a * math.sin(2 * math.pi * f * t + ph) for a, f, ph in parts)

    return value


def wobble_path(sc, hz, wobble_px, drift_px=5.0):
    """fixtures.noisy_path, plus the slow half of a hand that it leaves out.

    The corpus model is 5-9Hz tremor and one sine of pace variation per leg -
    deliberately, since anything under 4Hz "reads as deliberate heading change"
    and would be testing the noise rather than the recognizer. That is also why
    it looks tight and mechanical on camera: what makes a traced line read as
    human is the slow stuff the corpus is built to exclude.

    So tremor and corner rounding still come from noisy_path, and this adds
    what a camera needs on top:
      - meander: 3 sines per axis at 0.2-0.9Hz, ~1.4m, the drift of an arm
        that is not on rails
      - pace: timestamps rewarped by a slow speed multiplier that dips to a
        near-hesitation and recovers, instead of one tidy sine per leg

    Total duration is preserved, so the recording still runs at the fixture's
    own pace, and the seed is the scenario's, so a rerun wobbles identically.

    5px is the ceiling, and it is the meander that sets it, not the pace warp.
    A pass leg is a ~8m lateral flick over 0.45s, and drift of that order
    distorts it into a carry: swept against the corpus, 6px+ starts losing the
    PASS on mirrored_attack and phase_chain_5, surviving on some seeds and not
    others. Raise --drift past 5 and it is a coin toss the verifier will catch.
    """
    base = noisy_path(sc.waypoints, sc.durations, sc.seed,
                      hz=hz, wobble_px=wobble_px, speed_var=0.35)
    rng = random.Random(sc.seed ^ 0xB0BB1E)
    meander = [_sines(rng, 2, drift_px, 0.15, 0.5) for _ in range(2)]
    pace = _sines(rng, 2, 0.45, 0.12, 0.4)

    # anchor the meander at zero on the first point. The press start-snaps to
    # the origin mark, so a cursor that starts 1.4m off it has that offset
    # recorded as real backwards movement - which reads as a leading PASS and
    # gains the chain a segment. Your hand is where you clicked; the drift
    # builds from there.
    m0 = [meander[i](base[0].t) for i in range(2)]

    out, t_out, prev = [], base[0].t, base[0].t
    for p in base:
        # integrate dt / speed: slow patches stretch, quick ones compress, and
        # the clamp stops a deep dip from stalling the cursor outright
        speed = max(0.35, 1.0 + pace(p.t))
        t_out += (p.t - prev) / speed
        prev = p.t
        out.append((t_out, p.x + meander[0](p.t) - m0[0],
                    p.y + meander[1](p.t) - m0[1]))

    span_in = base[-1].t - base[0].t
    span_out = out[-1][0] - out[0][0]
    scale = span_in / span_out if span_out else 1.0   # keep the fixture's length
    return [((t - out[0][0]) * scale + base[0].t, x, y) for t, x, y in out]


def to_px(x_m, y_m):
    """Metre waypoint -> image pixel, the space fixtures.noisy_path works in.

    Fixture waypoints are IMAGE metres, not field metres: _trace_legs maps them
    with a bare `x_m * PX_PER_M` and no in-goal offset, so x=10 sits on the left
    try line. Adding the offset here would put the press 80px away from where
    the sampled path starts.
    """
    return x_m * config.PX_PER_M, y_m * config.PX_PER_M


def drag_scenario(page, sc, client_px, path=None):
    """One mousedown -> moves -> taps -> end. Returns (t_down, t_commit)."""
    page.mouse.move(*client_px(*to_px(*sc.waypoints[0])))
    t_down = time.perf_counter()
    page.mouse.down()
    taps, shifts = sorted(sc.taps), sorted(sc.shift)
    fired, shift_open = 0, None

    def pump(elapsed):
        """Fire the taps and Shift edges now due, at their recorded offsets."""
        nonlocal fired, shift_open
        while fired < len(taps) and taps[fired][0] <= elapsed:
            page.keyboard.press(taps[fired][1])
            fired += 1
        for i, (t0, t1) in enumerate(shifts):
            if shift_open is None and t0 <= elapsed < t1:
                page.keyboard.down("Shift")
                shift_open = i
            elif shift_open == i and elapsed >= t1:
                page.keyboard.up("Shift")
                shift_open = None

    if path:
        # the sampled path already carries its own pace curve, so each point is
        # played at its own timestamp rather than being re-interpolated
        for t, x_px, y_px in path:
            late = t - (time.perf_counter() - t_down)
            if late > 0:
                time.sleep(late)
            page.mouse.move(*client_px(x_px, y_px))
            pump(time.perf_counter() - t_down)
    else:
        for i, dur in enumerate(sc.durations):
            (ax, ay), (bx, by) = sc.waypoints[i], sc.waypoints[i + 1]
            t_leg = time.perf_counter()
            while True:
                # position is a function of elapsed wall-clock, not of a fixed
                # step count, so per-move overhead cannot distort the leg-to-leg
                # pace ratios the recognizer reads
                frac = min((time.perf_counter() - t_leg) / dur, 1.0)
                page.mouse.move(*client_px(*to_px(ax + (bx - ax) * frac,
                                                  ay + (by - ay) * frac)))
                pump(time.perf_counter() - t_down)
                if frac >= 1.0:
                    break
                time.sleep(MOVE_SLEEP)

    if shift_open is not None:
        page.keyboard.up("Shift")
    if sc.end == "a":
        page.keyboard.press("a")     # commits with the button still down
    t_commit = time.perf_counter()
    page.wait_for_timeout(int(LEAD_OUT_S * 1000))
    page.mouse.up()
    return t_down, t_commit


def verify(page, sc, svg_html):
    """The recorded trace must be the one the fixture says it is."""
    problems = []
    expected = sc.expect.get("actions")
    if expected:
        summary = page.locator(".q-notification__message").last   # newest chain
        text = summary.inner_text() if summary.count() else ""
        # exact field match, not a substring: "CARRY-PASS-CARRY-KICK" is a
        # substring of "PASS-CARRY-PASS-CARRY-KICK", so `in` passes a chain
        # that gained a whole extra segment
        got = next((f for f in (p.strip() for p in text.split("·"))
                    if f and all(w in ACTION_COLORS for w in f.split("-"))), "")
        want = "-".join(expected)
        if got != want:
            problems.append(f"classified {got or text!r}, expected {want}")
        for action in set(expected):
            if ACTION_COLORS[action] not in svg_html:
                problems.append(f"{action} colour {ACTION_COLORS[action]} "
                                "missing from the canvas")
    return problems


def record(sc, url, video_dir, cursor=True, path=None,
           kickoff=False, kickoff_path=None):
    """Drive the trace under video capture. Returns (webm, crop, trim fractions)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(video_dir),
            # defaults to an 800x800 fit box, silently downscaling the viewport
            record_video_size=VIEWPORT,
        )
        t_ctx = time.perf_counter()
        page = context.new_page()
        errors = []
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url)
        page.get_by_role("button", name="Start match").click()
        canvas = page.locator("img").first
        canvas.wait_for()
        box = canvas.bounding_box()
        scale = box["width"] / IMAGE_W

        def client_px(x_px, y_px):
            return box["x"] + x_px * scale, box["y"] + y_px * scale

        if cursor:
            page.evaluate(CURSOR_JS)
        if not kickoff:
            _preamble(page)  # before the lead-in, so the possession flip it
                             # causes settles off camera
        page.locator("button:has-text('play_arrow')").click()   # start the clock
        page.wait_for_timeout(900)

        t_first = None
        if kickoff:
            t_first, _ = drag_scenario(page, KICKOFF, client_px, kickoff_path)
            page.wait_for_timeout(1200)   # let the kick land and possession flip
        t_down, t_commit = drag_scenario(page, sc, client_px, path)
        page.wait_for_timeout(400)

        problems = verify(page, sc, page.locator("svg").first.inner_html())
        # re-measure: the commit grows the status text, and any reflow it causes
        # has to stay inside the crop
        after = canvas.bounding_box()
        bottom = max(box["y"] + box["height"], after["y"] + after["height"]) + 8
        crop = (min(VIEWPORT["width"], int(box["x"] * 2 + box["width"])),
                min(VIEWPORT["height"], int(bottom)))
        video = page.video
        t_end = time.perf_counter()
        context.close()            # the webm is only flushed on close
        webm = Path(video.path())
        browser.close()

    # capture runs from context creation to context close, so a frame index maps
    # onto wall-clock without having to assume Playwright's capture rate
    span = t_end - t_ctx
    trim = (max(0.0, (t_first or t_down) - t_ctx - LEAD_IN_S),
            t_commit - t_ctx + LEAD_OUT_S)
    return webm, crop, span, trim, problems, errors


def to_frames(ffmpeg, webm, crop, width, frames_dir):
    """webm -> cropped, scaled PNGs. -2 keeps the height even for the scaler."""
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)
    subprocess.run(
        [str(ffmpeg), "-nostdin", "-loglevel", "error", "-i", str(webm),
         "-vf", f"crop={crop[0]}:{crop[1]}:0:0,scale={width}:-2",
         str(frames_dir / "%05d.png")],
        check=True)
    return sorted(frames_dir.glob("*.png"))


def _palette(frame):
    """One shared palette for the run, with the action colours forced into it.

    An adaptive palette allocates by pixel population, and VP8 leaves the grass
    as thousands of near-identical greens - so the ~800 pixels of traced line
    lose every time, and #ffd54f comes out of the quantizer as a washed (231,
    209, 157). Stamping swatches into the palette SOURCE (never into an output
    frame) buys those colours an entry each. This is what palettegen would have
    done for free, had the bundled ffmpeg shipped it.
    """
    src = Image.open(frame).convert("RGB")
    swatch = 40
    forced = [*ACTION_COLORS.values(), "#ffffff", "#333333"]
    for i, color in enumerate(forced):
        src.paste(ImageColor.getrgb(color),
                  (i * swatch, 0, (i + 1) * swatch, swatch))
    return src.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)


def to_gif(frames, fps, out):
    """Assemble the GIF on the shared palette, undithered.

    Dithering a 4px line against grass blends it back into the noise it was
    just rescued from, so the segments snap to their nearest palette entry.
    """
    palette = _palette(frames[-1])
    images = [Image.open(f).convert("RGB").quantize(
                  palette=palette, dither=Image.Dither.NONE)
              for f in frames]
    out.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(out, save_all=True, append_images=images[1:],
                   duration=round(1000 / fps), loop=0, optimize=True)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixture", default="carry_pass_carry_kick",
                    choices=sorted(SCENARIOS))
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--width", type=int, default=800)
    ap.add_argument("--out", type=Path, default=OUT_GIF)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--no-cursor", dest="cursor", action="store_false",
                    help="omit the drawn pointer (Playwright records none)")
    ap.add_argument("--wobble", nargs="?", type=float, const=3.0, default=None,
                    metavar="PX",
                    help="trace with the corpus hand model instead of straight "
                         "legs; optional tremor amplitude in px (default 3.0)")
    ap.add_argument("--hz", type=int, default=30,
                    help="sample rate for --wobble; the round-trip sustains ~30")
    ap.add_argument("--drift", type=float, default=5.0, metavar="PX",
                    help="slow meander amplitude for --wobble (default 5px; "
                         "above that it starts eating short PASS legs)")
    ap.add_argument("--kickoff", action="store_true",
                    help="open with the match's own kickoff from the centre spot, "
                         "then play the fixture back the other way from where it "
                         "landed (pair with a mirrored fixture)")
    args = ap.parse_args()

    sc = SCENARIOS[args.fixture]
    if args.kickoff:
        sc = translated(sc, KICKOFF.waypoints[-1])   # start where the kick landed

    def wobbled(scenario):
        return (wobble_path(scenario, args.hz, args.wobble, args.drift)
                if args.wobble else None)

    # the kickoff is deliberately never wobbled: a 0.8s flick is not a stroke a
    # hand meanders through, and drift on that few samples bends its tail into a
    # phantom backwards PASS
    path, kickoff_path = wobbled(sc), None
    ffmpeg, source = find_ffmpeg()
    print(f"ffmpeg: {ffmpeg} ({source})")
    if path:
        print(f"hand model: {len(path)} points, {args.wobble}px tremor "
              f"at {args.hz}Hz, seed {sc.seed}")
    if args.kickoff:
        print(f"kickoff {KICKOFF.waypoints[0]} -> {KICKOFF.waypoints[-1]}, "
              f"then {args.fixture} from there")
    url = f"http://127.0.0.1:{args.port}/"     # no ?dev=1: the drawer is not in shot
    SCRATCH.mkdir(parents=True, exist_ok=True)

    app = subprocess.Popen([sys.executable, "-m", "tracer.app", str(args.port)],
                           cwd=str(REPO))
    try:
        wait_for_app(url)
        webm, crop, span, trim, problems, errors = record(
            sc, url, SCRATCH / "video", cursor=args.cursor, path=path,
            kickoff=args.kickoff, kickoff_path=kickoff_path)
    finally:
        app.terminate()

    print(f"recorded {webm} ({webm.stat().st_size / 1e6:.1f} MB), crop {crop}")
    if errors:
        print(f"console errors: {errors}")

    frames = to_frames(ffmpeg, webm, crop, args.width, SCRATCH / "frames")
    src_fps = len(frames) / span
    lo, hi = (min(len(frames), max(0, round(t * src_fps))) for t in trim)
    # no fps filter in the bundled build, so decimate here - against the rate
    # actually captured, measured off the recording, not an assumed 25
    every = max(1, round(src_fps / args.fps))
    kept = frames[lo:hi:every]
    print(f"frames: {len(frames)} at {src_fps:.1f}fps -> {len(kept)} kept "
          f"(every {every}, ~{src_fps / every:.1f}fps, "
          f"{trim[1] - trim[0]:.1f}s of drag)")

    gif = to_gif(kept, src_fps / every, args.out)
    size_mb = gif.stat().st_size / 1e6
    print(f"\nwrote {gif} ({size_mb:.1f} MB, {len(kept)} frames)")
    if problems:
        print("\nTRACE DID NOT VERIFY:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print(f"verified: {sc.expect.get('actions')}")


if __name__ == "__main__":
    main()
