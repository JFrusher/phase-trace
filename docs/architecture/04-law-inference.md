# 4 · Rugby-law inference

**Diagram:** [`../diagrams/law-inference.drawio`](../diagrams/law-inference.drawio)
*(one page: the decision tree, plus the tapped bypass and the colour key)*

**Source:** [`../../tracer/events.py`](../../tracer/events.py) (`infer_origin` and friends),
[`../../tracer/geometry.py`](../../tracer/geometry.py) (the field maths),
[`../../tracer/chips.py`](../../tracer/chips.py) (the correction UI)

---

## Why a possession's origin is worth this much code

In rugby, how a possession *began* is a large part of what it's worth. An interception 40 m out is a
different proposition from a scrum on your own 22, even if the phase that follows looks identical.
So every possession is recorded with a `start_reason`, and that reason scales its momentum weight
through `origin_factor` in
[`translators/rugby_weights.json`](../../translators/rugby_weights.json).

Making the analyst type that in would be one more thing to get wrong under time pressure, and most
of it is already sitting in the traced line.

## The three sources of truth

This is the organising idea of the whole page, and the diagram colour-codes by it.

**Geometry settles it (green).** A line crossing a touchline *is* a lineout. A score *is* followed
by a restart. A ball put over the dead-ball line *is* a 22 drop-out. For these the type is **never
editable**: a lineout would never become a scrum, so offering that choice would be noise. Only the
*team* is offered as a correction.

**A tap supplies it (orange).** Two things a traced line genuinely cannot show: a scrum and a
penalty. A knock-on looks exactly like a tackle; a penalty looks like nothing at all. `S` and `F`
bypass the tree entirely and set the origin directly.

**A chooser supplies it (orange).** Whether the ball was grounded in the in-goal is invisible in a
line, and so is what a team chose to do with a penalty. These get a chooser row on the chip,
pre-selected on the likely answer. Ignoring it accepts the guess; nothing blocks.

The categories tell you what to do when the tool is wrong. Green wrong means the geometry is wrong,
which is a bug or a bad trace. Orange wrong means you didn't tell it, which is one click.

## Walking the tree

`infer_origin()` tests in order; first match wins.

### 1 · A score was recorded → `restart`, centre spot

The **conceding** side takes the drop kick, so *they* hold the ball. This is the one rule people
consistently get backwards when they first read the code, and there's a comment about it in three
different files: **possession always means who has the ball, never who is about to receive it.**
The restart kick itself does the handing over, when you trace it.

Half-time follows the same principle from the other direction: `halftime_flip()` gives the kickoff
to whoever did *not* start the match with it.

### 2 · The line crossed a touchline → `lineout`, and the on-the-full law

The sub-tree here is the most rugby-specific logic in the repo.

- **Carried out?** The mark is where the carrier crossed, and the kick-to-touch law has nothing to
  say about it.
- **Kicked out, with a penalty armed as `kick_to_touch`?** The throw stays with the **kicking** team
  and the ground is kept. The armed case is tested *before* the law below and bypasses it, because a
  penalty to touch is not an open-play kick.
- **Kicked from inside your own 22?** You may kick directly into touch and keep the ground: the
  lineout forms at the exit point.
- **Kicked from outside it?** The ball is assumed to have gone out **on the full**, so the lineout
  goes back to the kick.

That last default is a deliberate choice under uncertainty. A top-down trace cannot see a bounce, so
the tool takes the stricter reading and offers the alternative: `ChainOrigin` carries an `alt_mark`,
and the `⇄` button on the chip swaps between them. Both marks are lawful; only the analyst knows
which happened.

One quirk documented in `geometry.py` and worth knowing: for kicks, "out of touch" is tested by
proximity (`ends_in_touch`) rather than crossing. The browser stops reporting `mousemove` once the
cursor leaves the image, so a ball kicked out is a path that **stops** at the edge, never one that
visibly crosses it. Carries use the strict crossing test, because a winger runs inside that margin
all game.

### 3 · Past a dead-ball line, or the chooser says drop-out → `drop_out_22`

