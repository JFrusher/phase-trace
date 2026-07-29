# Architecture docs

Six areas of this repo that are hard to reconstruct from the source alone, each with a diagram and
the reasoning behind it. Read them in order if you're new; jump straight to the one you need if
you're not.

| # | Page | What it answers |
|---|------|-----------------|
| 1 | [System composition](architecture/01-system-composition.md) | What the four packages are, and why the momentum maths knows nothing about rugby |
| 2 | [The recognizer pipeline](architecture/02-recognizer-pipeline.md) | How one mouse drag becomes a list of carries, passes and kicks — and why drawing speed can't change the answer |
| 3 | [Possession lifecycle](architecture/03-possession-lifecycle.md) | The chain state machine, the two undo snapshots, and the rewind-and-replay correction model |
| 4 | [Rugby-law inference](architecture/04-law-inference.md) | How the tool decides a lineout from a scrum from a 22 drop-out, and which facts it refuses to guess |
| 5 | [Export topology](architecture/05-export-topology.md) | Two parallel event logs, two exits, and the record shapes that land in each |
| 6 | [Calibration loop](architecture/06-calibration-loop.md) | Where every threshold comes from, and why no tool in this repo may write `config.py` |

## Viewing the diagrams

Diagrams are native `.drawio` files in [diagrams/](diagrams/) — editable, diff-visible XML rather
than baked images.

- **VS Code** — install the *Draw.io Integration* extension (`hediet.vscode-drawio`) and open the
  file. Multi-page diagrams get a page tab bar at the bottom.
- **Browser** — [app.diagrams.net](https://app.diagrams.net) → *File ▸ Open from ▸ Device*. Nothing
  is uploaded; the editor runs locally in the tab.
- **Desktop** — draw.io Desktop opens them directly. It also ships a CLI, which is the only way to
  export PNG/SVG/PDF from these files:
  ```bash
  drawio -x -f svg -e -b 10 -o diagram.drawio.svg diagram.drawio
  ```
  The `-e` flag embeds the diagram XML in the export, so the exported file stays editable.

No PNG or SVG exports are committed. They would be a second copy of the same information with
nothing keeping them in step, and a diagram that quietly stopped being true is worse than none.

## Conventions used across all six diagrams

| | |
|---|---|
| **Blue** `#dae8fc` | Code — a module, a function, a step in a pipeline |
| **Yellow** `#fff2cc` | Data — an in-memory log, a file on disk, a record shape |
| **Green** `#d5e8d4` | An output, or something the sport-agnostic core owns |
| **Orange** `#ffe6cc` | A human is in the loop — an operator tap, a chooser, a correction |
| **Red** `#f8cecc` | A hard gate: the laws of the game overriding geometry, a validation blocker, a decision no tool is allowed to make for you |
| **Purple** `#e1d5e7` | A decision the code evaluates |
| **Dashed grey box** | Context or a zone label, not a component |
| **Dashed edge** | Optional, asynchronous, or a loop back to an earlier step |

## What isn't documented here

- `legacy/tagger/` — the archived React keyboard logger this project replaced. Kept for the record;
  see its own [README](../legacy/tagger/README.md) for why it wasn't enough.
- Per-view internals of `report/` — the viewer has its own [README](../report/README.md), and its
  self-check page (`report/selfcheck.html`) is the executable version of that document.
- Tuning procedure — [tracer/TUNING.md](../tracer/TUNING.md) covers the symptom-to-parameter table.
  Page 6 here covers the *shape* of that loop, not the recipe.

[docs/tracer-dataflow.drawio](tracer-dataflow.drawio) predates this set and covers similar ground
for `tracer/` in three pages. It is left as-is; where the two disagree, these pages are newer.
