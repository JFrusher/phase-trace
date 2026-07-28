"""Set-piece outcomes inferred from who fed vs who secured the ball."""

from tracer import config, fixtures
from tracer.events import set_piece_record

PX = config.PX_PER_M
LEFT = config.IN_GOAL_DEPTH_M * PX
NAMES = {"home": "ENG", "away": "WAL"}


def test_won_when_feeding_team_secures():
    assert set_piece_record("lineout", "home", "home", NAMES, 12.4) == {
        "type": "set_piece", "kind": "lineout", "team": "ENG",
        "outcome": "won", "minute": 12.4}


def test_lost_when_opposition_secures():
    r = set_piece_record("scrum", "away", "home", NAMES, 20.0)
    assert r["kind"] == "scrum" and r["team"] == "WAL" and r["outcome"] == "lost"


def test_non_set_piece_reason_returns_none():
    assert set_piece_record("kickoff", "home", "home", NAMES, 0.0) is None
    assert set_piece_record("turnover_open", "home", "away", NAMES, 5.0) is None


def test_lineout_outcome_emitted_on_commit():
    m = fixtures.open_play_match(home="ENG", away="WAL")
    m.pending_start_reason = "lineout"
    m.possession = "home"                 # home throws in
    m.clock.start(t=100.0)
    m.mouse_down(LEFT + 10 * PX, 280, 100.0)
    for i in range(1, 151):               # a short carry, no steal
        m.mouse_move(LEFT + (10 + 10 * i / 150) * PX, 280, 100.0 + 2.5 * i / 150)
    m.key_down("a", 102.6)
    sp = [a for a in m.actions if a["type"] == "set_piece"]
    assert len(sp) == 1
    assert sp[0]["kind"] == "lineout" and sp[0]["outcome"] == "won"
    assert sp[0]["team"] == "ENG"


def test_steal_recorded_when_possession_flipped_mid_set_piece():
    m = fixtures.open_play_match(home="ENG", away="WAL")
    m.pending_start_reason = "lineout"
    m.possession = "home"                 # home throws in
    m.clock.start(t=100.0)
    m.mouse_down(LEFT + 10 * PX, 280, 100.0)
    for i in range(1, 151):
        m.mouse_move(LEFT + (10 + 10 * i / 150) * PX, 280, 100.0 + 2.5 * i / 150)
    m.key_down("x", 101.0)                # away steals it off the top
    m.key_down("a", 102.6)
    sp = [a for a in m.actions if a["type"] == "set_piece"][0]
    assert sp["team"] == "ENG" and sp["outcome"] == "lost"   # ENG threw, lost it
