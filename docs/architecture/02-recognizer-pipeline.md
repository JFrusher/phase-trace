# 2 · The recognizer pipeline

**Diagram:** [`../diagrams/recognizer-pipeline.drawio`](../diagrams/recognizer-pipeline.drawio)
*(one page, three horizontal layers)*

**Source:** [`../../tracer/segmentation.py`](../../tracer/segmentation.py),
[`../../tracer/features.py`](../../tracer/features.py),
[`../../tracer/config.py`](../../tracer/config.py)

---

## The problem

You hold the button down and follow the ball for a whole possession. Pass, run, pass, tackle is one
unbroken line. The software has to answer two questions from that line alone:

1. Where does one action end and the next begin?
2. What kind of action was each one?

Nothing else in the app is allowed to be as clever as this module, and `segmentation.py`'s own
docstring calls it "the highest-risk module". It's pure — no NiceGUI import anywhere in it or in
`features.py` — which is the only reason it's testable at the volume it needs to be.

## The constraint that shapes everything: pace invariance

The recognizer reads **shape, never speed**. Not "mostly shape". Timestamps are carried through the
pipeline and used for exactly one thing — correlating keyboard taps to segments in Layer 3 — and
never for classification.

This was deliberate. You should be able to trace off paused or scrubbed video, or live, or as a
quick after-the-fact sketch, and get the same answer. The moment classification reads velocity,
"trace it slowly to get it right" becomes real advice, and the tool becomes a thing you have to be
good at rather than a thing that works.

Two mechanisms enforce it:

- **`_resample()`** re-spaces points uniformly by arc length (`RESAMPLE_STEP_M = 0.5`) before
  anything else looks at them. Fixed-rate pointer sampling puts more points per metre when you draw
  slowly; after resampling, point density is identical however fast you drew. Timestamps are
  linearly interpolated, so each part keeps its true duration for Layer 3.
- **Every window is measured in metres of traced path**, not milliseconds or point counts —
  `HEADING_WINDOW_M`, `BOUNDARY_GROUP_M`, `MIN_SEGMENT_M`.

[`tests/test_pace_invariance.py`](../../tracer/tests/test_pace_invariance.py) is the fence around
this. It exists because the property is easy to break by accident and impossible to notice by hand.

## Layer 1 — where are the boundaries?

The insight here is that there's no universal threshold for "that was a sharp turn". A steady hand
and a shaky hand produce completely different angle distributions, and a fixed cutoff either
fragments the shaky one into noise or misses the steady one's real corners.

So the baseline is **the path's own median**, floored:

```
angle_base = max(8°,  median angle) × 2.0
ratio_base = max(1.2, median speed ratio) × 1.5
```

A wobbly trace raises its own bar. A clean one lowers it.

Evidence is then two independent signals summed, each squashed so neither can run away:

```
score = tanh(max(0, angle − angle_base) / 45°) + tanh(max(0, ratio − ratio_base) / 1.0)
```

Either signal alone can clear `BOUNDARY_ACCEPT = 0.75`. A hard direction change with no pace change
is a boundary; so is an abrupt speed change on a straight line. That's correct — a flat pass out
the back changes direction, a kick from a standing start changes pace.

Surviving candidates are then thinned three ways, all in metres of path:

- **Group** anything within `BOUNDARY_GROUP_M = 1.5` and keep the strongest — one physical corner
  produces a run of adjacent high-scoring points, not one.
- **Drop** anything within `MIN_SEGMENT_M = 4.0` of either end. A boundary two metres in doesn't
  describe an action, it describes the press.
- **Thin** to `MIN_SEGMENT_M` spacing, keeping the stronger of any close pair.

Every drop writes a human-readable line into `boundary_notes`, which is why the dev drawer can tell
you *why* your corner was missed rather than just that it was.

### The rejection path

Before any of this, two guards: fewer than three points, or net displacement below
`MIN_MOVEMENT_PX = 6`, and the chain is rejected outright with no commit. That's an accidental
click, and it's the answer to "why did my trace disappear" — the dev drawer logs rejected chains
too.

## Layer 2 — what kind of action was it?

Five features per slice, each `tanh`-squashed, most rectified so that absence of evidence is 0
rather than negative:

| Feature | Reads | Evidence for |
|---|---|---|
| `backward` | negative forward progress along the attack axis | PASS |
| `lateral` | across-pitch displacement, **minus 3 m per forward metre** | PASS |
| `straight` | net ÷ path length, centred at 0.85 | KICK |
| `dist` | net displacement, scale 28 m | KICK |
| `bent` | rectified straightness *deficit* below 0.90 | vetoes KICK |

Two of these encode rugby law directly rather than statistics.

