"""What phase-trace records for RADL: period, possession, and located positions.

Two things this pins, both of which used to be somebody else's problem:

  * `period` and `possession` are recorded where they are known -- the halftime
    button, and the team-assigned segments -- rather than re-inferred downstream
    from the shape of the stream;
  * a row's position is only stamped when the position means something.

None of it needs the `radl` package: these are phase-trace's own fields, and
the tracer has to record them whether or not the converter is installed. The
contract with RADL itself is test_radl_contract.py.
"""

from tracer import config, fixtures
from tracer.geometry import PitchCalibration

PX = config.PX_PER_M
LEFT = config.IN_GOAL_DEPTH_M * PX
CENTRE_Y = config.PITCH_WIDTH_M / 2 * PX
CAL = PitchCalibration()


def _trace(m, x0, x1, y, t0, dur, n=40):
    """Draw a straight stroke; leaves the chain OPEN (no end tap)."""
    m.mouse_down(x0, y, t0)
    for i in range(1, n + 1):
        m.mouse_move(x0 + (x1 - x0) * i / n, y, t0 + dur * i / n)
    return t0 + dur


def _carry(m, t0, x0=20, x1=45, y=CENTRE_Y):
    """One committed carry, in field metres."""
    t = _trace(m, LEFT + x0 * PX, LEFT + x1 * PX, y, t0, 0.6)
    m.key_down("a", t + 0.01)
    return t + 0.02


# --- period ----------------------------------------------------------------
def test_period_is_stamped_and_advances_at_halftime():
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="home")
    m.clock.start(t=0.0)
    t = _carry(m, 1.0)
    assert all(a["period"] == 1 for a in m.actions)

    m.halftime_flip()
    assert m.period == 2
    _carry(m, t + 1.0)
    assert {a["period"] for a in m.actions} == {1, 2}


def test_period_survives_a_session_round_trip():
    from tracer.match_state import MatchState

    m = fixtures.open_play_match(home="ENG", away="WAL", possession="home")
    m.halftime_flip()
    assert MatchState.from_dict(m.to_dict()).period == 2


def test_a_session_written_before_period_existed_resumes_in_period_one():
    from tracer.match_state import MatchState

    m = fixtures.open_play_match(home="ENG", away="WAL", possession="home")
    legacy = {k: v for k, v in m.to_dict().items() if k != "period"}
    assert MatchState.from_dict(legacy).period == 1


# --- possession ------------------------------------------------------------
def test_each_chain_is_its_own_possession():
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="home")
    m.clock.start(t=0.0)
    t = _carry(m, 1.0)
    _carry(m, t + 1.0)
    on_ball = [a for a in m.actions if a["type"] in ("carry", "pass", "kick")]
    assert [a["possession"] for a in on_ball] == [1, 2]


def test_a_possession_id_is_never_reused_after_undo():
    """Undo truncates the stream; the numbering has to resume, not restart.

    Two chains that both claimed possession 2 would merge into one on read,
    which is precisely the failure a stamped id is supposed to make impossible.
    """
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="home")
    m.clock.start(t=0.0)
    t = _carry(m, 1.0)
    t = _carry(m, t + 1.0)
    m.undo_last()
    _carry(m, t + 1.0)
    on_ball = [a for a in m.actions if a["type"] in ("carry", "pass", "kick")]
    assert [a["possession"] for a in on_ball] == [1, 2]


def test_a_discrete_event_sits_inside_the_possession_it_interrupted():
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="home")
    m.clock.start(t=0.0)
    t = _trace(m, LEFT + 20 * PX, LEFT + 60 * PX, CENTRE_Y, 1.0, 0.6)
    m.key_down("a", t + 0.01)
    m.key_down("b", t + 0.5)                   # sin bin, between possessions
    binned = [e for e in m.events if e["type"] == "sin_bin"][0]
    assert binned["possession"] == m.actions[-1]["possession"]


# --- located positions only ------------------------------------------------
def test_a_card_carries_no_position():
    """A card is a keystroke, not a place. Stamping the pointer at that moment
    published mouse position as if it were where the offence happened."""
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="home")
    m.clock.start(t=0.0)
    _carry(m, 1.0)
    m.key_down("b", 3.0)
    card = [e for e in m.events if e["type"] == "sin_bin"][0]
    assert "x_m" not in card and "y_m" not in card


def test_a_conversion_carries_no_position():
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="home")
    m.clock.start(t=0.0)
    t = _trace(m, LEFT + 20 * PX, LEFT + 60 * PX, CENTRE_Y, 1.0, 0.6)
    m.key_down("t", t)
    m.key_down("a", t + 0.01)
    m.key_down("c", t + 2.0)
    conv = [e for e in m.events if e["type"] == "conversion"][0]
    assert "x_m" not in conv


def test_a_try_still_carries_where_it_was_scored():
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="home")
    m.clock.start(t=0.0)
    x1 = LEFT + 60 * PX
    t = _trace(m, LEFT + 20 * PX, x1, CENTRE_Y, 1.0, 0.6)
    m.key_down("t", t)
    m.key_down("a", t + 0.01)
    scored = [e for e in m.events if e["type"] == "try"][0]
    assert scored["x_m"] == round(CAL.field_x_m(x1), 1)


def test_every_positioned_row_is_a_located_type():
    m = fixtures.open_play_match(home="ENG", away="WAL", possession="home")
    m.clock.start(t=0.0)
    t = _carry(m, 1.0)
    m.key_down("e", t)                          # error: located
    m.key_down("b", t + 0.5)                    # card: not
    m.key_down("d", t + 1.0)                    # card: not
    for row in [*m.events, *m.actions]:
        if "x_m" in row:
            assert row["type"] in config.LOCATED_EVENT_TYPES, row["type"]
