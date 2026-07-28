"""Fixture generator + injection harness self-tests."""

from tracer import fixtures
from tracer.match_state import MatchState


def test_noisy_path_deterministic():
    a = fixtures.noisy_path(((10, 35), (22, 35)), (3.0,), seed=42)
    b = fixtures.noisy_path(((10, 35), (22, 35)), (3.0,), seed=42)
    c = fixtures.noisy_path(((10, 35), (22, 35)), (3.0,), seed=43)
    assert [(p.x, p.y, p.t) for p in a] == [(p.x, p.y, p.t) for p in b]
    assert [(p.x, p.y, p.t) for p in a] != [(p.x, p.y, p.t) for p in c]


def test_noisy_path_sane():
    pts = fixtures.noisy_path(((10, 35), (22, 35)), (3.0,), seed=7)
    assert all(b.t > a.t for a, b in zip(pts, pts[1:]))
    assert abs(len(pts) - 180) <= 20                          # ~60 Hz for 3s
    assert all(abs(p.y - 35 * fixtures.PX) < 6 for p in pts)  # near ideal line
    assert pts[-1].x > pts[0].x


def test_inject_raw_roundtrip():
    m = fixtures.open_play_match()
    points = [[80, 280, 0.0], [120, 280, 1.0], [160, 280, 2.0]]
    fixtures.inject_raw(m, points, taps=(("9", 0.1),))
    assert m.chain_seq == 1
    assert not m.recorder.active
    assert len(m.events) == 1
    assert m.events[0]["players"] == [{"number": 9, "role": "start"}]


def test_check_catches_wrong_expect():
    sc = fixtures.SCENARIOS["carry_straight"]
    m = fixtures.open_play_match()
    fixtures.inject(m, sc)
    mismatches = fixtures.check(m, {"actions": ["KICK"]})
    assert mismatches and "actions" in mismatches[0]
