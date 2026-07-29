# 6 · Calibration loop

**Diagram:** [`../diagrams/calibration-loop.drawio`](../diagrams/calibration-loop.drawio)
*(one page: live corrections · dev capture · the three read-only tools and the human gate)*

**Source:** [`../../tracer/feedback.py`](../../tracer/feedback.py),
[`../../tracer/sweep.py`](../../tracer/sweep.py),
[`../../tracer/fit.py`](../../tracer/fit.py),
[`../../tracer/calibrate.py`](../../tracer/calibrate.py),
[`../../tracer/fixtures.py`](../../tracer/fixtures.py)

**Procedure:** [`../../tracer/TUNING.md`](../../tracer/TUNING.md) has the symptom→parameter
diagnosis table. This page is about the shape of the loop, not the recipe.

---

## The problem this solves

Page 2 described a recognizer built entirely from hand-set constants: `BOUNDARY_ACCEPT = 0.75`,
`B_KICK = −6.4`, `MIN_SEGMENT_M = 4.0`, and about thirty more. Every one is a judgement encoded as a
number.

Two things follow. Those numbers are wrong in ways nobody has discovered yet, because they were
tuned against synthetic input rather than a real match. And when they're wrong, the person who finds
out is an analyst mid-match watching a carry get called a kick, so the fix has to start from what
*they* saw.

The loop therefore has two entry points, and they meet in one corpus.

## Entry point 1 — correct it live, it logs itself

Click a misread segment. `reclassify_segment()` cycles its action and re-commits (page 3). On the
way through, `_log_correction()` fires `on_correction(payload)` carrying:

- the traced **points** and the `attack_dir` frame they were classified in
- the squashed **features** at the time
- **context**: per-class scores, softmax probabilities, confidence, minute, team

`app.py` wires that callback to `feedback.log_correction`, which writes one row to a local SQLite
database at `tracer/feedback/corrections.db` (gitignored). Pure stdlib; nothing in `feedback.py`
imports the UI, and a caller that never wires the callback writes nothing. That's why the entire
test suite and every fixture run leave the database untouched.

### Only reclassifies train weights

Four kinds get logged (`reclassify`, `hint`, and `team`/`type`/`delete` from the Review dialog), but
`training_pairs()` selects **`kind='reclassify'` only**, taking the latest correction per
`(match, segment_id)`.

The reason is specific: a `K`/`P`/`R` hint can relabel a *carry-shaped gesture* as a kick. The
operator is asserting an intent the geometry doesn't show. That is the right thing for them to do
live and a poisoned label for a geometric classifier — feeding hints into the fit would teach it
that carry-shaped things are kicks. They're kept for the audit record and nothing else.

### Features are re-extracted, not replayed

`training_pairs()` stores the raw **points**, and re-runs `features.extract()` under the *current*
config when you calibrate. Stored features would go stale the moment someone changed
`F_DIST_SCALE_M`, and you'd be fitting weights against a feature space that no longer exists.

## Entry point 2 — capture it in dev mode, promote it to a test

For a misread you want permanently fenced rather than nudged:

1. Run `python -m tracer.app 8080 dev` and hit **Save last trace**, which snapshots the chain's raw
   inputs to `tracer/dev_traces/` (gitignored).
2. Replaying that file must reproduce the identical report. The pipeline is deterministic on
   identical points, and this is the check that it stays so.
3. Move it to `tracer/tests/traces/`, add an `"expect"` key, and `test_corpus.py` picks it up
   automatically as `trace:<name>`.

The `expect` vocabulary is whatever `fixtures.check()` understands: actions, teams, event types,
origins. A real misread becomes a permanent regression, which is a stronger outcome than a weight
nudge.

## The corpus

Three sources, one training set:

- **`fixtures.SCENARIOS`** — 39 synthetic scenarios. `noisy_path()` turns waypoint scripts in metres
  into human-ish pixel traces with speed variation, hand tremor, corner rounding and sampling
  jitter, deterministic per seed. The tremor is modelled at 5–9 Hz, which is physiological
  frequency: fast enough that the recognizer's heading windows average it out exactly as they do a
  real hand. Slower wobble would read as deliberate heading change, and the corpus would be testing
  the noise generator rather than the recognizer.
- **`tracer/tests/traces/`** — promoted real traces.
- **`corrections.db`** — the reclassify rows.

