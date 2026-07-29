"""The contract with RADL: shared vocabularies, and a lossless round trip.

Everything here needs the optional `radl` package (`pip install -e ../RADL`),
so the whole module skips without it -- which is why the checks that do NOT
need it live in test_vocab_parity.py and test_radl.py instead.

Two halves:

  * **parity** -- constants that exist in both repos and must stay equal.
    Holding them equal in a test rather than importing radl from tracer/config
    is what keeps phase-trace installable without a sibling checkout.
  * **round trip** -- a traced match exported and read back as an action frame,
    with nothing null that phase-trace actually knew. Schema drift shows up as
    nulls long before it shows up as an exception.
"""

import csv
import json

import pandas as pd
import pytest

from tracer import config, fixtures
from tracer.raw_export import export_raw
from tracer.radl_export import RADL_CSV
from tracer.tests.test_radl import CENTRE_Y, LEFT, PX, _carry, _trace

radl = pytest.importorskip("radl",
                           reason="radl not installed (pip install -e .[radl])")


# --- vocabulary parity ------------------------------------------------------
def test_start_reasons_match_radl():
    assert sorted(config.START_REASONS) == sorted(radl.config.START_REASONS)


def test_located_event_types_match_radl():
    assert sorted(config.LOCATED_EVENT_TYPES) == sorted(
        radl.config.LOCATED_EVENT_TYPES)


def test_points_match_radl():
    assert config.POINTS == radl.config.POINTS


def test_pitch_dimensions_match_radl():
    assert (config.PITCH_LENGTH_M, config.PITCH_WIDTH_M, config.IN_GOAL_DEPTH_M) == (
        radl.config.PITCH_LENGTH_M, radl.config.PITCH_WIDTH_M,
        radl.config.IN_GOAL_DEPTH_M)


def test_penalty_reasons_are_a_radl_sub_type():
    assert sorted(config.PENALTY_REASONS) == sorted(
        radl.config.SUB_TYPES["penalty_won"])


def test_error_kinds_are_a_radl_sub_type():
    assert sorted(config.ERROR_KEYS.values()) == sorted(radl.config.SUB_TYPES["error"])


def test_set_piece_reasons_are_a_radl_sub_type():
    assert sorted(config.SET_PIECE_REASONS) == sorted(
        radl.config.SUB_TYPES["set_piece"])


def test_every_type_phase_trace_can_log_is_a_radl_action_type():
    """The dead-data guard, pointed the other way.

    A new key in DISCRETE_EVENT_KEYS that RADL has never heard of would export,
    then blow up the converter at the end of a real match. Fail here instead.
    """
    emitted = {*config.DISCRETE_EVENT_KEYS.values(),
               *config.CONVERSION_KEYS.values(), config.PENALTY_WON_TYPE,
               "set_piece", "error", "carry", "pass", "kick"}
    for etype in emitted:
        assert etype in radl.config.ACTION_TYPES, etype


def test_every_contact_outcome_phase_trace_can_state_is_a_radl_one():
    """Only held_up today. The rest of RADL's vocabulary stays unproduced because
    nothing in a top-down line states that a ruck or maul formed at all -- see
    _emit_chain. This is the guard for when that changes."""
    emitted = {o for o in config.IN_GOAL_OUTCOMES
               if o in radl.config.CONTACT_OUTCOMES}
    assert emitted == {"held_up"}
    for outcome in emitted:
        assert outcome in radl.config.CONTACT_OUTCOMES


def test_the_spec_version_the_converter_reports_is_the_installed_one():
    """SPEC_VERSION reaches an operator inside every rejection message, so a
    stale one names a version that was never published."""
    assert radl.SPEC_VERSION == radl.config.SPEC_VERSION
    assert radl.config.SPEC_VERSION.count(".") == 2


# --- the round trip ---------------------------------------------------------
def _exported_match(tmp_path):
    """A short traced match on disk: two possessions, a try, a conversion.

    Opens on a scrum tap rather than bare open play, so possession 1 has a named
    origin the way every possession in a real trace does -- the tracer either
    infers the reason from the previous chain's geometry or is told it.
    """
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="away")
    m.clock.start(t=0.0)
    m.key_down("s", 0.5)                        # scrum to ENG, attacking +x
    t = _carry(m, 1.0, x0=20, x1=45)
    t = _trace(m, LEFT + 45 * PX, LEFT + 104 * PX, CENTRE_Y, t + 1.0, 0.9)
    m.key_down("t", t)
    m.key_down("a", t + 0.01)
    m.key_down("c", t + 2.0)
    out = tmp_path / "ENG_v_WAL"
    export_raw(out, {"date": "2026-07-29", "competition": "Test"},
               m.team_names, m.events, m.actions)
    return m, out


