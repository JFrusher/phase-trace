# Tuning the line recognizer

How to adapt the parameters that decide what a traced line *is*. Both decision
layers are **evidence-scored**: every decision is a weighted sum of named
features, every weight a plain number in [`config.py`](config.py), every score
breakdown visible in the dev panel. The logic lives in
[`segmentation.py`](segmentation.py) and [`features.py`](features.py); tuning
never requires touching either.

**Pace-invariance is the load-bearing property.** The line is read from its
geometry, never its drawing speed. Three mechanisms enforce it: the path is
resampled to uniform arc-length spacing (`RESAMPLE_STEP_M`) before anything
else looks at it, so point density is identical whether you trace fast or slow;
all windows are measured in metres of traced path, not milliseconds; and no
feature uses absolute speed. `tests/test_pace_invariance.py` pins it. Don't
reintroduce a millisecond or m/s constant into the recognizer — it breaks this
silently.

## The two decision layers

**Layer 1 — boundary detection** (where does one action end?). Each interior
point of the resampled path gets heading-change (`angle`) and speed-change
(`ratio`) measurements from `HEADING_WINDOW_M` (arc-length) velocity windows.
Evidence is scored against **this path's own baselines** (median angle/ratio,
floored), so a wobbly hand raises its own bar:

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
across the corpus). The `angle`/`ratio` evidence is itself pace-invariant:
directions don't scale with pace, and the ratio cancels it. Only the window
units and point density were ever pace-bound, and resampling plus metre windows
fix both.

**Layer 2 — classification** (what is each segment?). Five named features per
segment ([`features.py`](features.py)), each squashed to roughly [-1, 1] and
computed from point positions only. The time taken to draw the line is not
measured and never affects the class:

| Feature | What it measures | Evidence for |
|---|---|---|
| `backward` | net motion against attack direction (rectified, sharp) | PASS, the rugby-law signal |
| `lateral` | lateral movement, **minus `LATERAL_FWD_PENALTY` × forward gain** | PASS (square pass) |
| `dist` | net displacement magnitude (metres) | KICK; kicks travel far |
| `straight` | net displacement / path length | KICK (mild) |
| `bent` | straightness *deficit* below `F_BENT_CENTER` (rectified) | vetoes KICK |

**A pass cannot gain forward ground** (a forward pass is illegal), so forward
progress *vetoes* both PASS features: `backward` is rectified (0 unless the
segment loses ground) and `lateral` subtracts `LATERAL_FWD_PENALTY` metres of
forward gain per lateral metre. A forward-and-sideways run (arc, cut, diagonal)
therefore scores CARRY, never PASS. That is the fix for the reported "forward
movement classed as a pass" bug; raising `LATERAL_FWD_PENALTY` makes the veto
stricter.

**`bent` is the mirror veto on the kick side.** Distance alone is a bad kick
detector: a 32 m running break clears the distance bar and reads as a kick,
which wrongly flips possession for the rest of the chain. A real kick is
near-straight, so `bent` stays at zero for genuine kicks *and* for straight long
carries, and only bites the bent-long case (`W_KICK_BENT = -6.0`).

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

**KICK is geometry-only.** `W_KICK_DIST` dominates because distance is the
necessary signal; `straight` modulates and `bent` vetoes. The kick threshold
sits ~27m (`B_KICK`/`W_KICK_DIST`/`F_DIST_SCALE_M`). Strokes of 20-30m are
ambiguous and lean CARRY, since a false kick wrongly flips possession; a real
short kick gets promoted by the K hint or in Review. Attack direction flips
after every KICK, but a K/P/R hint that changes a KICK call does **not** re-flip
downstream attack direction, because taps run after geometry.

**Boundary detection** uses the heading change *and* a within-trace speed
*ratio* (relative acceleration) to find where actions change. The ratio is
pace-invariant, since it cancels a global pace change, and it is detection-only:
it never reaches the classifier. It earns its place because a carry-to-kick
transition often has no heading change at all, only a speed change.
Classification itself reads zero timing.

## Symptom -> knob

