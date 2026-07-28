# ROADMAP — tracer/ to a public PR

**Working document. Delete this file in the final commit before opening the PR.**

Target: one PR into `origin/master` (Jfrusher/phase-trace), read by a public
audience as a portfolio piece. Branch `feature/modular-input-framework` is
currently 10 commits ahead of `master`, clean fast-forward, 154 tests green.

The PR narrative is the arc: a keyboard-only React tagger hit its ceiling, was
replaced by a mouse-trace recognizer, and the abandoned tool stays archived in
`legacy/` as evidence of the judgement call. That story only lands if the
tracer has actually been used on a real match — so the proof artifact is a
momentum chart generated from a full 80-minute hand-traced game.

---

## Design principles

These are settled. Everything below implements them.

**1. Every inferred attribution renders as a chip; the chip's team badge is a
switch.** There are two teams, so any team attribution is one click from
correct. No modal, no confirm, no correction mode — the chip *is* the
correction UI.

**2. Set-piece type is never switchable.** Type is either geometrically
certain (a kick crossing the touchline is a lineout; a score is a restart) or
explicitly typed by the user (`S` scrum, `F` penalty). A lineout never needs to
become a scrum. This keeps every chip binary.

**3. Nothing blocks.** Choosers open pre-selected on the best guess. Ignore one
and keep tracing — that accepts the guess.

**4. Chips are DOM elements, not canvas hit-tests.** `ui.interactive_image`
reports mouse coordinates rather than element targets, so a clickable SVG chip
inside it is impossible. Chips render as absolutely-positioned NiceGUI elements
over the image inside a `relative` container. Real click handlers, no
hit-testing, no collision with `MatchState.mouse_down`.

**5. Only the live chip plus the last resolved one (ghosted) are drawn.** 130
possessions of accumulated markers is soup.

**6. The trace stays action-coloured.** Amber carry, blue pass, red kick. That
redraw is the recognizer's feedback channel and recolouring it by team destroys
it. Team identity lives on the chrome: scoreboard, possession chip, in-goal
tint, and a thin team-coloured underline beneath the trace.

**7. Context between chains is two nullable fields, not a state machine.**
`pending_start_reason` and `armed_next_action` on `MatchState`. No enum, no
transition table, nothing to get stuck in.

**8. The match clock is the ground truth for event minutes, and no attempt is
made to link it to real match time.** The operator starts and pauses it to stay
roughly with play; `minute` comes from it exactly as it already does. Trace
pace and match time are structurally unlinkable given the input model, so there
are no anchors, no interpolation, and no post-hoc minute entry. Chart x-axis
accuracy is therefore approximate by design — say so in the README limitations.

---

## Rugby laws the tool must respect

Recorded here because they are facts, not preferences, and each one changes
code:

- **A penalty kicked to touch retains the throw-in** for the kicking team. An
  open-play kick to touch gives the throw to the other team. Same geometry,
  opposite team inference — the difference is entirely the origin.
- **Kick to touch on the full.** From inside your own 22, the lineout is where
  the ball crossed the line (territory gained). From outside your own 22, the
  ball goes back to where it was kicked (territory denied). The tool cannot see
  a bounce, so it assumes on-the-full for kicks originating outside the 22 and
  makes the chip's *position* clickable to jump to the exit point.
- **After a score, the conceding team restarts and the scoring team receives.**
  `events.infer_next_possession` already returns the scorer, which is correct.

---

## Phase 0 — Pilot trace. No code.

Fifteen possessions from the real match footage, before anything is built. The
data gets thrown away; the point is discovering *unknown* problems, since the
known ones are already enumerated below.

**Taps during an active drag — VERIFIED 2026-07-21.** Playwright drove a real
`page.mouse.down()` → 40 moves → `press('a')` → `mouse.up()` sequence against
the running app: the chain committed on the `a` tap while the button was still
held, toast `England · CARRY · 14.3m`, zero console errors. This was the
assumption that would have voided the whole input model. It holds. Still worth
re-checking with a physical mouse and real Shift-holds during the pilot, since
synthetic events bypass some OS-level input paths.

Log every recognizer disagreement and every friction point into a triage table:
symptom, was it a threshold problem or a missing capability, how often.

**Exit:** a written triage list that reorders Phase 1.

---

## Phase 1 — Make an 80-minute session survivable

None of this is a feature. It is the difference between a full-match trace
being possible and being abandoned at minute 30.

