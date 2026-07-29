# 3 · Possession lifecycle

**Diagram:** [`../diagrams/possession-lifecycle.drawio`](../diagrams/possession-lifecycle.drawio)
*(two pages — 1: chain state machine · 2: one possession, call by call)*

**Source:** [`../../tracer/match_state.py`](../../tracer/match_state.py),
[`../../tracer/continuity.py`](../../tracer/continuity.py)

---

## What `MatchState` is for

`match_state.py` is the biggest module in the repo and the only one that knows about all the
others. It owns the clock, possession, the chain lifecycle, tap dispatch, undo, and the two output
streams. It imports no UI: `app.py` wires browser events in and reads state back through three
optional callbacks.

```python
m.on_commit    = committed              # a chain landed — redraw the canvas
m.on_change    = lambda: (save(), refresh(), chips.refresh())
m.on_correction = feedback.log_correction
```

That inversion is load-bearing. It's why `fixtures.py` can drive a real `MatchState` with synthetic
pointer input and get behaviour identical to the live app, and why every test in `tracer/tests/`
runs without a browser. An unwired callback is a no-op, which is also why tests never write to the
feedback database.

## Page 1 — the state machine

Four states and one you pass through:

**Awaiting press.** `pending_start_reason` is set, `last_origin.mark` is armed and drawn as a small
target dot on the pitch, and `armed_next_action` may be set by a penalty option chooser.

**Recording.** `ChainRecorder` accumulates `PathPoint`s; `KeyState` appends timestamped taps and
Shift intervals.

**Segmenting.** `segment_path()` then `apply_taps()`. A rejected path — fewer than three points, or
under `MIN_MOVEMENT_PX` — commits nothing and goes straight back to *Awaiting press*.

**Committed.** `_commit_chain()` runs team assignment, score resolution, origin inference and both
output streams, then fires the callbacks.

**Re-committing.** A correction rewinds to the pre-commit snapshot and replays `_commit_chain()`.

### Snapping: the whole path moves, not just its start

`mouse_down` looks up where the pending possession begins — the lineout mark, the scrum mark, the
spot a turnover happened, the centre spot for a restart — and if it snaps, it shifts **the entire
path** onto that mark, not only the first point.

That's the subtle bit. Moving the start alone would turn the gap between the mark and a sloppy press
into a leg of its own, and Layer 1 would faithfully detect a boundary there and emit a phantom
action. Shifting the whole path preserves its shape exactly.

Two kinds of mark, so two snapping rules:

- **Centre-spot restarts** (`kickoff`, `restart`) always snap. The ball is on the spot however you
  press; that is law, not inference.
- **Positional marks** (lineout, scrum, turnover, penalty) are inferred, so they snap only within
  `SNAP_TOLERANCE_M = 10.0`. A press further out is taken at face value as a deliberate free start,
  so one wild click can't drag a whole trace onto a wrong guess.

`mouse_down` returns the point it actually recorded and the canvas draws from that, so the drawn
line and the recorded data can never disagree about where play began.

### What ends a chain

Four ways, and the ordering of authority matters:

1. **`A` or `Space`** — the authoritative signal. The play died: tackle, ruck, whistle.
2. **`S` or `F`** — also ends it, and additionally records a scrum or a penalty.
3. **The traced line leaving the field.** `_left_field()` fires mid-`mouse_move`. In law the play is
   already over, so keep drawing straight out and the lineout or drop-out lands without a tap.
4. **Mouse-up** — a defensive fallback only.

Releasing the button being the fallback rather than the signal is the core mechanic. It's what lets
one continuous drag cover pass-run-pass-tackle without you having to decide mid-play where the
actions divide.

`_left_field()` tests *crossing*, not proximity, because a winger runs inside the touch margin all
game without going out. It is guarded by the same displacement floor `segment_path()` uses, so a
trace started on a line can't end itself before it has drawn anything.

### Two snapshots, taken at different moments

This is the detail most likely to bite someone changing this file, and it's called out in a note on
the diagram.

**`_undo`** is taken at `mouse_down`, not at commit. Taps landing mid-trace (a `T` for a try, a `V`
for a turnover) have already mutated `events` and `possession` by the time the chain commits. Undo
has to take those back too, so the snapshot must predate them.

**`_precommit`** is taken at commit. `_undo` is no use for re-classification, because re-classifying
happens via a click, and a click is itself a `mouse_down`, which overwrites `_undo` with post-commit
state before the handler ever runs.

### Corrections rewind and replay; they never patch

`reclassify_segment(i)` cycles a segment's action and then re-runs the entire commit over the same
points. It does not edit the emitted events.

Recomputing is both shorter than patching and the only version that stays correct. Changing an
action can flip possession, split the chain differently, change which sub-chains exist, change the
inferred origin, change the score, and change where the next press snaps to.

The same applies to `choose_in_goal_outcome()`: switching away from a try has to un-log the try
event, take its five points back, and undo the restart it triggered. Replaying is the only way that
stays consistent.

One extra step comes with a manual KICK: `reclassify_downstream()` re-derives every segment *after*
the changed one, because toggling a KICK on or off changes the attack-direction frame they were
classified in. Segments up to and including the changed one keep their now user-set action.

**Undo is one level, no stack.** There's a `ponytail:` comment on it saying so — the "I just saw
that go wrong" case is the only one that happens in practice, and `_undo` becomes a deque the first
time a real trace shows multi-step regret.

## Page 2 — one possession, call by call

The sequence diagram walks a single possession from press to committed, then a correction.

Reading it, three things stand out:

**`MatchState` is the hub.** Every other module is a leaf. `segmentation.py` and `events.py` are
pure functions called into and returned from; they never call back.

**`assign_teams` and `infer_origin` are separate calls with different jobs.** The first walks the
chain deciding who held the ball for each segment (a KICK hands over, an intercepted PASS hands
over). The second reads how the chain *ended* to decide how the next one *begins*, which is page 4's
whole subject.

**Both output streams are written in the same pass.** `chain_to_events()` collapses same-team runs
into `phase_sequence` records for the momentum path; `chain_to_actions()` keeps every segment as its
own row for analysis. Page 5 covers why.

### The timestamp caveat

`canvas.py` stamps timestamps server-side on event arrival, because the browser's
`MouseEventArguments` carries no client clock. On localhost that's fine. Over a WAN, latency jitter
would degrade tap correlation. That is the one place in the whole recognizer where timing still
matters — Layers 1 and 2 never read a timestamp at all.

## Trade-offs

**No formal state machine object.** `pending_start_reason` and `armed_next_action` are two nullable
fields, with a comment in the source noting this is deliberately not a state machine, so that
nothing can get stuck in an unreachable state. The diagram draws a state machine because that's the
clearest way to explain it, not because one is implemented.

**Per-connection state, built inside the page closure.** Module-level state would let two browser
tabs, or a reload, corrupt each other's match. `reload=False` on `ui.run()` is for the same reason
and is called non-negotiable in the source: dev auto-reload restarts the process and silently drops
in-memory match state.

**Nothing blocks.** Every chooser is pre-selected on the guess; ignoring it accepts that guess. A
modal that stops the clock during a match costs more than a wrong guess you can fix in one click.