**`lateral`'s forward penalty** exists because *a forward pass is illegal*. So forward progress is
positive proof it wasn't a pass, and each forward metre cancels three metres of lateral evidence.
That's not a tuned coefficient standing in for a fuzzy correlation; it's a rule with a hard edge,
and `F_BACK_SCALE_M = 0.5` makes `backward` near-step-shaped at zero for the same reason.

**`bent`** exists because distance alone is a bad kick detector. A 32 m running break is long, and
without a veto it clears the distance bias and reads as a kick — which would wrongly flip
possession for the rest of the chain. A real kick is near-straight (~0.95+), so `bent` stays at
zero for genuine kicks *and* for straight long carries, and only bites the bent-long case.

Scoring is a per-class linear sum with **CARRY as a fixed reference class scoring 0**:

```
score(CARRY) = 0
score(PASS)  = B_PASS + Σ w_PASS,f · f
score(KICK)  = B_KICK + Σ w_KICK,f · f
```

PASS and KICK scores therefore read as *evidence against the carry default*, and `argmax` with ties
going to CARRY means ambiguity always lands on the safest answer. `B_KICK = −6.4` puts the
geometric kick threshold at roughly 27 m: shorter strokes stay CARRY, and a genuinely short kick is
promoted by a `K` tap or a click, not by lowering the bar for everything.

### Confidence is a diagnostic, not a certainty

`confidence = top probability − second`. It is deliberately *not* used to shade the drawn line, and
[`canvas.py`](../../tracer/canvas.py) carries a comment explaining why: a textbook carry wins only
by PASS's small `−0.2` bias and scores ~0.09, while a genuinely borderline 25–30 m stroke scores
higher. The margin measures the bias constant, not doubt. Shading by it would mark the safest calls
as the least certain.

It is used for one thing: `KICK_FLIP_MIN_CONF = 0.05`, below which a *geometric* kick doesn't flip
attack direction. Kept low on purpose — a genuine 30 m kick only scores ~0.14 by design, so an
aggressive gate would suppress real kicks. The phantom-kick case is stopped upstream by
`W_KICK_BENT` instead.

### Where the laws override the geometry

If `force_first` is set, the first slice is relabelled `KICK` regardless of what it looked like.
This covers kickoffs, restarts, 22 drop-outs, and penalties taken to touch or at goal — all cases
where the law settles it before the trace exists.

It's applied **inside** the classification loop, not patched on afterwards. That matters: a KICK
flips attack direction, and every segment after it must be classified in the flipped frame. Patching
the label on at the end would leave the downstream segments classified against the wrong frame,
and a receiver's onward carry would read as "backward, therefore a pass".

## Layer 3 — keyboard annotations

`apply_taps()` runs after classification and follows one rule absolutely: **taps never move a
boundary.** They relabel, flag and attribute. This keeps segmentation deterministic on the geometry
alone, and means a mistimed tap degrades one label rather than restructuring the chain.

- `K` / `P` / `R` relabel the segment under the cursor. `TYPE_HINT_GRACE_MS = 250` catches the tap
  that lands just after the segment ended, which is when you actually notice.
- `L` flags a linebreak, but only on a CARRY — a pass can't break the line.
- **Digits** group into one number within `DIGIT_BURST_MS = 400`. The nearest action boundary picks
  the segment and the role: tapped just *before* a boundary means whoever ended the last action,
  just *after* means whoever starts the next.
- **Shift held** over a PASS marks it intercepted, which splits the chain and hands the rest to the
  other team.

## The dev drawer is not optional infrastructure

Run `python -m tracer.app 8080 dev` (or `?dev=1`). The drawer logs one report per chain — including
rejected ones — with path stats, the boundary baselines, every candidate's score, the top near-miss
rejects, a per-segment feature-contribution table, and every tap-correlation decision. The canvas
draws a white dot at each picked boundary.

A recognizer with hand-set thresholds that can't explain itself is untunable, and the whole
calibration loop on page 6 depends on being able to see what it saw.

## Trade-offs

**Hand-set weights, not learned ones.** Every weight is a flat constant, chosen to encode a
cascade of rules a human can argue with. `tracer.fit` can propose learned values, but it
L2-regularises toward the current hand-set numbers precisely so the encoding survives unless the
data actively disagrees.

**Synthetic calibration.** These thresholds are tuned against 39 synthetic scenarios plus the
pace-invariance fence — not against a real match. Nobody has traced live footage end to end. The
numbers most likely to move are `BOUNDARY_ACCEPT` and the ~27 m kick threshold. Page 6 covers the
loop for fixing that.

**No hierarchical segmentation.** One flat pass over the path. A possession with a genuinely nested
structure (a chip-and-chase regather, where the same team kicks to itself) isn't representable —
it's on the known-gaps list in [`tracer/README.md`](../../tracer/README.md), not an oversight.
