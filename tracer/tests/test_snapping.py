"""Start-snapping: the new possession begins on the mark the last one left.

The whole path is shifted onto the mark, not just its first point, so a sloppy
press near the mark can't grow a phantom leg between the mark and where the
trace really started. Reasons that are inherently a drop kick also force the
first segment to KICK regardless of how short it was drawn.
"""

from tracer import config, fixtures
from tracer.events import ChainOrigin, halfway_mark

PX = config.PX_PER_M
LEFT = config.IN_GOAL_DEPTH_M * PX


def test_press_within_tolerance_snaps_onto_the_origin_mark():
    m = fixtures.open_play_match()
    m.last_origin = ChainOrigin("lineout", "home", (400.0, 100.0))
    m.pending_start_reason = "lineout"
    # press 6.25m off the mark (< SNAP_TOLERANCE_M): aimed at it, so it snaps
    assert m.mouse_down(360.0, 70.0, 100.0) == (400.0, 100.0)


def test_press_beyond_tolerance_is_taken_as_pressed():
    m = fixtures.open_play_match()
    m.last_origin = ChainOrigin("lineout", "home", (400.0, 100.0))
    m.pending_start_reason = "lineout"
    # 22.5m off the mark (> SNAP_TOLERANCE_M): a deliberate free start, no snap,
    # so one wild click can't drag the whole trace onto the mark
    assert m.mouse_down(300.0, 250.0, 100.0) == (300.0, 250.0)


def test_pending_mark_exposes_the_snap_target():
    m = fixtures.open_play_match()
    m.last_origin = ChainOrigin("lineout", "home", (400.0, 100.0))
    m.pending_start_reason = "lineout"
    assert m.pending_mark == (400.0, 100.0)     # what chips._target draws


def test_whole_path_shifts_by_the_snap_vector():
    m = fixtures.open_play_match()
    m.last_origin = ChainOrigin("turnover_open", "away", (400.0, 100.0))
    m.pending_start_reason = "turnover_open"
    m.mouse_down(360.0, 70.0, 100.0)           # snap vector = (+40, +30)
    assert m.mouse_move(370.0, 70.0, 100.1) == (410.0, 100.0)


def test_initial_kickoff_falls_back_to_halfway():
    m = fixtures.open_play_match()
    m.last_origin = None
    m.pending_start_reason = "kickoff"
    cx, cy = halfway_mark(m.cal)
    assert m.mouse_down(cx - 50, cy - 30, 0.0) == (cx, cy)


def test_no_mark_no_snap():
    m = fixtures.open_play_match()          # pending reason cleared, no origin
    assert m.mouse_down(300.0, 250.0, 0.0) == (300.0, 250.0)


def test_short_drop_out_22_is_forced_to_a_kick():
    # an 8m straight stroke reads as a carry, but a 22 drop-out is a drop kick
    m = fixtures.open_play_match()
    m.pending_start_reason = "drop_out_22"
    m.mouse_down(25 * PX, 280, 100.0)
    for i in range(1, 61):
        m.mouse_move((25 + 8 * i / 60) * PX, 280, 100.0 + 1.5 * i / 60)
    m.key_down("a", 101.5)
    assert m.last_chain.segments[0].action == "KICK"
