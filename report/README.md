# Match Report — tracer export viewer

A no-build web page that reads a tracer **export folder** and renders five views, styled to match
Live Trace. No server, no dependencies, no build step: open the HTML file in a browser.

## Use

1. Open `report/index.html` in a browser (double-click, or `file://`).
2. **Choose folder** and pick an `exports/<HOME>_v_<AWAY>/` folder, **Choose files**, or drag-drop
   the folder onto the page.
3. Pick a tab.

`report/sample/` holds a ready export bundle. Pick that folder to see it work.

## What it reads

`match.json` first: it is self-contained (`meta` + `actions` + `summary`). If it is absent the page
falls back to `actions.csv` + `team.csv` + `players.csv`. All parsing is client-side; nothing leaves
the machine. Positions ride on the actions stream (see [Positions](#positions)), so the heatmap
works straight from `match.json`.

An export folder may also contain `radl.csv`, the same stream as a
[RADL](https://github.com/ThatsNoicey/RADL) action frame. This page ignores it. RADL is the
interchange format for analysis elsewhere.

## The five views

- **Pitch map** — every carry / pass / kick drawn on the pitch from its `start`/`end` metres,
  coloured amber / blue / red (intercepts dashed). Toggle by team and action type. Records without
  coordinates (set pieces, scores) aren't drawn but still count in the stats.
- **Heatmap** — a Gaussian KDE of any located metric over the pitch. Pick the metric (all actions,
  carries/passes/kicks, linebreaks, or the discrete events: tries, penalties won, penalties conceded,
  turnovers, errors, cards, set pieces), filter by team, and drag the bandwidth slider. **Single**
  mode shades in one team's hue; **Differential** diverges home (red) to away (blue) about a neutral
  midpoint. Lines are sampled along their whole path; discrete events plot at their captured point.
  Penalties conceded is the discipline map — it reads the `conceded_by` field, so picking a team
  shows where **they** gave penalties away rather than where they won them.
- **Team** — home-vs-away mirrored comparison of `summary.team`: possession count, metres, action
  tallies, discipline, plus penalty-reason and error-kind breakdowns where they were tagged. The
  tracer computes this at export time (`raw_export.team_summary`) and the page only renders it, so
  the tab and the CSVs cannot disagree.
- **Players** — sortable per-player table from `summary.players`, keyed on jersey number. Rows only
  exist for numbers tapped during capture, so an untagged match shows an empty state. That is the
  common case: tagging numbers live is optional and most traces skip it.
- **Momentum** — a mirrored area curve reconstructed from the action stream. See the caveat below.

## Momentum is reconstructed (approximate)

The raw export drops the `phase_sequence` events the momentum engine keys off, so this page rebuilds
possession phases by grouping consecutive same-team actions, derives a territory weight the way
[`translators/rugby.py`](../translators/rugby.py) `_territory_weight` does, then runs the same
exp-decay and Gaussian smoothing as [`core/engine.py`](../core/engine.py). Two known gaps:

- **origin_factor is fixed at 1.0.** `start_reason` isn't in the raw export, so an interception and a
  scrum-fed phase carry the same weight.
- **x-axis** uses match minute when timestamps span time. When the clock was never started (every
  `minute` is `0.0`, common in quick captures) it falls back to possession sequence, labelled as such
  on the chart.

Read the curve as approximate. `momentum.py` produces the authoritative one.

## Self-check

Open `report/selfcheck.html`. It asserts the territory weight, the Gaussian blur, the metre-to-pixel
mapping and the momentum timebase fallback, and prints PASS/FAIL. All should pass.

## Files

| File | Role |
|------|------|
| `index.html` | Page shell + file/drop wiring |
| `report.css` | Live Trace palette (as CSS tokens) + layout |
| `ingest.js` | Folder/file read, JSON-first + CSV fallback, shape-sniff, normalize |
| `pitch.js` | Port of [`tracer/pitch.py`](../tracer/pitch.py) SVG pitch + action overlay |
| `momentum.js` | Momentum reconstruction + engine port |
| `heatmap.js` | Gaussian KDE (bin → blur → colormap) for the heatmap |
| `views.js` | Match header, pitch map, heatmap, team comparison, player table, momentum chart |
| `selfcheck.html` | In-browser assertions |
| `sample/` | A real export bundle to test against. Regenerate with RADL's `tools/make_synthetic_match.py <phase-trace> report/sample` |

## Positions

Carries, passes and kicks have always carried `start`/`end` coordinates. The tracer also stamps
discrete events (tries, penalties, turnovers, errors, set pieces) with an `x_m`/`y_m` taken from
where the ball was when the key was tapped. Both land in `positions.csv` and on `match.json`'s
action stream, which is what the heatmap consumes.

**Cards and conversions carry no position, deliberately.** A sin bin or a conversion is logged by a
keystroke well after the ball has moved on, so "where the ball was" is wherever the pointer had
drifted to. That is pointer noise, and it used to reach the heatmap as if it were data.
`tracer/config.py`'s `LOCATED_EVENT_TYPES` is the list of types that do get a position.

## Period and possession

Every row also carries `period` (1, 2, and on into extra time) and `possession` (a running id from
1). The tracer records both; the page never re-derives them. Halftime swaps ends and the export
folds that swap away, so nothing downstream can recover the half from the coordinates. Possession
boundaries are exact for the same reason — segments are assigned to teams before export.
