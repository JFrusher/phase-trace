# 5 · Export topology

**Diagram:** [`../diagrams/export-topology.drawio`](../diagrams/export-topology.drawio)
*(two pages — 1: two logs, two exits · 2: record shapes)*

**Source:** [`../../tracer/events.py`](../../tracer/events.py),
[`../../tracer/raw_export.py`](../../tracer/raw_export.py),
[`../../tracer/export.py`](../../tracer/export.py),
[`../../tracer/validate.py`](../../tracer/validate.py)

---

## Two logs, on purpose

`MatchState` keeps two parallel streams built from the same committed chains:

```python
self.events: list[dict]   # the momentum shape — validated, conservative
self.actions: list[dict]  # the analysis shape — rich, every field optional
```

They answer to different consumers under different rules, which is why they aren't one list with a
discriminator field.

**`events[]` is a contract.** `RugbySport.translate()` and `MomentumEngine.compute()` consume it,
and `validate.py` refuses to write it if they can't. Adding a field here means thinking about the
momentum path.

**`actions[]` is a spreadsheet.** One row per carry, pass and kick, with coordinates. It's for a
coach slicing a match, and its guiding rule is "get out whatever was captured": a column is blank
where nothing was tagged.

The separation buys one specific thing: **nothing added to the rich stream can break the validated
momentum path.** The positional-data widening — stamping `x_m`/`y_m` on discrete events, adding
`positions.csv`, adding the heatmap — touched `actions[]` extensively and `events[]` barely at all.

### The de-duplication rule

`raw_export.action_stream()` merges both streams for the CSV bundle and **drops `phase_sequence`
when it does**, keeping its scoring and discipline siblings.

A `phase_sequence` is the momentum path's *bundled* view of carries that already appear individually
in `actions[]`. Emitting both would double-count every carry in the metres totals. It is a one-line
filter, easy to delete by accident and hard to notice afterwards.

## Validation runs the real pipeline

`validate.py` is 25 lines and worth reading in full. It doesn't check a schema, it *runs* the thing:

```python
std = RugbySport().translate(events)
MomentumEngine(half_life_minutes=sport.decay_half_life).compute(
    std, home, away, sport.chart_profile().max_t)
```

Any exception becomes a human-readable blocker and the write doesn't happen.

Because `tracer/` shares a process with the momentum code, this is the strongest possible check:
nothing can `KeyError` downstream that didn't already fail here. A hand-written schema validator
would be a second description of the same contract, and second descriptions drift.

It also catches the non-obvious failure: `compute()` raises when the net momentum peak is zero, so
"you exported a match with no threat events" is caught at export rather than discovered later at
chart time.

The raw export gets **no** validation, deliberately. It has no downstream contract to break.

## Half-time folding

Swapping ends is a 180° rotation of the pitch about its centre, so `geometry.canonical_xy()` folds
every exported coordinate back into the first-half frame:

```
(x, y) → (PITCH_LENGTH_M − x, PITCH_WIDTH_M − y)
```

Without it, a team's second-half data would land at the opposite end from its first-half data, and
every heatmap, pitch map and positional average would be split in half and meaningless.

The metre-based fields (`metres_gained`, `end_metres_from_line`) are already
orientation-independent, because they read `attack_dir`, so only `x`/`y` need folding. `attack_dir`
itself is reported in the canonical sense, so a team attacks the same way in the data all match.

`MatchState.canon_attack_dir_home` records the frame the match began in, and `_flipped()` asks
whether the live direction still matches it. Sessions saved before this existed default `canon` to
their current direction, so nothing is spuriously folded on resume.

## Page 2 — record shapes

The second page lays out what actually lands in each stream. A few things are worth pulling out.

**`phase_sequence` never carries a weight.** `events.py` says so in its module docstring:
`rugby_weights.json` and `_territory_weight()` stay the single source of truth. The tracer records
metres, field position, linebreaks and origin; the translator turns that into energy. If the weight
were baked in at capture time, retuning the model would mean re-exporting every match.

**Optional fields are absent, not null.** `linebreak`, `intercepted`, `player`, `assist`, `reason`
and `conceded_by` only appear when set. Every reader tolerates their absence, and the CSV writer
only emits columns actually present in the stream (`_action_cols`). A partially-tagged match is
still valid data, which matters because it is the normal case: you don't get every jersey number
during live play.

**`set_piece` outcomes are inferred, not tapped.** The awarded side fed the lineout or scrum; the
side that started the next possession came away with it. Same team is `won`, opposition is `lost`.
One fewer thing to tap for a fact already implied by what happened next.

**`penalty_won` carries `conceded_by`**, so the discipline map can show where a team *gave penalties
away* as well as where it won them. Giving them away is the more useful half for a coach, and it's
why the report's heatmap has a "penalties conceded" metric.

**`StandardEvent` closes the loop.** Six fields, and the territory weight formula is right there on
the diagram:

```
base      = 0.15 + 0.35 · min(metres / 40, 1)
territory = max(0, 1 − end_metres_from_line / 100)
weight    = (base + 0.3 · territory) × (1 + 0.25 · linebreaks) × origin_factor[start_reason]
```

`start_metres_from_line` is exported but deliberately **not** weighted. End position already drives
`territory_factor`, and adding a second positional term with no reference data to fit it against
would be inventing signal. The field is there for when there is data.

## The two consumers

**`momentum.py`** reads the events JSON through `CustomJSONSource`, runs the real pipeline, writes
a PNG. This is the authoritative curve.

**`report/index.html`** reads the export folder. `ingest.js` prefers `match.json` (self-contained)
and falls back to `actions.csv` + `team.csv` + `players.csv`, warning that linebreak, interception
and player tags aren't in the CSV export. Everything is client-side.

Its momentum tab is a **reconstruction**, and both the diagram and
[`report/README.md`](../../report/README.md) say so. Two known gaps:

- `origin_factor` is pinned at **1.0**, because `start_reason` isn't in the raw export. An
  interception-fed phase and a scrum-fed phase get the same weight.
- The x-axis uses match minute when timestamps span time, and falls back to **possession sequence**
  when the clock was never started, labelled as such on the chart.

It runs the same decay and smoothing maths, ported to JS, but on different inputs. It approximates
`momentum.py` rather than reproducing it, and it says so in three places, because an approximate
chart that looks authoritative is worse than no chart.

`report/selfcheck.html` runs in-browser assertions over the territory weight, the Gaussian blur, the
metre-to-pixel mapping and the timebase fallback. It's the executable half of that README.

## Trade-offs

**CSV parsing is minimal.** `report/ingest.js` splits on newlines and commas and trims, with no
quoted-comma handling. A `ponytail:` comment marks the ceiling: upgrade only if a team name ever
contains a comma. The tracer's numeric and short-token exports never need it.

**Colours are pinned at the ingest boundary.** `safeColor()` rejects anything that isn't a six-digit
hex literal, because those values flow into `style="background:…"` attributes and SVG fills. A
future colour-carrying export (a session save's `team_colors`, say) can't break out into markup.

**`positions.csv` is a convenience, not a dependency.** The bundled report reads positions off
`match.json`'s action stream. The CSV exists so someone can open it in Excel and pivot it, and
nothing in the codebase reads it back.