### 1.1 Undo last chain

- `MatchState`: before `end_chain` mutates anything, snapshot
  `(len(events), possession, last_end_reason, pending_start_reason)` into
  `self._undo`. Single-slot — one level of undo is enough.
  <!-- ponytail: single-slot undo; make it a deque if the pilot shows multi-step regret -->
- `undo_last()`: truncate `events`, restore the snapshot, clear the canvas.
- `app.py`: a button plus `Ctrl+Z` via `e.modifiers` in the keyboard handler.
- New `tests/test_undo.py`: commit a chain, undo, assert event count and
  possession both restored.

### 1.2 Commit feedback

Currently a misread chain is only visible by opening the dev panel. `on_commit`
already fires on every commit — use it.

- `app.py`: `ui.notify` a one-line summary — `HOME · CARRY-PASS-KICK · 24m`.
- Summary builder next to `chain_to_events` in `events.py` so it is testable
  without NiceGUI.

### 1.3 Named sessions

`sessions/session.json` is a single slot; a second match clobbers the first.

- `autosave.py`: `save_session(d, path)`, slug derived from team names →
  `sessions/<home>_v_<away>.json`.
- `setup.py`: list existing sessions, resume offers the newest.

### 1.4 Surface low confidence

`Segment.confidence` is computed on every segment and shown only in the dev
panel. The tool knows when it is guessing and does not say so.

- `config.py`: `CONFIDENCE_DOTTED = 0.25` (margin below which a segment is
  drawn dotted).
- `canvas.py`: `render_segments` applies `stroke-dasharray` under that
  threshold.

**Exit:** an 80-minute session can be run start to finish, mistakes are
reversible, and misreads are visible in the moment.

---

## Phase 2 — Chain origin and the chip system — **DONE 2026-07-21**

Built and browser-verified. 212 tests green (from 154 at the branch head).
Two defects were found by the browser check that the unit tests could not see,
both now covered by regression tests:

1. **Re-classify duplicated events.** The click that re-classifies is itself a
   `mouse_down`, which overwrote the undo snapshot with the *post*-commit
   state before the handler ran, so the rewind left the committed chain in
   place and appended a second copy. Fixed with a separate `_precommit`
   snapshot taken inside `_commit_chain`. The same clobbering also lost a try
   tapped mid-chain, because `_chain_events_start` moved and
   `_scored_team_this_chain` could no longer find it.
2. **The chip covered the line it annotates**, swallowing the very clicks it
   was meant to leave available, and the new wrapper broke the pitch's
   responsive scaling (`max-width:100%` resolved against a wrapper sized by
   its own content, so the pitch overflowed the window). Chips now float above
   their mark and the wrapper carries the sizing.

Deviation from plan: the new scenarios went into `tests/test_origin.py` as
inference tests rather than into the `fixtures.py` corpus. The corpus exercises
*segmentation* of drawn shapes; origin inference is a separate layer and adding
it there would have tested the wrong thing.

Original plan follows.



The largest phase and the one that makes the momentum model rugby-literate.
Every possession currently begins from nowhere: `last_end_reason` is a derived
three-way guess, display-only, never exported.

### 2.1 Vocabulary

`config.py`:

```python
START_REASONS = ("kickoff", "restart", "drop_out_22", "scrum", "lineout",
                 "penalty", "turnover_open", "interception", "kick_return")
```

Free kicks are deliberately out — see non-goals.

The *weights* for these live in `translators/rugby_weights.json`, not here.
The tracer emits a `start_reason`; the translator owns what it is worth. That
separation is the repo's existing architecture and this must not blur it.

### 2.2 Inference

`events.infer_start_reason(prev_chain, scored_team, armed, cal)` returning
`(reason, team_key, marker_point)`:

| Condition | Reason | Team | Chip point |
|---|---|---|---|
| a restart-triggering score | `restart` | scoring team | halfway |
| `armed_next_action == "kick_to_touch"` | `lineout` | **kicking** team | mark per 2.4 |
| last segment KICK, path crosses touch | `lineout` | other team | mark per 2.4 |
| last segment KICK, stays in field | `kick_return` | receiving team | end point |
| a PASS was intercepted | `interception` | intercepting team | boundary point |
| `S` tapped | `scrum` | opponent of possessor | end point |
| `F` tapped | `penalty` | opponent of possessor | the mark |
| otherwise | `turnover_open` | other team | end point |

