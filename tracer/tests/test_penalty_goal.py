"""Penalty at goal: the posts test, and the auto-score it drives.

A kick at goal is judged from the horizontal line alone (a top-down trace
can't see height), so a line crossing the goal line between the uprights is a
successful penalty_kick. Picking `at goal` / `to touch` also forces the next
stroke to a KICK, whatever its shape.
"""

from tracer import config, fixtures
from tracer.continuity import PathPoint, Segment
from tracer.events import compute_score, penalty_at_goal_scored
from tracer.geometry import PitchCalibration

PX = config.PX_PER_M
LEFT = config.IN_GOAL_DEPTH_M * PX
RIGHT_TRY = LEFT + config.PITCH_LENGTH_M * PX   # x of the +x try line
CENTRE_Y = config.PITCH_WIDTH_M / 2 * PX        # between the posts here
CAL = PitchCalibration()


def _kick(x0, x1, y0, y1):
    return Segment(action="KICK", points=[PathPoint(x0, y0, 0.0),
                                          PathPoint(x1, y1, 0.6)])


# --- pure posts geometry ---------------------------------------------------
def test_dead_centre_is_a_goal():
    seg = _kick(RIGHT_TRY - 300, RIGHT_TRY + 40, CENTRE_Y, CENTRE_Y)
    assert penalty_at_goal_scored(seg, 1, CAL) is True


def test_wide_of_the_posts_is_a_miss():
    seg = _kick(RIGHT_TRY - 300, RIGHT_TRY + 40, CENTRE_Y - 80, CENTRE_Y - 80)
    assert penalty_at_goal_scored(seg, 1, CAL) is False


def test_short_of_the_line_is_a_miss():
    # never reaches the goal line, so there is no crossing to judge
    seg = _kick(RIGHT_TRY - 300, RIGHT_TRY - 100, CENTRE_Y, CENTRE_Y)
    assert penalty_at_goal_scored(seg, 1, CAL) is False


def test_mirrored_end_uses_the_left_try_line():
    # a team attacking -x kicks at the left posts
    seg = _kick(LEFT + 200, LEFT - 40, CENTRE_Y, CENTRE_Y)
    assert penalty_at_goal_scored(seg, -1, CAL) is True


def test_edge_of_the_posts_counts():
    half = config.GOAL_WIDTH_M / 2 * PX
    seg = _kick(RIGHT_TRY - 300, RIGHT_TRY + 40, CENTRE_Y + half, CENTRE_Y + half)
    assert penalty_at_goal_scored(seg, 1, CAL) is True


# --- integration through the penalty flow ----------------------------------
def _trace(m, x0, x1, y, t0, dur, n=60):
    m.mouse_down(x0, y, t0)
    for i in range(1, n + 1):
        m.mouse_move(x0 + (x1 - x0) * i / n, y, t0 + dur * i / n)
    return t0 + dur


def _win_penalty_for_home(m, t):
    """AWAY held the ball, so the F tap awards the penalty to HOME."""
    m._tap_origin("f", t)
    assert m.possession == "home"


def test_at_goal_through_the_posts_scores_three_and_restarts():
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="away")
    _win_penalty_for_home(m, 100.0)
    m.choose_penalty_option("at_goal")
    assert m.armed_next_action == "kick_at_goal"
    t = _trace(m, RIGHT_TRY - 320, RIGHT_TRY + 40, CENTRE_Y, 101.0, 0.6)
    m.key_down("a", t)

    assert any(e["type"] == "penalty_kick" and e["team"] == "ENG"
               for e in m.events)
    assert compute_score(m.events, m.team_names) == {"home": 3, "away": 0}
    assert m.last_end_reason == "score"
    assert m.possession == "away"                 # conceding side restarts
    assert m.pending_start_reason == "restart"
    assert m.in_goal_choice is None               # no grounding chooser offered


def test_at_goal_wide_scores_nothing_and_offers_no_chooser():
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="away")
    _win_penalty_for_home(m, 100.0)
    m.choose_penalty_option("at_goal")
    t = _trace(m, RIGHT_TRY - 320, RIGHT_TRY + 40, CENTRE_Y - 120, 101.0, 0.6)
    m.key_down("a", t)

    assert not any(e["type"] == "penalty_kick" for e in m.events)
    assert compute_score(m.events, m.team_names) == {"home": 0, "away": 0}
    assert m.in_goal_choice is None               # a shot is never a grounding


def test_to_touch_forces_a_kick_even_when_short():
    # an 8m straight stroke reads as a carry on geometry; a penalty to touch
    # is a kick, so the option forces it
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="away")
    _win_penalty_for_home(m, 100.0)
    m.choose_penalty_option("kick_to_touch")
    assert m.armed_next_action == "kick_to_touch"
    t = _trace(m, 40 * PX, 48 * PX, CENTRE_Y, 101.0, 1.5)
    m.key_down("a", t)
    assert m.last_chain.segments[0].action == "KICK"
