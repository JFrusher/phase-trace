"""Discipline: penalty reasons + error events."""

from translators.rugby import RugbySport

from tracer import config
from tracer.match_state import MatchState


def test_error_key_logs_action_for_possessing_team():
    m = MatchState("ENG", "WAL")           # possession defaults to home
    m.clock.start(t=0.0)
    m.key_down("e", 60.0)                   # knock-on at 1'
    assert m.actions == [{"type": "error", "kind": "knock_on",
                          "team": "ENG", "minute": 1.0}]


def test_all_three_error_kinds_map():
    m = MatchState("ENG", "WAL")
    m.clock.start(t=0.0)
    m.key_down("e", 0.0)
    m.key_down("w", 0.0)
    m.key_down("h", 0.0)
    assert [a["kind"] for a in m.actions] == ["knock_on", "forward_pass", "handling"]


def test_penalty_reason_attaches_to_the_penalty_event():
    m = MatchState("ENG", "WAL")
    m.clock.start(t=0.0)
    m._tap_origin("f", 30.0)               # F: penalty (home concedes -> WAL wins)
    pen = next(e for e in m.events if e["type"] == config.PENALTY_WON_TYPE)
    assert "reason" not in pen             # absent until the chip is used
    m.choose_penalty_reason("offside")
    assert pen["reason"] == "offside" and m.penalty_reason == "offside"


def test_penalty_with_reason_still_translates():
    # the extra key must not break the validated momentum path
    (std,) = RugbySport().translate(
        [{"type": config.PENALTY_WON_TYPE, "team": "ENG", "minute": 5.0,
          "reason": "high"}])
    assert std.weight == 0.6


def test_error_annotation_does_not_touch_events():
    m = MatchState("ENG", "WAL")
    m.clock.start(t=0.0)
    m.key_down("e", 10.0)
    assert m.events == []                   # errors are action-stream only