The `scrum` default assumes a knock-on by the team in possession, which is the
common case. Injury restarts, defenders' knock-ons and contested-kick knock-ons
are all the same chip with one click on the team badge.

The `turnover_open` fallback replaces the current hard-coded plain-end
assumption in `events.py:52` and is what fixes the penalty possession bug.

### 2.3 Touch detection

`geometry.py`: `crosses_touch(points) -> (bool, exit_point)`. Touch is
`y <= 0 or y >= IMAGE_H`.

**Risk to test early:** it is unverified whether `ui.interactive_image` reports
mouse coordinates once the cursor leaves the image bounds. If it clamps, the
fallback is treating a trace ending within `TOUCH_MARGIN_M` of an edge as out.
Establish this in Phase 0 if possible — it is cheap to check and 2.2 depends on
it.

### 2.4 On-the-full law

`geometry.py`: `lineout_mark(kick_start, exit_pt, attack_dir, cal)`.

If the kick originates outside the kicking team's own 22, the mark is at the
kick origin's x on the touchline; otherwise at the exit point. Needs a small
`own_22_x(attack_dir)` helper. The chip's position is clickable to toggle
between the two candidates for the bounced case.

Penalty kicks to touch bypass this entirely — the mark is always the exit
point and the kicking team throws in.

### 2.5 Penalty flow

- New key `F` = penalty awarded, defaulting to the opponent of the current
  possessor. Same `_other(self.possession)` pattern `sin_bin` already uses.
  (`N` stays penalty *goal scored*, `P` is taken by the pass hint.)
- New key `S` = scrum. Ends the chain if one is active, same as `A`.
- The penalty chip carries a four-option chooser, pre-selected on **kick to
  touch**: at goal / to touch / tap and go / scrum.
  - *to touch* → `armed_next_action = "kick_to_touch"`; the next stroke places
    a lineout chip with the kicking team throwing in.
  - *tap and go* → `pending_start_reason = "penalty"`, possession retained.
  - *scrum* → `pending_start_reason = "scrum"`, possession retained.
  - *at goal* → arms `N` (scored) or a miss.
- Emits a discrete `penalty_won` event, weighted like `turnover_won`.

### 2.6 Export shape

`chain_to_events` sets `start_reason` on the **first** sub-chain only.
Subsequent sub-chains inside one chain arose from an in-chain kick or
interception and their origin is already implied.

Also add `start_metres_from_line` alongside the existing
`end_metres_from_line`. Without it the origin factor is positionally blind and
an attacking lineout five metres out is indistinguishable from one on your own
line.

### 2.7 Momentum weighting

`rugby_weights.json` gains an `origin_factor` map; `rugby.py::_territory_weight`
multiplies by `origin_factor.get(start_reason, 1.0)`.

Starting values, to be tuned in Phase 5 — these are guesses and must be
labelled as such in the module docstring, the way the sin_bin judgement call
already is:

```
interception 1.30 · penalty 1.25 · lineout 1.15 · turnover_open 1.10
scrum 1.00 · kick_return 0.95 · restart 0.90 · kickoff 0.90 · drop_out_22 0.85
```

Set pieces get **no discrete weighted events** — a lineout is not itself threat
creation, it is context that modifies the threat of the possession it starts.
This is the same double-counting argument `rugby.py` already makes for
`sin_bin`. `penalty_won` is the exception because a penalty *is* a standalone
swing, exactly like `turnover_won`.

### 2.8 Kill the dead-data trap

`rugby_weights.json` has `"_default": 0.4`, which silently swallows any event
type the translator does not know. Add a new type and it exports, charts, and
means nothing.

Extend `tests/test_vocab_parity.py` to fail if any `START_REASONS` entry lacks
an `origin_factor`, or any `DISCRETE_EVENT_KEYS`/`CONVERSION_KEYS` value lacks
either a weight or an explicit marker-only declaration.

### 2.9 The chip component

New `tracer/chips.py`. One component reused for lineout, scrum, penalty,
restart and drop-out:

- Absolutely positioned inside a `relative` wrapper around the canvas.
- Team-coloured rounded chip, small icon plus label — `LINEOUT · HOME`.
- Click the team badge → flip team, fire `on_flip`.
- Click the position handle (lineout only) → toggle mark between the on-the-full
  candidates.
- The previous chip renders at reduced opacity and is not clickable.