The defending side drops out from their own 22, whoever put the ball there. Which side defends which
in-goal is pure geometry (`in_goal_defender`) and never depends on who happened to be carrying. That
matters because both teams end up in both in-goals over a match.

### 4 · The chooser says held up → `scrum` at the 5 m mark

Attacking side. Only reachable through the in-goal chooser; nothing infers it.

### 5 · Last segment was a KICK → `kick_return`

The receiving side, with **no mark**. The ball is in open play, so the next press is free-hand rather
than snapped.

Note this doesn't log a `turnover_won`. A kick is a tactical choice, not a forced error, and
crediting it as a turnover would inflate the receiving team's momentum for something the kicking
team decided to do.

### 6 · Any PASS was intercepted → `interception`

Driven by a Shift held over the pass during the trace. This one *does* log a `turnover_won`, and it
splits the chain: everything after the intercepted pass belongs to the other team.

### 7 · Otherwise → `turnover_open`

The fall-through, marked where the trace ended. Possession is assumed lost at the breakdown: the
coarse knock-on / jackal / held-in-the-tackle case. There's a `ponytail:` comment in the source
acknowledging the assumption. Tap `Z` or `X` if possession was actually retained, as when a penalty
is played on.

## What the taps do

`S` (scrum) and `F` (penalty) both end the play and award **against whoever was carrying**. That's
right most of the time, and the chip's team badge fixes the rest in one click.

An `F` tap does three extra things:

1. Logs a `penalty_won` event carrying `conceded_by`, the side that gave it away, so a coach can map
   their own discipline rather than only penalties won.
2. Arms the option chooser: *to touch · at goal · tap · scrum*, defaulting to `kick_to_touch`.
3. Sets `armed_next_action`, which forces the next stroke to be a KICK. To-touch and at-goal are both
   kicks by definition, and letting the recognizer read a short-drawn penalty kick as a carry would
   put the ball in the wrong hands.

A penalty chip carries a second chooser for *why* it was given (offside · high · ruck · scrum · foul
· other). It writes onto the `penalty_won` event as an optional extra that the momentum translator
ignores, and stays absent until picked — the general rule for annotations here.

### Penalties at goal

Picking *at goal* changes how the trace is judged. Instead of offering a grounding chooser,
`penalty_at_goal_scored()` reads where the kick's ground track crosses the goal line and whether
that crossing falls between the uprights (`GOAL_WIDTH_M = 5.6`). If it does, three points are
awarded automatically.

Rugby is three-dimensional and a top-down trace is not, so height over the bar is invisible. A line
drawn through the posts counts as a successful kick, on the basis that the analyst drew it that way
on purpose. A kick that falls short or crosses wide is a miss.

### In-goal outcomes

A trace finishing over a try line gets a chooser: *try · held up · drop-out*, pre-selected on the
guess. Carrying into the in-goal you're attacking reads as a try (scored immediately; `C`/`M` still
attaches the conversion). A kick into the in-goal, or ending up in your own, reads as a 22 drop-out,
because defenders field those far more often than the chase wins them.

Switching the choice rewinds the chain and re-commits it, so a try taken back also takes its five
points back (page 3).

## Where the guesswork actually is

The tracer's job is to say **what happened**. The translator's job is to say **what it's worth**.
Only the second half is guesswork:

| Reason | `origin_factor` |
|---|---|
| interception | 1.30 |
| penalty | 1.25 |
| lineout | 1.15 |
| turnover_open | 1.10 |
| scrum | 1.00 |
| kick_return | 0.95 |
| kickoff, restart | 0.90 |
| drop_out_22 | 0.85 |

These nine numbers are judgement calls with no reference data behind them, and `rugby.py`'s
docstring says so plainly. Set pieces get no weight of their own: a lineout is context for the
possession it starts rather than threat creation in itself, and crediting it separately would
double-count that possession. Cards work the same way. Going to 14 men isn't threat creation, and
the pressure it invites is already counted by the phases that follow.

The football side of this repo was validated against published Flashscore graphics. The rugby side
has not been validated against anything, because nobody has traced a real match end to end yet. The
gap is in the data, not in the documentation — the code, the README and this page all say so.
