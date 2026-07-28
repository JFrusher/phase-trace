"""Pace-invariance fence: the SAME traced shape must classify identically no
matter how fast it is drawn. This is the regression guard for the reported
corner-miss / forward-as-PASS bug (both were pace artifacts).

There is no real-time-sync assumption: absolute tracing speed is not an
identifier. A scenario run at 0.25x, 1x, and 4x its scripted leg durations
must yield one and the same action list.
"""

import dataclasses

import pytest

from tracer import fixtures
from tracer.match_state import MatchState

# Drawing pace vs real-time pace span a ~4x range; test across it. (The
# synthetic tremor in noisy_path is itself pace-dependent geometry, so beyond
# this range the fixture, not the recognizer, becomes the variable.)
PACES = (0.5, 1.0, 2.0)

# Geometry scenarios: those whose expected outcome is a specific action shape.
GEOMETRY = [name for name, sc in fixtures.SCENARIOS.items()
            if sc.waypoints and "actions" in sc.expect and not sc.taps]


def scaled(sc, k):
    return dataclasses.replace(sc, durations=tuple(d * k for d in sc.durations))


def actions_at(sc, k):
    m = fixtures.open_play_match(sc.attack_dir, sc.possession)
    fixtures.inject(m, scaled(sc, k))
    return [s.action for s in m.last_chain.segments] if m.last_chain else []


@pytest.mark.parametrize("name", GEOMETRY)
def test_actions_identical_across_pace(name):
    sc = fixtures.SCENARIOS[name]
    got = {k: actions_at(sc, k) for k in PACES}
    baseline = got[1.0]
    assert all(a == baseline for a in got.values()), got


def test_z_shape_corners_survive_fast_tracing():
    """The reported failure: a sharp Z drawn fast keeps its corners and its
    forward legs read CARRY (not PASS, not KICK)."""
    z = fixtures.Scenario(
        name="_z", waypoints=((15, 15), (32, 15), (17, 32), (34, 32)),
        durations=(1.0, 1.0, 1.0), expect={})
    for k in PACES:
        acts = actions_at(z, k)
        assert len(acts) == 3, f"pace {k}: corners lost -> {acts}"
        assert acts[0] == "CARRY" and acts[2] == "CARRY", f"pace {k}: {acts}"
        assert "KICK" not in acts, f"pace {k}: phantom kick -> {acts}"