### 2.10 Team colours — dependency of 2.9

- Two `ui.color_input` fields in `setup.py`, sensible defaults.
- `MatchState.team_colors`, persisted through `to_dict`/`from_dict`.
- Consumed by chips now; by the scoreboard and pitch in Phases 3 and 4.

### 2.11 Click a segment to re-classify

Same DOM-overlay pattern as 2.9, applied to the trace itself. The canvas only
ever draws the last committed chain, so the clickable region is naturally
bounded to it.

- Click a committed segment → cycle `CARRY → PASS → KICK`, re-run team
  assignment and re-emit that chain's events.
- Click versus drag is already discriminated by `MIN_MOVEMENT_PX = 6`, so
  starting a new trace on top of the old line still works: a drag traces, a
  click re-classifies.
- `K`/`P`/`R` hint keys and `TYPE_HINT_GRACE_MS` stay. Two paths to one
  outcome, deliberately — hints during the trace, clicks after it.
  <!-- ponytail: kept both on request; the hint tap-correlation path is the one to delete first if this ever needs simplifying -->

### 2.12 Fixtures

New scenarios in `fixtures.py`: `penalty_to_touch_retains`,
`kick_to_touch_on_the_full`, `kick_to_touch_from_own_22`, `scrum_from_knock_on`,
`restart_after_try`. Each asserts the resulting `start_reason` and team.

**Exit:** a penalty won and kicked to touch keeps the ball with the correct
team throwing in; every export carries an origin; the parity test makes dead
event types impossible.

---

## Phase 2.5 — Inference checkpoint. No code.

Re-trace the same fifteen pilot possessions against the new system. Count:
how many chips had the right team without a click, how many start reasons were
right.

Below roughly 80% correct, fix the inference before building anything on top of
it. Phases 3 and 4 are polish over this layer and polishing a wrong layer is
wasted work.

---

## Phase 3 — Scoring and discipline completeness — **DONE 2026-07-21**

Deviation: `sin_bin` was **not** renamed to `yellow_card`. A sin bin *is* the
yellow card, the existing name is the more precise one, and renaming would have
churned tests and the sample export for nothing. `red_card` was added alongside
it on `D`, and both are marker-only.

Also dropped: "Review gains an action re-classify". Events carry no action —
`phase_sequence` records metres and linebreaks, not carry/pass/kick — so there
is nothing at event level to re-classify, and the segment-level path already
exists on the canvas. Review instead gained the correction that *does* map to
the data: changing a score event's type, for the mis-tapped `T`-instead-of-`N`
that puts five points in the wrong column.

## Phase 4 — Pitch map and team identity — **DONE 2026-07-21**

Deviation: **the scale selector was cut.** The image already carries
`max-width:100%` and scales to fit the window; a selector would have duplicated
what CSS does while threading `px_per_m` through five modules. The calibration
test survives as insurance — it pins that every exported metre figure stays
exact at 6/8/10 px per metre, so the option remains cheap if a real session
wants it.

Corrected while here: the 22m lines were drawn dashed and are solid in the
laws; the 10m lines are the broken ones.

Also cut after seeing it rendered: on-pitch direction arrows. They sat in the
middle of the field of play, competing with the very traces the pitch exists to
show, and the status bar already carries a direction arrow. The in-goal areas
are tinted and labelled with the defending team instead — space that is never
traced on.

Original plan follows.

## Phase 3 — original plan

- `penalty_try` = 7 points in `config.POINTS`, new key `Y`, and it must **not**
  arm the conversion listener.
- Split `sin_bin` into `yellow_card` (`B`, existing) and `red_card` (`D`). Both
  stay marker-only in `rugby.py` — the existing double-counting rationale holds
  unchanged for reds.
- Scoreboard rebuilt: team-coloured chips at the size the number deserves,
  flashing briefly on change.
- `review.py` gains an action re-classify select per segment-derived event —
  the post-hoc path for anything the click-to-cycle on the canvas missed once
  the chain is no longer drawn.
- Parity test (2.8) covers all new types automatically.

---

## Phase 4 — Pitch map and team identity

You cannot judge a lineout's position on a pitch that does not draw the lineout
lines. `pitch.py` currently has try lines, halfway and two 22s.