| Symptom | Likely fix |
|---|---|
| **Corner not detected (two actions read as one)** | Lower `MIN_SEGMENT_M` (it drops boundaries closer than this in metres) and/or lower `BOUNDARY_ACCEPT`. The report's **near-miss** lines show what the missed corner scored |
| One action splits into phantom segments | Raise `BOUNDARY_ACCEPT`; accepted candidates show their score in the report |
| Double boundaries at one turn | Raise `BOUNDARY_GROUP_M` |
| **Forward movement read as a PASS** | Raise `LATERAL_FWD_PENALTY` so forward gain vetoes lateral harder. This should not happen at all — forward strokes are CARRY by construction — so first check the segment's `fwd` in the report is actually positive |
| Kicks read as carries | Check the segment's score table. If `dist` is low the stroke is short for a kick: lower `F_DIST_SCALE_M`, raise `W_KICK_DIST`, or raise `B_KICK` toward 0. A genuinely short kick needs the K hint |
| Long carries read as kicks | Check `bent`. A bent long run should be vetoed by `W_KICK_BENT`; if it isn't, raise `F_BENT_CENTER` so more of the stroke counts as bent |
| Straight carries read as kicks | Lower `B_KICK` (more negative) or raise `F_DIST_SCALE_M` so the kick distance bar sits higher. `bent` can't help here — a straight carry looks exactly like a kick |
| Flat/square passes read as carries | Raise `W_PASS_LATERAL`, lower `F_LAT_SCALE_M` (sharper), or lower `LATERAL_FWD_PENALTY` (weaker forward veto) |
| Crabbing forward runs read as passes | Raise `LATERAL_FWD_PENALTY` or lower `W_PASS_LATERAL` |
| Driven-back carries read as passes | Add CARRY-favouring evidence via a **negative** PASS weight on `straight` (a tackle wiggle isn't straight), or let `python -m tracer.fit` find it once such traces are promoted |
| Short legitimate traces vanish | Lower `MIN_MOVEMENT_PX` |
| Same shape classifies differently at different speeds | A pace-invariance regression: a time/speed term crept into classification, or a window is point-count rather than metres. Run `test_pace_invariance.py` |
| Everything after one segment wrong | A marginal KICK call flipped attack direction. The score table shows its confidence |

## The tuning loop

1. **Capture with evidence.** `python -m tracer.app 8080 dev`. The drawer shows,
   per segment, every feature's squashed value, weight and contribution per
   class, plus scores, probabilities and confidence; per path, it shows the
   boundary baselines and the top near-miss candidates. A misread becomes a
   numeric instruction: "the missed turn scored 0.68 against accept 0.75".
2. **Save the trace.** *Save last trace* snapshots raw inputs to
   `tracer/dev_traces/` (gitignored). Replay to confirm determinism.
3. **Promote to ground truth.** Move the file to `tracer/tests/traces/` and add
   an `"expect"` key (vocabulary in `fixtures.check`). `test_corpus.py` picks it
   up, and it joins the fit training set automatically.
4. **Propose.** Three tools, all print-only:
   - `python -m tracer.sweep` grids over any config constants (edit `GRID`;
     weights sweep the same as thresholds) and prints a ranked pass-count table.
   - `python -m tracer.fit` runs softmax regression over every exact-actions
     corpus case (hint scenarios excluded), L2-anchored to your current values.
     It prints a paste-ready weight block, before/after corpus pass counts, and
     a confusion matrix. Weights barely move until real traces disagree with the
     synthetic corpus; that is the anchor working, not a broken fit.
   - `python -m tracer.calibrate` is `fit` plus the corrections operators logged
     in the running app (see below). Same regression, same paste-ready block.
     Run it pre-game to fold yesterday's fixes into today's weights. An empty
     correction log makes it identical to `fit`.
5. **Decide and edit by hand.** Paste or adjust in `config.py`.
6. **Verify.** `python -m pytest tracer/tests/`, especially
   `test_pace_invariance.py` and `test_corpus.py`. Then re-trace live in dev
   mode.

## The self-correction feedback loop

Steps 1–3 are the manual way to grow ground truth: capture, save, promote a
trace file. There is also an automatic path. Every correction an operator makes
in the running app is logged to a local SQLite DB
(`tracer/feedback/corrections.db`, gitignored) by [`feedback.py`](feedback.py).
Logging is wired through `MatchState.on_correction`, set in `app.py`. Anything
that doesn't set that callback — every test, every fixture — writes nothing.

- **Clicking a drawn segment to re-cycle its action** (carry → pass → kick)
  produces a labelled `(geometry, corrected-class)` pair. That is the
  highest-value signal and the only kind `calibrate` trains on.
- K/P/R hints and Review-dialog edits (team, event type, delete) are logged for
  the audit record but excluded from training. A K/P/R hint can relabel a
  carry-shaped gesture, which poisons the geometric labels — the same reason
  `fit` excludes hint scenarios.

`python -m tracer.calibrate` reads that log, keeps the latest correction per
segment, re-extracts features from the stored points under the *current* config
so a pair survives later scale-tuning, adds the reclassifies to the fit corpus,
and proposes weights exactly as `fit` does. Still print-only. The L2 anchor
keeps one or two corrections from over-swinging a weight; what moves a weight is
a systematic misread corrected many times. So: fix misreads live, let
corrections accrue, run `calibrate` before the next game, and paste the block if
the numbers convince you.

## Old -> new constants

| Retired | Replaced by |
|---|---|
| `ANGLE_THRESHOLD_DEG`, `SPEED_RATIO_THRESHOLD` | `BOUNDARY_*` baselines/scales + `BOUNDARY_ACCEPT` |
| `HEADING_WINDOW_MS`, `BOUNDARY_GROUP_MS`, `MIN_SEGMENT_MS` (milliseconds) | `HEADING_WINDOW_M`, `BOUNDARY_GROUP_M`, `MIN_SEGMENT_M` (metres of path) + `RESAMPLE_STEP_M` |
| `FAST_SPEED_MPS`, `SHORT_DURATION_MS`, `F_RELPACE_*`, `F_BURSTY_*` (any time/speed) | **gone**. Kick is `dist` + `straight` + `bent`, geometry only |
| features `fast`, `short`, `kickburst`, `relpace`, `bursty` | `dist`, `straight`, `bent`. No feature reads time |
| `LATERAL_RATIO` (`|lat| > ratio·|fwd|`) | `LATERAL_FWD_PENALTY` (forward gain *vetoes* lateral: `|lat| − penalty·max(0,fwd)`) |

## Adapting beyond thresholds

- **New scenario**: add a `_sc(...)` to [`fixtures.py`](fixtures.py). It joins
  the corpus, sweep, fit and the pace fence automatically.
- **New feature** (curvature for spiral kicks, say): keep it pace-invariant — a
  distance or a ratio, never an absolute speed or time. Add its formula and
  `F_*` scale in `features.py`/`config.py`, append it to `FEATURES`, and add
  `W_PASS_*`/`W_KICK_*` zeros. Extraction, scoring, the dev table, sweep and fit
  all pick it up by name with no further wiring.
- **New class** (OFFLOAD, say): add it to `SCORED_CLASSES` with its `B_`/`W_`
  block. Downstream consumers of `seg.action` have to learn the new string —
  canvas colour and the possession logic in `events.py`.
- **Different sport or scale**: `PX_PER_M` and the pitch dimensions are the
  physical anchors. The metre-based windows and distance scales transfer with
  them.