def _held_up_match(tmp_path):
    """A carry into the in-goal, ruled held up by the chooser."""
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="away")
    m.clock.start(t=0.0)
    m.key_down("s", 0.5)                        # scrum to ENG, attacking +x
    t = _trace(m, LEFT + 80 * PX, LEFT + 104 * PX, CENTRE_Y, 1.0, 0.9)
    m.key_down("a", t)
    m.choose_in_goal_outcome("held_up")
    out = tmp_path / "ENG_v_WAL_heldup"
    export_raw(out, {"date": "2026-07-29", "competition": "Test"},
               m.team_names, m.events, m.actions)
    return m, out


def test_held_up_survives_the_round_trip_onto_the_carry_it_ended(tmp_path):
    """contact_outcome's first producer, end to end. Before this the column was
    null in every row of every export, and a held-up carry was indistinguishable
    from any other attacking 5m scrum."""
    _, out = _held_up_match(tmp_path)
    frame = radl.read_match(out / "match.json")

    held = frame[frame.contact_outcome == "held_up"]
    assert len(held) == 1
    assert held.iloc[0].action_type == "carry"
    # independent of result: a carry held up over the line is not a failed carry
    assert pd.isna(held.iloc[0].result)


def test_export_writes_a_radl_frame(tmp_path):
    _, out = _exported_match(tmp_path)
    assert (out / RADL_CSV).exists()
    with open(out / RADL_CSV, encoding="utf-8") as f:
        header = next(csv.reader(f))
    assert header == radl.config.COLUMNS


def test_the_frame_round_trips_without_schema_drift(tmp_path):
    _, out = _exported_match(tmp_path)
    frame = radl.read_match(out / "match.json")
    payload = json.loads((out / "match.json").read_text(encoding="utf-8"))
    assert list(frame.columns) == radl.config.COLUMNS
    assert str(frame.period.dtype) == "Int8"
    assert str(frame.possession_id.dtype) == "Int32"
    # one row in, one row out: the converter drops nothing and invents nothing
    assert len(frame) == len(payload["actions"])


def test_nothing_phase_trace_knew_is_null_after_the_round_trip(tmp_path):
    """Every column here is something the tracer recorded for every row it
    wrote; a null means a field was renamed, dropped, or stopped being stamped
    somewhere between MatchState and the frame."""
    _, out = _exported_match(tmp_path)
    frame = radl.read_match(out / "match.json")
    for column in ("match_id", "period", "time_min", "team", "action_type",
                   "possession_id"):
        assert frame[column].notna().all(), column

    on_ball = frame[frame.action_type.isin(radl.config.ON_BALL_ACTION_TYPES)]
    assert not on_ball.empty
    for column in ("start_x", "start_y", "end_x", "end_y", "attack_dir",
                   "metres_gained", "end_metres_from_line",
                   "possession_start_reason"):
        assert on_ball[column].notna().all(), column


def test_the_score_survives_the_round_trip(tmp_path):
    """The one end-to-end assertion that spans both models: what the tracer
    thinks the score is, and what RADL computes from the published rows."""
    from tracer.events import compute_score

    m, out = _exported_match(tmp_path)
    traced = compute_score(m.events, m.team_names)
    frame_score = radl.score(radl.read_match(out / "match.json"))
    assert frame_score.get("ENG", 0) == traced["home"]
    assert frame_score.get("WAL", 0) == traced["away"]


def test_period_and_possession_come_from_the_data_not_a_guess(tmp_path):
    """`halftime_minute` is the fallback path. With a stamped period the
    converter must not need it, and must not be overridden by it."""
    _, out = _exported_match(tmp_path)
    assert (radl.read_match(out / "match.json").period == 1).all()
    # the whole match sits before this minute, so a minute-based split would
    # also say 1 -- pass an absurd one, and only a stamped period still holds
    assert (radl.read_match(out / "match.json", halftime_minute=-1).period == 1).all()
