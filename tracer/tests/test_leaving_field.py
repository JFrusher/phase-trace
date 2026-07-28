"""Ball out of play, and the in-goal chooser, through the real MatchState.

The line stopping at the edge of the image used to be the end of it: the
mouseup landed on the document, end_chain never ran, and the possession was
silently dropped. These pin the replacement — the trace itself says the ball
is out — plus what a trace finishing over a try line is taken to mean.
"""

from tracer import config
from tracer.events import compute_score
from tracer.match_state import MatchState

PX = config.PX_PER_M
LEFT = config.IN_GOAL_DEPTH_M * PX
MID_Y = config.PITCH_WIDTH_M * PX / 2


def _trace(m, x0_m, x1_m, t0=100.0, dur=3.0, y=MID_Y, y1=None, n=60):
    y1 = y if y1 is None else y1
    m.mouse_down(LEFT + x0_m * PX, y, t0)
    for i in range(1, n + 1):
        f = i / n
        m.mouse_move(LEFT + (x0_m + (x1_m - x0_m) * f) * PX, y + (y1 - y) * f,
                     t0 + dur * f)
    return t0 + dur


def _match(**kw):
    """Mid-match: a fresh match pends the kickoff, which snaps every start to
    the centre spot and forces a KICK — none of these are restarts."""
    m = MatchState("ENG", "WAL", **kw)
    m.pending_start_reason = None
    m.clock.start(t=100.0)
    return m


# --- out of play ends the play, with no tap --------------------------------
def test_crossing_a_touchline_commits_the_chain_by_itself():
    m = _match()
    _trace(m, 20, 45, y1=-4.0)              # kicked out to the left touchline
    assert not m.recorder.active            # no A tap, no mouseup: still ended
    assert m.last_chain is not None
    assert m.last_origin.reason == "lineout"


def test_crossing_the_dead_ball_line_commits_the_chain_by_itself():
    m = _match()
    _trace(m, 60, 115)                      # kicked through the in-goal
    assert not m.recorder.active
    assert m.last_origin.reason == "drop_out_22"


def test_running_along_the_touchline_keeps_the_chain_alive():
    m = _match()
    inside = config.TOUCH_MARGIN_M * PX     # inside the kick-to-touch margin
    _trace(m, 20, 45, y1=inside)
    assert m.recorder.active                # a winger hugging the line is in play


def test_a_first_flick_cannot_end_a_chain_before_it_has_drawn_anything():
    m = _match()
    m.mouse_down(LEFT + 20 * PX, 2.0, 100.0)
    m.mouse_move(LEFT + 20 * PX, -1.0, 100.1)   # starts on the line, one move
    assert m.recorder.active


# --- the in-goal chooser ----------------------------------------------------
def test_carrying_into_the_in_goal_scores_a_try_and_arms_the_conversion():
    m = _match()
    t = _trace(m, 90, 103)
    m.key_down("a", t)
    assert m.in_goal_choice == "try"
    assert compute_score(m.events, m.team_names) == {"home": 5, "away": 0}
    assert m.last_origin.reason == "restart"
    assert m.last_origin.team == "away"          # they conceded, so they restart
    m.key_down("c", t + 5)
    assert compute_score(m.events, m.team_names) == {"home": 7, "away": 0}


def test_choosing_held_up_takes_the_try_back():
    m = _match()
    t = _trace(m, 90, 103)
    m.key_down("a", t)
    m.choose_in_goal_outcome("held_up")
    assert compute_score(m.events, m.team_names) == {"home": 0, "away": 0}
    assert m.last_origin.reason == "scrum"
    assert m.last_origin.team == "home"          # attacking scrum, 5m out
    assert not [e for e in m.events if e["type"] == "try"]


def test_choosing_try_after_a_drop_out_guess_scores_it():
    m = _match()
    t = _trace(m, 60, 103)                       # a kick into the in-goal
    m.key_down("a", t)
    assert m.in_goal_choice == "drop_out"
    m.choose_in_goal_outcome("try")
    assert compute_score(m.events, m.team_names) == {"home": 5, "away": 0}


def test_a_tapped_try_outranks_the_guess_and_hides_the_chooser():
    # T is explicit input; offering a chooser that cannot overrule it would be
    # a control that lies
    m = _match()
    t = _trace(m, 90, 103)
    m.key_down("t", t)
    m.key_down("a", t + 0.01)
    assert m.in_goal_choice is None
    assert compute_score(m.events, m.team_names) == {"home": 5, "away": 0}
    assert len([e for e in m.events if e["type"] == "try"]) == 1


def test_a_chain_that_stayed_on_the_field_offers_no_chooser():
    m = _match()
    t = _trace(m, 20, 32)
    m.key_down("a", t)
    assert m.in_goal_choice is None


def test_undo_removes_an_inferred_try():
    m = _match()
    t = _trace(m, 90, 103)
    m.key_down("a", t)
    m.undo_last()
    assert m.events == []
    assert compute_score(m.events, m.team_names) == {"home": 0, "away": 0}


# --- halftime ----------------------------------------------------------------
def test_halftime_hands_the_kickoff_to_the_other_side():
    m = _match(possession="home")
    t = _trace(m, 20, 32)
    m.key_down("a", t)                           # possession has moved on
    m.halftime_flip()
    assert m.possession == "away"                # home kicked off the first half
    assert m.pending_start_reason == "kickoff"
    assert m.last_origin.reason == "kickoff"
    assert m.attack_dir_home == -1


def test_halftime_survives_a_resumed_session():
    m = _match(possession="away")
    revived = MatchState.from_dict(m.to_dict())
    revived.halftime_flip()
    assert revived.possession == "home"