- **Add:** 10m lines (dashed), 5m and 15m lines (short dashes running the
  pitch's length), goal posts at both try lines, halfway hash marks, and metre
  labels — `22 · 10 · H · 10 · 22`.
- In-goal areas tinted with the *defending* team's colour, so which way each
  side attacks reads without thinking.
- Direction arrows that flip with `halftime_flip`.
- Scale selector at 6 / 8 / 10 px per metre. `PitchCalibration` already takes
  `px_per_m` as a parameter, so this is a passthrough — but calibration must be
  re-verified at all three, since every metre figure in the export depends on
  it.

**Exit:** a stranger looking at a screenshot can tell who has the ball, which
way they are going, and roughly where on the pitch it is happening.

---

## Phase 5 — Full match and tuning

1. Trace the full 80 minutes, scrubbing and pausing freely. The recognizer is
   pace-invariant, so slow scrubbing costs nothing.
2. Every misbehaving trace: Save last trace in dev mode, promote to
   `tracer/tests/traces/` with an `"expect"` key.
3. `python -m tracer.sweep` and `python -m tracer.fit` over the enlarged corpus.
   Read the output, edit `config.py` by hand — neither tool writes.
4. Tune the Phase 2.7 `origin_factor` values against how the chart actually
   reads. These are the least defensible numbers in the repo until this happens.
5. Export and render:
   `python momentum.py examples/<match>.json momentum_<match>.png --sport rugby`

**Exit:** a real momentum chart from a real match, full corpus green, and
thresholds justified by real traces rather than synthetic fixtures.

**Contingency, currently unbudgeted:** if the full trace shows the recognizer is
simply too inaccurate on real hand-drawn paths, the answer is a post-hoc
segment correction pass in Review, not more threshold tuning. Decide at the
Phase 2.5 checkpoint whether this risk is live.

---

## Phase 6 — PR preparation

- `.github/workflows/tests.yml` — pytest on push and PR, badge in the root
  README. There is currently no CI at all.
- Three or four tests for `core/engine.py`: decay half-life, net-momentum sign
  flip, smoothing shape. The decay math is the repo's actual thesis and has
  zero coverage; all 154 tests live in `tracer/`.
- A short GIF of a trace becoming coloured segments. Nobody is going to
  `pip install` a NiceGUI app to see what this does.
- Root README rewritten: the real chart and the GIF as the headline, tracer
  promoted out of the bottom section.
- `tracer/README.md` and `TUNING.md` updated for the new vocabulary, chips, and
  origin factors. The Known MVP gaps list stays and stays honest.
- **Delete this file.**
- PR body carrying the arc: tagger → ceiling → tracer → real match.

---

## Deliberate non-goals

Documented so they read as decisions rather than omissions:

- **Advantage.** A period of advantage played is not representable and is not
  worth a state field.
- **Free kicks.** Rare enough that a scrum chip with a clicked team is close
  enough.
- **Rucks and mauls as counted events.** Phase play is already the
  `phase_sequence` abstraction; counting rucks would double-count it.
- **Squad rosters.** Digit taps stay free-form; typos are fixed in Review.
- **Live in-app momentum chart.** Chart generation stays the manual
  `momentum.py` step — that separation is the architecture's whole point.
- **Kick-to-self (chip and chase).** Still unrepresentable. Trace it as a carry.
- **Full-time / periods.** The halftime button covers the only direction change
  that matters.

---

## Risks

| Risk | Phase | Mitigation |
|---|---|---|
| Taps/Shift do not fire during an active mouse drag | 0 | Test it first. Failure voids the input model, not just this roadmap. |
| `interactive_image` clamps coordinates at its bounds, so touch detection cannot see the ball go out | 2.3 | Fall back to a `TOUCH_MARGIN_M` proximity test. Check in Phase 0. |
| Start-reason inference is wrong more often than right | 2.5 | The checkpoint exists precisely to catch this before Phases 3–4 build on it. |
| Recognizer too inaccurate on real hand traces | 5 | Post-hoc correction in Review. Unbudgeted — decide at 2.5. |
| Origin factors are unvalidated guesses | 2.7 | Labelled as judgement calls in the docstring, tuned in Phase 5, flagged in the README limitations the way the football model already is. |

---

## Honest cost

Phases 2 and 4 are each a real build. Phase 5 is hours of human tracing. This
is weeks of evenings, not a session.

**The cut, if it needs one:** 0 → 1 → 5 → 6. That still produces a real
momentum chart from a real traced match with honestly documented gaps, and
drops the entire smart-inference feature layer.
