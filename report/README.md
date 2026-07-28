# Match Report — tracer export viewer

A standalone, no-build web page that reads a tracer **export folder** and turns it into four
views, styled to match Live Trace's bright-pitch look. No server, no dependencies, no build step —
open the HTML file in a browser.

## Use

1. Open `report/index.html` in a browser (double-click, or `file://`).
2. **Choose folder** and pick an `exports/<HOME>_v_<AWAY>/` folder, **Choose files**, or drag-drop
   the folder onto the page.
3. Explore the four tabs.

A ready sample lives in `report/sample/` — pick that folder to see it work.

## What it reads

`match.json` is the source of truth (self-contained: `meta` + `actions` + `summary`). If it's absent,
the page falls back to `actions.csv` + `team.csv` + `players.csv`. Parsing is 100% client-side —
nothing leaves the machine. Positions now ride on the actions stream (see "positions" below), so the
heatmap works straight from `match.json`.

## The five views

- **Pitch map** — every carry / pass / kick drawn on the pitch from its `start`/`end` metres,
  coloured amber / blue / red (intercepts dashed). Toggle by team and action type. Records without
  coordinates (set pieces, scores) aren't drawn but still count in the stats.
- **Heatmap** — a Gaussian KDE of any located metric over the pitch. Pick the metric (all actions,
  carries/passes/kicks, linebreaks, or the discrete events — tries, **penalties won**, **penalties
  conceded**, turnovers, errors, cards, set pieces), filter by team, and drag the blur (bandwidth)
  slider. Penalties conceded is the discipline map: pick a team to see every spot **they** gave a
  penalty away (attributed via the `conceded_by` field the tracer stores). **Single** mode shades in
  one team's hue (transparent → saturated); **Differential** mode diverges home (red) ↔ away (blue)
  with a neutral midpoint, so you see which side owned each zone. Lines are sampled along their whole
  path; discrete events plot at their captured point.
- **Team** — home-vs-away mirrored comparison from `summary.team`, plus penalty-reason / error-kind
  breakdowns when present.
- **Players** — per-player table from `summary.players` (sortable). Shows an empty-state when jersey
  numbers weren't tagged during capture (common).
- **Momentum** — a mirrored area curve reconstructed from the action stream. See the caveat below.

## Momentum is reconstructed (approximate)

The raw export drops the `phase_sequence` events the official momentum engine keys off, so this page
rebuilds possession phases by grouping consecutive same-team actions and derives a territory weight
the same way [`translators/rugby.py`](../translators/rugby.py) `_territory_weight` does, then runs the
same exp-decay + Gaussian-smoothing math as [`core/engine.py`](../core/engine.py). Two known gaps:

- **origin_factor is fixed at 1.0** — `start_reason` isn't in the raw export, so an interception and a
  scrum-fed phase are weighted the same. This is an approximation, not a reproduction of the official
  curve.
- **x-axis** uses match minute when timestamps span time; when the clock was never started (every
  `minute` is `0.0`, common in quick captures) it falls back to **possession sequence**, labelled as
  such on the chart.

## Self-check

Open `report/selfcheck.html` — it runs assertions for the territory weight, the Gaussian blur, the
metre→pixel mapping, and the momentum timebase fallback, and prints PASS/FAIL. All should pass.

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
| `sample/` | A real export bundle to test against |

## Positions

Every located thing carries a pitch position. Carries/passes/kicks always had `start`/`end`
coordinates; the tracer now also stamps discrete events (tries, penalties, turnovers, errors, cards,
set pieces) with an `x_m`/`y_m` from where the ball was when they were tapped. The export writes a
`positions.csv` (one row per located thing) alongside the other files, and the same positions ride on
`match.json`'s action stream — which is what the heatmap consumes.
