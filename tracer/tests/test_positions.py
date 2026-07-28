"""Every located thing carries a pitch position.

Carries/passes/kicks always had absolute coordinates; this pins the widening
that gives the discrete events (penalty, try, turnover, error, ...) an x_m/y_m
too — stamped from where the ball was when they were tapped — and the
positions.csv / match.json that expose them for heatmaps.
"""

import csv
import json

from tracer import config, fixtures
from tracer.geometry import PitchCalibration
from tracer.raw_export import export_raw, position_rows
from tracer.validate import validate_events

PX = config.PX_PER_M
LEFT = config.IN_GOAL_DEPTH_M * PX
CENTRE_Y = config.PITCH_WIDTH_M / 2 * PX      # 35 m
CAL = PitchCalibration()


def _trace(m, x0, x1, y, t0, dur, n=40):
    """Draw a straight stroke; leaves the chain OPEN (no end tap)."""
    m.mouse_down(x0, y, t0)
    for i in range(1, n + 1):
        m.mouse_move(x0 + (x1 - x0) * i / n, y, t0 + dur * i / n)
    return t0 + dur


def test_try_tap_stamps_the_pointer_position():
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="home")
    x1 = LEFT + 60 * PX                       # field 60 m
    t = _trace(m, LEFT + 20 * PX, x1, CENTRE_Y, 1.0, 0.6)
    m.key_down("t", t)                        # try, tapped mid-trace
    m.key_down("a", t + 0.01)                 # commit the carry

    tries = [e for e in m.events if e["type"] == "try"]
    assert tries and tries[0]["x_m"] == round(CAL.field_x_m(x1), 1)
    assert tries[0]["y_m"] == round(CAL.field_y_m(CENTRE_Y), 1)


def test_penalty_won_stamps_where_it_was_won():
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="away")
    x1 = LEFT + 45 * PX
    t = _trace(m, LEFT + 30 * PX, x1, CENTRE_Y, 1.0, 0.5)
    m._tap_origin("f", t)                     # AWAY held it -> penalty to HOME

    pens = [e for e in m.events if e["type"] == "penalty_won"]
    assert pens and pens[0]["x_m"] == round(CAL.field_x_m(x1), 1)
    assert pens[0]["team"] == m.team_names["home"]        # AWAY conceded -> HOME won
    assert pens[0]["conceded_by"] == m.team_names["away"]  # the side that gave it away


def test_error_tap_stamps_position():
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="home")
    x1 = LEFT + 25 * PX
    t = _trace(m, LEFT + 20 * PX, x1, CENTRE_Y, 1.0, 0.5)
    m.key_down("e", t)                        # knock-on, tapped mid-trace
    errs = [a for a in m.actions if a["type"] == "error"]
    assert errs and errs[0]["x_m"] == round(CAL.field_x_m(x1), 1)


def test_line_actions_keep_their_coordinates():
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="home")
    _trace(m, LEFT + 20 * PX, LEFT + 40 * PX, CENTRE_Y, 1.0, 1.2)
    m.key_down("a", 2.3)
    carries = [a for a in m.actions if a["type"] == "carry"]
    assert carries and all(k in carries[0] for k in
                           ("start_x_m", "start_y_m", "end_x_m", "end_y_m"))


