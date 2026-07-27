# Tuning the line recognizer

How to adapt the parameters that decide what a traced line *is*. Both
decision layers are **evidence-scored**: every decision is a weighted sum of
named features, every weight a plain number in [`config.py`](config.py),
every score breakdown visible in the dev panel. The logic lives in
[`segmentation.py`](segmentation.py) + [`features.py`](features.py); tuning
never requires touching either.

**Pace-invariance is the load-bearing property.** The line is read from its
geometry, never its drawing speed. Mechanically: the path is **resampled to
uniform arc-length spacing** (`RESAMPLE_STEP_M`) before anything else, so
point density is identical whether you trace fast or slow; all windows are
measured in **metres of traced path**, not milliseconds; and no feature uses
absolute speed. The same shape yields the same actions at any pace — pinned
by `tests/test_pace_invariance.py`. Don't reintroduce a millisecond or m/s
constant into the recognizer; it silently breaks this.

## The two decision layers

**Layer 1 — boundary detection** (where does one action end?). Each interior
point of the resampled path gets heading-change (`angle`) and speed-change
(`ratio`) measurements from `HEADING_WINDOW_M` (arc-length) velocity windows.
Evidence is scored against **this path's own baselines** (median angle/ratio,
floored) — a wobbly hand raises the bar automatically:

```
score = W_BOUNDARY_ANGLE * tanh(max(0, angle - angle_base) / BOUNDARY_ANGLE_SCALE_DEG)
      + W_BOUNDARY_SPEED * tanh(max(0, ratio - ratio_base) / BOUNDARY_RATIO_SCALE)
boundary iff score >= BOUNDARY_ACCEPT
```

