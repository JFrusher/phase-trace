# 1 · System composition

**Diagram:** [`../diagrams/system-composition.drawio`](../diagrams/system-composition.drawio)
*(C4-container flavour: one page, four bands top to bottom)*

---

## The shape of it

There are two separable problems in this repo, and almost every design decision follows from
keeping them separate.

The first is *the maths*: given a stream of weighted, timestamped threat events, draw a
broadcast-style momentum curve. That was solved upstream for football, and it is sport-agnostic.
Exponential decay and Gaussian smoothing don't care what game produced the impulses.

The second is *getting the event stream*, which is the hard part. Typing one out during a match is
slow and you get it wrong, and in rugby the thing you most need is *where* on the pitch it happened,
which a keyboard vocabulary can't express. `tracer/` exists for this and holds roughly 80% of the
code.

The four bands in the diagram are: capture (`tracer/`), what it writes, who reads that, and the
library the readers drive.

## Components

### `core/` — the maths, ~150 lines total

`schema.py` defines `StandardEvent(team, t, weight, category, label, marker)`. That is the *only*
shape the engine ever sees. Everything upstream exists to produce it.

`engine.py` is the model in one line:

```
momentum_team(t) = Σ over events e:  wₑ · exp(−λ · (t − tₑ))    for t ≥ tₑ
```

…then a Gaussian blur, then `home − away` normalised to its own peak so exactly one team is above
the line at a time. `compute()` raises if the peak is zero, which is what makes it usable as a
validation dry-run (see page 5).

`chart.py` renders it, taking axis ticks and interval markers from a `ChartProfile` rather than
hardcoding 90 or 80 minutes.

`t` is deliberately typed as "a continuous clock position", not "minutes". A sport without a wall
clock (tennis, say) would map points and games onto a synthetic axis and the engine wouldn't notice.

### `translators/` — one class per sport

A `BaseSport` owns match structure (duration, half-time markers, decay half-life, tick labels) and
`translate()`, which turns raw provider events into `StandardEvent`s.

The two implementations differ in kind, not just in their numbers:

- **Football** keys off discrete threat moments (shot, big chance, goal, sustained pressure), so its
  weights are a flat JSON lookup table.
- **Rugby** has no equivalent single moment. Threat builds through phase play and territory, so
  `RugbySport._territory_weight()` *derives* a weight in code from metres gained, how close the
  possession finished to the try line, linebreaks, and how the possession began.

That asymmetry is why `translate()` is a method rather than a weight table. Making weight a lookup
on both sides would have forced rugby into a shape that doesn't fit it.

### `sources/` — one class per data provider

`BaseDataSource.parse()` normalises one provider's file format. It knows nothing about sport
vocabulary or weighting.

Keeping Sport and DataSource as **independent axes** is the deliberate call. The obvious
alternative, one class per (sport, provider) pair, multiplies: three sports and four providers is
twelve classes, eleven of them copy-paste. Here it's seven.

### `tracer/` — the Live Trace app

A NiceGUI single-process app. You hold the mouse button down and follow the ball for a whole
possession; keyboard taps layer annotations on without breaking the drag. It writes the same JSON
`momentum.py` reads.

Internally it splits into: UI shell (`app.py`, `canvas.py`, `chips.py`), orchestration
(`match_state.py`), recognition (`segmentation.py`, `features.py`), rugby semantics (`events.py`,
`geometry.py`) and writers (`export.py`, `raw_export.py`, `autosave.py`).

`match_state.py` is the load-bearing module and it imports no UI. It talks to the app through three
optional callbacks (`on_commit`, `on_change`, `on_correction`), which is why the whole of it is
testable without a browser, and why `fixtures.py` can drive a real `MatchState` with synthetic
input and get faithful behaviour.

### `report/` — the standalone viewer

A no-build HTML page. Open the file, pick an export folder, get five tabs. Everything is parsed
client-side; nothing leaves the machine.

Its momentum tab is an **approximation**, and the diagram says so. The raw export doesn't carry
`phase_sequence` events, so the viewer regroups possessions from consecutive same-team actions and
pins `origin_factor` to 1.0. It ports the decay maths from `core/engine.py` unchanged, but the
inputs differ, so the curve is not the authoritative one.

## Walkthrough: one match, end to end

1. **Setup** — teams, colours, kickoff possession, attack direction. `MatchState` is constructed.
2. **Trace** — press, follow the ball, tap `A` when the play dies. Each committed chain appends to
   two logs and autosaves.
3. **Correct** — chips on the pitch carry the inferred set piece; clicking a drawn segment cycles
   its action. Every correction is logged (page 6).
4. **Export** — *Validate + export* writes the events JSON, but only after `validate.py` has
   dry-run the actual pipeline. *Export data (CSV)* writes the analysis bundle unconditionally.
5. **Chart** — `python momentum.py exports/....json out.png --sport rugby`.
6. **Review** — open `report/index.html`, pick the export folder.

## Trade-offs worth knowing

**One process, no server.** The tracer, the maths and the validator all share a Python process.
That is what makes `validate.py` possible in its current form: it calls `RugbySport().translate()`
and `MomentumEngine.compute()` directly rather than reimplementing a schema check that would drift.
The cost is that the tracer can't be a thin client, and browser latency shows up as timestamp jitter
(see page 3).

**No live chart.** Chart generation stays a manual `momentum.py` step. Rendering during capture
would put matplotlib in the request path for no benefit, since you can't act on a momentum curve
mid-match anyway.

**The clock is a stopwatch.** You start and pause it to stay roughly with play. Trace pace and real
match time are structurally unlinkable given the input model, so **event minutes are approximate**,
and minute is the chart's x-axis. This is the largest known inaccuracy in the system, and fixing it
needs a different input model.

**The rugby weights are unvalidated.** The football side was checked against published Flashscore
graphics. The rugby side (decay half-life 4.5, the territory formula, the nine `origin_factor`
values, cards as markers rather than impulses) is judgement with no reference data behind it. The
code says so in its docstrings; so does page 4.
