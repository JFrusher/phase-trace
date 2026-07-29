# Tagger — archived

A keyboard-only sports event logger. Log an event in one or two keystrokes
(Team, Event, Modifier), then export JSON that `../../momentum.py` reads.

**This tool is archived and no longer developed.** It is kept as the record of
the first attempt at the input problem, and it is not part of the test suite or
CI. [`tracer/`](../../tracer/) replaced it.

## Why it was replaced

The tagger works, and for football it would still be a reasonable tool. It fails
on rugby for one reason: a keyboard vocabulary can tell you *that* a carry
happened but not *where* it happened, and in rugby field position is most of
what a possession is worth. Metres gained, distance to the try line, whether a
kick found touch inside the 22 — none of it is expressible as a keystroke, and
all of it drives the rugby momentum weight.

Two smaller problems compounded that. Every event needed its own keystroke
sequence, so a fast phase outran the operator. And the vocabulary had to be
extended for every new thing worth recording, which is why `sport-config/` grew
into JSON rule files.

The tracer takes the opposite approach: one continuous mouse drag per
possession, with the software reading the actions off the line's geometry.
Coordinates come free, and the keyboard drops back to annotations that genuinely
aren't in the line (jersey numbers, linebreaks, scores).

## Setup

```bash
cd legacy/tagger
npm install
npm run dev
```

Open the printed local URL. Needs Node.js LTS.

## Hotkeys

| Key | Action |
|---|---|
| `Z` / `X` / `C` | Stage Team A / Team B / Neutral (sticky — stays selected across events) |
| `1`–`9` | Select the event type in that on-screen position. If it has no modifiers, it logs immediately. |
| `Q W E R T Y U I O P` | Select the modifier in that on-screen position (always logs immediately) |
| `Enter` | Submit now (skips the modifier step) |
| `Backspace` | Clear the last staged field (modifier, then event type — team is never cleared this way) |
| `Space` | Start/pause the clock |
| `Shift+Space` | Arm a clock reset — press `Enter` to confirm, any other key cancels |

The clock's scrub slider is mouse-only, enabled while paused.

## Checking the export against the Python pipeline

The export contract was verified by round-tripping through the real pipeline:

```bash
# from the repo root, after using Export in the Tagger:
python momentum.py <exported-file>.json out.png --sport rugby
```

A chart that renders without a `KeyError` or `ValueError` is a compliant export.
`tracer/validate.py` does the same job for the tracer, but automatically and
before the write.