def test_export_writes_positions_csv_and_json(tmp_path):
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="home")
    x1 = LEFT + 55 * PX
    t = _trace(m, LEFT + 20 * PX, x1, CENTRE_Y, 1.0, 0.8)
    m.key_down("t", t)                        # a try with a position
    m.key_down("a", t + 0.01)

    out = export_raw(tmp_path, {"date": "", "competition": ""},
                     m.team_names, m.events, m.actions)
    with open(tmp_path / "positions.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    types = {r["type"] for r in rows}
    assert "try" in types                                        # discrete located
    assert types & {"carry", "pass", "kick"}                     # line action located too
    a_try = next(r for r in rows if r["type"] == "try")
    assert a_try["x_m"] and a_try["y_m"]

    payload = json.loads((tmp_path / "match.json").read_text(encoding="utf-8"))
    j_try = next(a for a in payload["actions"] if a["type"] == "try")
    assert "x_m" in j_try and "y_m" in j_try
    assert out == str(tmp_path)


def test_position_stamp_does_not_break_the_momentum_path():
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="home")
    t = _trace(m, LEFT + 20 * PX, LEFT + 50 * PX, CENTRE_Y, 1.0, 0.8)
    m.key_down("t", t)
    m.key_down("a", t + 0.01)
    # extra x_m/y_m keys must stay invisible to the validated momentum export
    assert validate_events(m.events, "ENG", "WAL") == []


def _open_second_half(possession="home"):
    """A match flipped to the second half, with the kickoff snap/force cleared
    so a bare trace is judged on geometry the same way open_play_match is."""
    m = fixtures.open_play_match(home="ENG", away="WAL", possession=possession)
    m.halftime_flip()
    m.possession = possession
    m.pending_start_reason = None
    m.last_origin = None
    m.armed_next_action = None
    return m


def test_second_half_folds_positions_into_first_half_frame():
    m = _open_second_half()
    # forward run for a second-half HOME (who now attacks -x on screen)
    x0, x1 = LEFT + 50 * PX, LEFT + 30 * PX
    t = _trace(m, x0, x1, CENTRE_Y, 1.0, 1.0)
    m.key_down("t", t)                       # a try at the end point
    m.key_down("a", t + 0.01)

    act = next(a for a in m.actions if a["type"] in ("carry", "pass", "kick"))
    # coordinates folded 180deg into the first-half frame: x->100-x, y->70-y
    assert act["start_x_m"] == round(config.PITCH_LENGTH_M - CAL.field_x_m(x0), 1)
    assert act["end_x_m"] == round(config.PITCH_LENGTH_M - CAL.field_x_m(x1), 1)
    assert act["start_y_m"] == round(config.PITCH_WIDTH_M - CAL.field_y_m(CENTRE_Y), 1)
    # attack_dir reported in the canonical (first-half) sense: HOME attacks +x
    assert act["attack_dir"] == 1
    # metres stay physically correct (this was a forward run)
    assert act["metres_gained"] == 20.0
    # a discrete event folds identically
    a_try = next(e for e in m.events if e["type"] == "try")
    assert a_try["x_m"] == round(config.PITCH_LENGTH_M - CAL.field_x_m(x1), 1)


def test_first_half_positions_are_not_folded():
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="home")
    x0 = LEFT + 30 * PX
    t = _trace(m, x0, LEFT + 50 * PX, CENTRE_Y, 1.0, 1.0)
    m.key_down("a", t + 0.01)
    act = next(a for a in m.actions if a["type"] in ("carry", "pass", "kick"))
    assert act["start_x_m"] == round(CAL.field_x_m(x0), 1)      # raw, unfolded
    assert act["attack_dir"] == 1


def test_canonical_orientation_survives_a_resumed_session():
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="home")
    m.halftime_flip()
    revived = m.__class__.from_dict(m.to_dict())
    assert revived._flipped() is True                          # still folding after resume
    assert revived.canon_attack_dir_home == m.canon_attack_dir_home


def test_position_rows_skips_the_unlocated():
    stream = [{"type": "carry", "team": "ENG", "minute": 1, "start_x_m": 5.0,
               "start_y_m": 5.0, "end_x_m": 9.0, "end_y_m": 6.0},
              {"type": "sin_bin", "team": "WAL", "minute": 2},            # no position
              {"type": "penalty_won", "team": "ENG", "minute": 3, "x_m": 40.0, "y_m": 30.0}]
    rows = position_rows(stream)
    assert {r["type"] for r in rows} == {"carry", "penalty_won"}          # sin_bin dropped
    assert next(r for r in rows if r["type"] == "carry")["x_m"] == 5.0    # start is the point