`fixtures.inject()` fires raw inputs through a real `MatchState` exactly as the live app would. All
logic takes `t` as a parameter rather than reading the wall clock, so instant injection is faithful
rather than a simulation.

## The three tools

| Tool | Tunes | Method |
|---|---|---|
| `python -m tracer.sweep` | segmentation thresholds | grid over `BOUNDARY_ACCEPT`, `MIN_SEGMENT_M`, `B_KICK`; prints a pass count per combination with the failing scenario names |
| `python -m tracer.fit` | classification weights | multinomial logistic regression over the fixture corpus |
| `python -m tracer.calibrate` | classification weights | the same fit, plus the logged reclassifies |

`fit.py` is the interesting one: a from-scratch softmax regression in pure stdlib. The corpus is
tiny, so closed-form gradients and batch gradient descent finish in milliseconds, and pulling in
scikit-learn would buy nothing.

Two design choices matter:

**CARRY is the fixed reference class**, matching `features.score()` exactly. The model being fitted
is the model being run.

**L2 regularisation is toward the *current config values*, not toward zero.** That's unusual and
deliberate. The hand-set weights encode a cascade of rules a human can defend, so the prior should
be "those rules are right" rather than "nothing is right", and proposals stay anchored unless the
data actively disagrees. On day one, when the labels match the cascade, weights barely move. That is
the anchor working. It earns its keep as misclassified real traces accumulate.

`fit.py` also excludes hint-tap scenarios (same poisoning argument as above) and any scenario whose
segment count disagrees with `expect`, since boundary errors are `sweep`'s problem rather than the
classifier's.

`calibrate.py` is thin: `fit.training_set() + feedback.training_pairs()`, then the same `fit.train`.
With an empty database its output is identical to `tracer.fit`, and it says so.

## The gate

**None of the three writes `config.py`.** All of them print a proposal and exit.

This is the centre of the design, and it's why the diagram draws a red diamond rather than an arrow.
Automatic tuning against a 39-scenario synthetic corpus would overfit confidently and silently, and
the failure mode — a recognizer that quietly got worse at the case you didn't have a fixture for —
is invisible until you're mid-match.

So: read the pass table, read the confusion matrix, read the proposed block, decide, edit by hand.
Then `python -m pytest -q`, where `test_corpus.py` replays the whole corpus at baseline config and
catches an edit that regressed something. CI runs the same on every push and pull request.

`tracer.sweep` stays out of CI. It's a tuning report that always exits 0, so running it there would
prove nothing, and `test_corpus.py` already gates the recognizer.

## Where calibration actually stands

The constants in `config.py` are tuned against the 39 synthetic scenarios plus the pace-invariance
fence. **Not against a real match.** Nobody has traced live footage end to end.

The numbers most likely to move:

- `BOUNDARY_ACCEPT`. The sweep at 2026-07-20 found 0.65–0.85 all passing, with genuine turns scoring
  ≥ 0.92 and release wobble ≤ 0.73 on the noisy corpus. 0.75 is the band centre: a reasonable
  default, not evidence of a sharp optimum.
- The ~27 m geometric kick threshold (`B_KICK`).
- `F_BENT_CENTER` and `W_KICK_BENT`, both set by hand to stop long bent runs reading as kicks, and
  both carrying a `ponytail:` comment saying to validate them against real traces before treating
  them as settled.
- The nine `origin_factor` weights (page 4), though those belong to the translator rather than the
  recognizer, and no tool here proposes them.

The infrastructure for fixing all of this exists and is wired end to end. What's missing is a traced
match.

## Trade-offs

**Local-only feedback.** The correction database is a gitignored file on the analyst's machine. No
telemetry, no upload, no shared model. The cost is that corrections don't pool across users; the
benefit is that traced positional data from someone's match never leaves their laptop by default.

**No online learning.** Corrections affect the *next* session, via a pre-game `calibrate` run, not
the current one. Weights shifting mid-match would make the tool's behaviour unreproducible: you
could no longer tell a recognizer change from a tracing change within one match.

**The corpus is synthetic-heavy.** 39 generated scenarios against zero promoted real traces today.
`noisy_path()` is a good model of a hand, but it is a model, and every threshold currently rests on
it. Promoting real traces is the highest-value contribution anyone could make to this codebase.
