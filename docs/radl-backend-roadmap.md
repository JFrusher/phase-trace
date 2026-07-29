# RADL backend roadmap

Where phase-trace's storage stands after the RADL alignment, and what the next
person building the database / API / vendor layers needs to know before they
start. Every `TODO(radl-*)` comment in the codebase points here.

## Where things stand

RADL is the **interchange boundary**, not the in-memory model. That is a
deliberate choice, and the thing most likely to be reversed by accident:

- **`MatchState` is a drawing state machine.** Pixels, chains, segments, taps,
  undo snapshots, snap marks, armed penalty options. None of that is RADL and
  none of it should become RADL — a flat action table is the wrong shape for
  state that is still being edited by a mouse.
- **`match.json` is the stable interface.** `radl.phase_trace.read_match` parses
  it as plain JSON and never imports phase-trace. Keep it that way: the coupling
  is one file format, in one direction.
- **The momentum path is separate and stays separate.** `MatchState.events`
  holds `phase_sequence` rows that bundle a whole possession with no
  coordinates. RADL cannot express that shape and explicitly refuses it
  (`radl/phase_trace.py`). Deleting `events` to "unify on RADL" deletes the
  momentum chart, which is the product.

What the alignment actually changed:

| | before | now |
|---|---|---|
| `metres_gained`, `end_metres_from_line` | clamped at 0, contradicting the coordinates beside them | signed; `translators/rugby.py` and `report/momentum.js` clamp at the point of use |
| `period` | not recorded; RADL guessed from a caller-supplied `halftime_minute` | stamped on every row by `MatchState.period`, advanced by `halftime_flip` |
| `possession` | not recorded; RADL re-inferred it from team changes | stamped from the team-assigned segments (`MatchState._number_possessions`) |
| position on a card / conversion | pointer coordinates at the keystroke | not stamped at all (`config.LOCATED_EVENT_TYPES`) |
| `possession_start_reason` on a mid-chain handover | absent — ~1 possession in 6 could not say how it began | `kick_return` / `interception`, the same names the between-chain case already used (`events.split_reason`) |
| vocabularies | duplicated in both repos, nothing checked | held equal by `tracer/tests/test_radl_contract.py` |
| RADL output | none — RADL had to be run by hand | `radl.csv` written by every export, validated before write |

Two of those change momentum values, deliberately. Signed metres are clamped at
the weight rather than in the data, which leaves the chart identical. But naming
a mid-chain handover means a sub-chain created by a kick now receives the
`kick_return` origin factor from `translators/rugby_weights.json`, where it
previously got the 1.0 default — the same factor the identical handover already
received when it happened between two chains. `report/momentum.js` reads the
same field, so the app's chart and the report's reconstruction moved together.

## TODO(radl-storage) — a database

The frame is already one flat table, which is the whole point of an action
language. So:

```sql
CREATE TABLE actions (<radl.config.COLUMNS with radl.config.DTYPES>);
CREATE INDEX actions_match_possession ON actions (match_id, possession_id);
```

- Write with `frame.to_sql`, read with `pd.read_sql`. **Do not write an ORM row
  class per action.** A `Action(Base)` declarative model would be a second
  definition of a schema that `radl.config` already owns, and the two would
  drift the same way the vocabularies did before `test_vocab_parity.py`.
- `freeze_frame` is the one non-scalar column (`object`, per `spec §2.9`). It is
  null everywhere today. When something fills it, store it as JSON in a text
  column rather than normalising it into a second table — it is a per-row blob
  by design, not a relation.
- Generate DDL from `radl.config.DTYPES` rather than hand-writing it, so adding
  a column to the spec cannot leave the table behind.
- Start with SQLite. `tracer/feedback.py` already uses it for the correction
  log; there is no reason for a second engine until there is a second writer.

## TODO(radl-api) — an HTTP layer

phase-trace has no API today; the app is NiceGUI talking to an in-process
`MatchState`. If one is added:

- Serve RADL, not `MatchState`. `GET /matches/{id}/actions` returns the frame
  (`frame.to_dict("records")`, or CSV/parquet by `Accept` header). Nothing about
  chains, segments or pixels belongs on the wire.
- Ingest is `POST /matches` taking a `match.json` payload, and the handler is
  `radl.phase_trace.convert` — which already validates every closed vocabulary
  and raises naming the offending row. That is the trust boundary; do not add a
  second, looser one in the route.
- Do not expose a write endpoint per action. RADL rows are a published record of
  what happened, and the thing that edits them is the tracer's review pane
  (`tracer/review.py`) operating on `MatchState`, upstream of the export.

## TODO(radl-pydantic) — typed models

Worth having only at the API boundary, and only for the request/response
envelope. The action row itself is already typed by `radl.config.DTYPES`, and a
`BaseModel` per action would be the same duplicate-schema mistake as the ORM
class. If a model is wanted for the row anyway, generate its fields from
`radl.config.COLUMNS` / `DTYPES` rather than restating them.

Note the vocabularies are the natural `Enum`s: `ACTION_TYPES`, `RESULTS`,
`START_REASONS`, `CONTACT_OUTCOMES` — all closed, all already enforced by
`radl.phase_trace._one_of`.

## TODO(radl-vendor) — a second producer

There is no vendor feed today, which is why there is one converter and no
deserializer layer. RADL's spec says as much (`§7, "One producer"`).

When a second arrives (Opta, Stats Perform, a tracking engine):

- It gets its own module in `radl/`, sibling to `phase_trace.py`, converting
  the raw feed straight to the action frame. Do **not** route it through
  phase-trace's `match.json` — that file is phase-trace's export shape, not a
  neutral intermediate, and treating it as one would make every other producer
  inherit phase-trace's quirks.
- Expect it to be the event that separates "the RADL standard" from "what
  phase-trace happens to do". `possession_start_reason`, the `sub_type`
  collapse, and the fixed 100×70 pitch are the three most likely to move.
- kloppy is the reference for how a multi-provider deserializer layer is
  organised, if it ever becomes worth one. It is not worth one for a single
  provider.

## Known gaps this work did not close

- `phase_id`, `contact_outcome`, `freeze_frame` stay null. Nothing in a
  top-down mouse trace can see a breakdown or a defensive shape.
- Missed kicks at goal are still not recorded, so kicking accuracy is not
  computable (`conversion_missed` exists; there is no `penalty_kick_missed`).
- `sin_bin` has no duration and there is no players-on-field count.
- A set piece is one row, not a contest.

All four are `radl/docs/spec-v0.2.md §7` limitations, and all four are producer
limitations rather than schema ones — closing them means tracing more, not
changing the table.