where `angle_base = max(BOUNDARY_ANGLE_FLOOR_DEG, median angle) * BOUNDARY_ANGLE_BASE_MULT`
(ratio analogous). Either evidence alone can clear the accept threshold.
Grouping (`BOUNDARY_GROUP_M`), end-drop and thinning (`MIN_SEGMENT_M`) are in
metres of path; the accidental-click reject (`MIN_MOVEMENT_PX`) is unchanged.
`BOUNDARY_ACCEPT = 0.75` sits mid-band (sweep 2026-07-20, 0.65-0.85 all-pass
across the corpus). The `angle`/`ratio` evidence is itself pace-invariant
(directions don't scale with pace; the ratio cancels it) — only the window
units and point density were pace-bound, which resampling + metre windows fix.

**Layer 2 — classification** (what is each segment?). Four named features
per segment ([`features.py`](features.py)), each squashed to roughly [-1, 1],
**purely spatial** — computed from point positions only, never timestamps.
The time taken to draw the line is not measured and never affects the class:

| Feature | What it measures | Evidence for |
|---|---|---|
| `backward` | net motion against attack direction (rectified, sharp) | PASS — the rugby-law signal |
| `lateral` | lateral movement, **minus `LATERAL_FWD_PENALTY` × forward gain** | PASS (square pass) |
| `dist` | net displacement magnitude (metres) | KICK — kicks travel far |
| `straight` | net displacement / path length | KICK (mild) |

**A pass cannot gain forward ground** (a forward pass is illegal), so forward
progress *vetoes* both PASS features: `backward` is rectified (0 unless the
segment loses ground) and `lateral` subtracts `LATERAL_FWD_PENALTY` metres of
forward gain per lateral metre. A forward-and-sideways run (arc, cut, diagonal)
therefore scores **CARRY**, never PASS — this is the fix for the reported
"forward movement classed as a pass" bug. Raising `LATERAL_FWD_PENALTY` makes
the veto stricter.

Per class: `score = B_c + Σ W_c_FEATURE * feature`; **CARRY is the fixed
reference class** (score 0 — no constants). Softmax gives probabilities;
argmax wins (CARRY wins ties); `confidence = top prob - second prob` (dev
panel only).

> **Read `confidence` as a diagnostic, never as certainty.** Because CARRY
> scores a flat 0, a textbook carry wins only by PASS's bias (`B_PASS = -0.2`)
> and reports a 0.09 margin, while a genuinely borderline 30m stroke reports
> 0.138. The number tracks the bias constant, not doubt, so it ranks the
> safest calls below the ambiguous ones. Shading the canvas by it was tried
> and removed for exactly this reason. It is useful only next to the feature
> table that explains where the score came from.
 **KICK is geometry-only**: `W_KICK_DIST` dominates (distance is
the necessary signal), `straight` modulates. The kick threshold sits ~27m
(`B_KICK`/`W_KICK_DIST`/`F_DIST_SCALE_M`); 20-30m strokes are ambiguous and
lean **CARRY** (a false kick wrongly flips possession — the K hint or Review
promotes a real short kick). Attack direction flips after every KICK; a K/P/R
hint that changes a KICK call does **not** re-flip downstream attack direction
(taps run after geometry).

**Boundary detection** still uses the heading-change *and* a within-trace
speed-*ratio* (relative acceleration) to find where actions change — the ratio
is pace-invariant (it cancels a global pace change) and detection-only; it
never reaches the classifier. It is needed because a carry→kick transition
often has no heading change, only a speed change. Classification itself reads
zero timing.

## Symptom -> knob

| Symptom | Likely fix |
|---|---|
| **Corner not detected (two actions read as one)** | Lower `MIN_SEGMENT_M` (it drops boundaries closer than this in metres) and/or lower `BOUNDARY_ACCEPT` — the report's **near-miss** lines show what the missed corner scored |
| One action splits into phantom segments | Raise `BOUNDARY_ACCEPT`; accepted candidates show their score in the report |
| Double boundaries at one turn | Raise `BOUNDARY_GROUP_M` |
| **Forward movement read as a PASS** | Raise `LATERAL_FWD_PENALTY` so forward gain vetoes lateral harder (should never happen — forward strokes are CARRY by construction); check the segment's `fwd` in the report is actually positive |
| Kicks read as carries | Segment's score table: if `dist` is low the stroke is short for a kick — lower `F_DIST_SCALE_M` / raise `W_KICK_DIST` / raise `B_KICK` toward 0; a genuinely short kick needs the K hint |
| Carries read as kicks | Lower `B_KICK` (more negative) or raise `F_DIST_SCALE_M` so the kick distance bar sits higher |
| Flat/square passes read as carries | Raise `W_PASS_LATERAL`, lower `F_LAT_SCALE_M` (sharper), or lower `LATERAL_FWD_PENALTY` (weaker forward veto) |
| Crabbing forward runs read as passes | Raise `LATERAL_FWD_PENALTY` or lower `W_PASS_LATERAL` |
| Driven-back carries read as passes | Add CARRY-favoring evidence via **negative** PASS weight on `straight` (a tackle wiggle isn't straight) — or let `python -m tracer.fit` find it once such traces are promoted |
| Short legitimate traces vanish | Lower `MIN_MOVEMENT_PX` |
| Same shape classifies differently at different speeds | A pace-invariance regression — a time/speed term crept into classification, or a window is point-count not metres. Run `test_pace_invariance.py` |
| Everything after one segment wrong | Marginal KICK call flipped attack direction — the score table shows its confidence |

## The tuning loop

1. **Capture with evidence** — `python -m tracer.app 8080 dev`. The drawer
   shows, per segment, every feature's squashed value, weight, and
   contribution per class, plus scores/probs/confidence; per path, the
   boundary baselines and the top near-miss candidates. Misreads become
   numeric instructions ("the missed turn scored 0.68 against accept 0.75").
2. **Save the trace** — *Save last trace* snapshots raw inputs to
   `tracer/dev_traces/` (gitignored). Replay to confirm determinism.
3. **Promote to ground truth** — move to `tracer/tests/traces/`, add
   `"expect"` (vocabulary: `fixtures.check`). `test_corpus.py` picks it up;
   it also joins the **fit training set** automatically.
4. **Propose** — three tools, same philosophy (print, never write):
   - `python -m tracer.sweep` — grid over any config constants (edit `GRID`;
     weights sweep the same as thresholds). Ranked pass-count table.
   - `python -m tracer.fit` — softmax regression over every exact-actions
     corpus case (hint scenarios excluded), L2-anchored to your current
     values; prints a paste-ready weight block + before/after corpus pass
     counts + confusion. Weights barely move until real traces disagree with
     the synthetic corpus — that is correct behavior.
   - `python -m tracer.calibrate` — `fit` plus the corrections operators logged
     in the running app (see below). Same regression, same paste-ready block.
     Run it **pre-game** to fold yesterday's fixes into today's weights; an
     empty correction log makes it identical to `fit`.
5. **Decide and edit by hand** — paste/adjust in `config.py`.
6. **Verify** — `python -m pytest tracer/tests/`, especially
   `test_pace_invariance.py` (the same shape must classify identically across
   pace) and `test_corpus.py`. Then re-trace live in dev mode.

## The self-correction feedback loop

Steps 1–3 are the *manual* way to grow ground truth (capture → save → promote a
trace file). There is also an **automatic** path: every correction an operator
makes in the running app is logged to a local SQLite DB
(`tracer/feedback/corrections.db`, gitignored) by
[`feedback.py`](feedback.py). Logging is wired through `MatchState.on_correction`
(set in `app.py`); anything that doesn't set that callback — every test, every
fixture — writes nothing.

- **Clicking a drawn segment to re-cycle its action** (carry→pass→kick) is a
  labelled `(geometry, corrected-class)` pair — the highest-value signal, and
  the only kind `calibrate` **trains on**.
- K/P/R hints and Review-dialog edits (team, event type, delete) are logged too,
  for the audit record, but are **excluded from training**: a K/P/R hint can
  relabel a carry-shaped gesture and poison the geometric labels (the same
  reason `fit` excludes hint scenarios).

`python -m tracer.calibrate` reads that log — latest correction per segment
wins, features re-extracted from the stored points under the *current* config so
a pair survives later scale-tuning — adds the reclassifies to the fit corpus,
and proposes weights exactly as `fit` does (still print-only). The L2 anchor
keeps one or two corrections from over-swinging a weight; a systematic misread
corrected many times is what actually moves it. Full loop: operators fix
misreads live → corrections accrue → `calibrate` before the next game → paste
the block if the numbers convince you.

## Old -> new constants

| Retired | Replaced by |
|---|---|
| `ANGLE_THRESHOLD_DEG`, `SPEED_RATIO_THRESHOLD` | `BOUNDARY_*` baselines/scales + `BOUNDARY_ACCEPT` |
| `HEADING_WINDOW_MS`, `BOUNDARY_GROUP_MS`, `MIN_SEGMENT_MS` (milliseconds) | `HEADING_WINDOW_M`, `BOUNDARY_GROUP_M`, `MIN_SEGMENT_M` (metres of path) + `RESAMPLE_STEP_M` |
| `FAST_SPEED_MPS`, `SHORT_DURATION_MS`, `F_RELPACE_*`, `F_BURSTY_*` (any time/speed) | **gone** — kick is now `dist` + `straight` (geometry only) |
| features `fast`, `short`, `kickburst`, `relpace`, `bursty` | `dist`, `straight` — no feature reads time |
| `LATERAL_RATIO` (`|lat| > ratio·|fwd|`) | `LATERAL_FWD_PENALTY` (forward gain *vetoes* lateral: `|lat| − penalty·max(0,fwd)`) |

## Adapting beyond thresholds

- **New scenario**: `_sc(...)` in [`fixtures.py`](fixtures.py) — joins corpus,
  sweep, fit, and the pace fence automatically.
- **New feature** (e.g. curvature for spiral kicks): keep it pace-invariant
  (a distance or a ratio, never an absolute speed/time). Add its formula +
  `F_*` scale in `features.py`/`config.py`, append to `FEATURES`, add
  `W_PASS_*`/`W_KICK_*` zeros — extraction, scoring, dev table, sweep, and fit
  all pick it up by name with no further wiring.
- **New class** (e.g. OFFLOAD): add to `SCORED_CLASSES` + its `B_`/`W_`
  block; downstream consumers of `seg.action` must learn the new string
  (canvas color, events possession logic).
- **Different sport/scale**: `PX_PER_M` and pitch dims are the physical
  anchors; the metre-based windows and distance scales transfer with them.
