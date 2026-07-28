"""Scored classification contracts.

The old cascade-parity fence was retired with the pace-invariant rework: it
pinned a wall-clock KICK rule that was itself the bug. Pace-invariance is now
pinned by tests/test_pace_invariance.py; this file pins the scoring contract
(scores/probs/confidence shape and the obvious geometric calls).
"""

import pytest

from tracer import features, fixtures
from tracer.match_state import MatchState


def run_scenario(sc):
    m = fixtures.open_play_match(sc.attack_dir, sc.possession)
    fixtures.inject(m, sc)
    return m


def test_segments_carry_scores_and_confidence():
    m = run_scenario(fixtures.SCENARIOS["carry_pass_carry_kick"])
    for seg in m.last_chain.segments:
        assert set(seg.scores) == {"CARRY", "PASS", "KICK"}
        assert seg.scores["CARRY"] == 0.0
        assert 0.0 <= seg.confidence <= 1.0


def test_evidence_has_score_breakdown():
    m = run_scenario(fixtures.SCENARIOS["carry_straight"])
    ev = m.last_debug["segments"][0]
    for key in ("features", "scores", "probs", "confidence", "action_geo",
                "rule", "net_m"):
        assert key in ev
    assert set(ev["features"]) == set(features.FEATURES)
    assert ev["rule"]
    assert sum(ev["probs"].values()) == pytest.approx(1.0, abs=2e-3)  # display-rounded


def test_obvious_geometric_calls():
    assert run_scenario(fixtures.SCENARIOS["carry_straight"]) \
        .last_chain.segments[0].action == "CARRY"
    assert run_scenario(fixtures.SCENARIOS["pass_backward"]) \
        .last_chain.segments[0].action == "PASS"
    assert run_scenario(fixtures.SCENARIOS["kick_long"]) \
        .last_chain.segments[0].action == "KICK"


def test_decisive_calls_have_high_confidence():
    m = run_scenario(fixtures.SCENARIOS["pass_backward"])
    assert m.last_chain.segments[0].confidence > 0.95


def test_hint_overrides_action_but_not_geometry():
    m = run_scenario(fixtures.SCENARIOS["hint_k"])
    assert m.last_chain.segments[0].action == "KICK"          # hint applied
    assert m.last_debug["segments"][0]["action_geo"] == "CARRY"  # geometry kept
