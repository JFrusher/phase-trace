"""Handoff inference: who has the ball for the next chain, and why.

infer_next_possession is pure; the integration tests drive the real
end_chain path so the reason cue and score override are exercised too.
"""

from tracer import config
from tracer.events import compute_score, infer_next_possession
from tracer import fixtures
from tracer.match_state import MatchState

PX = config.PX_PER_M
LEFT = config.IN_GOAL_DEPTH_M * PX


# --- pure inference table --------------------------------------------------
def test_score_hands_the_ball_to_the_conceding_team_to_restart():
    # possession means who HAS the ball, and the side that conceded takes the
    # drop kick — scored_team decides that even when the scoring kick already
    # flipped possession in-chain
    assert infer_next_possession("home", "away", "home") == "away"
    assert infer_next_possession("away", "home", "away") == "home"


def test_kick_or_interception_uses_in_chain_flip():
    assert infer_next_possession("home", "away", None) == "away"
    assert infer_next_possession("away", "home", None) == "home"


def test_plain_end_is_a_turnover_to_the_other_side():
    assert infer_next_possession("home", "home", None) == "away"
    assert infer_next_possession("away", "away", None) == "home"


# --- integration through end_chain -----------------------------------------
def _trace(m, x0_m, x1_m, t0, dur, n=60):
    m.mouse_down(LEFT + x0_m * PX, 280, t0)
    for i in range(1, n + 1):
        m.mouse_move(LEFT + (x0_m + (x1_m - x0_m) * i / n) * PX, 280,
                     t0 + dur * i / n)
    return t0 + dur


def test_carry_end_hands_ball_over_as_turnover():
    m = fixtures.open_play_match(home="ENG", away="WAL")   # a carry in open play
    m.clock.start(t=100.0)
    t = _trace(m, 10, 22, 100.0, 3.0)      # ~12m carry, tackled
    m.key_down("a", t)
    assert m.possession == "away"
    assert m.last_end_reason == "turnover"


def test_kick_end_flips_and_reads_as_kick():
    m = fixtures.open_play_match(home="ENG", away="WAL")   # a kick from open play
    m.clock.start(t=100.0)
    t = _trace(m, 30, 68, 100.0, 0.6)      # ~38m kick
    m.key_down("a", t)
    assert m.possession == "away"
    assert m.last_end_reason == "kick"


def test_drop_goal_gives_the_restart_to_the_conceding_side_and_scores():
    m = MatchState("ENG", "WAL")
    m.clock.start(t=100.0)
    t = _trace(m, 30, 68, 100.0, 0.6)      # home kicks (would flip to away)
    m.key_down("g", t)                     # ...but it's a drop goal by home
    m.key_down("a", t + 0.01)
    assert m.possession == "away"          # away conceded, so away restarts
    assert m.last_end_reason == "score"
    assert compute_score(m.events, m.team_names) == {"home": 3, "away": 0}
