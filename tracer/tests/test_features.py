"""Exact-value unit tests for the classification feature extractor."""

import math

import pytest

from tracer import config, features
from tracer.continuity import PathPoint

PX = config.PX_PER_M


def path(*legs):
    """PathPoints from (x_m, y_m, t) triples."""
    return [PathPoint(x * PX, y * PX, t) for x, y, t in legs]


# --- extract: base geometry ------------------------------------------------

def test_raw_geometry_forward_carry():
    feats, raw = features.extract(path((0, 0, 0.0), (10, 0, 2.0)), +1)
    assert raw["fwd_m"] == pytest.approx(10.0)
    assert raw["lat_m"] == pytest.approx(0.0)
    assert raw["net_m"] == pytest.approx(10.0)
    assert raw["straightness"] == pytest.approx(1.0)
    assert "dur_s" not in raw  # classification does not measure time


def test_attack_dir_mirrors_forward():
    _, raw = features.extract(path((0, 0, 0.0), (10, 0, 2.0)), -1)
    assert raw["fwd_m"] == pytest.approx(-10.0)


# --- extract: rectified evidence features ----------------------------------

def test_forward_motion_gives_zero_backward_feature():
    feats, _ = features.extract(path((0, 0, 0.0), (10, 0, 2.0)), +1)
    assert feats["backward"] == 0.0


def test_backward_flick_saturates_backward_feature():
    feats, _ = features.extract(path((0, 0, 0.0), (-5, 0, 1.0)), +1)
    assert feats["backward"] == pytest.approx(math.tanh(5 / config.F_BACK_SCALE_M))
    assert feats["backward"] > 0.99


def test_forward_progress_vetoes_lateral_pass():
    # A forward run that also moves sideways is a CARRY, never a PASS.
    # Rugby: a pass cannot gain forward ground, so forward vetoes lateral.
    feats, _ = features.extract(path((0, 0, 0.0), (12, 15, 2.0)), +1)
    assert feats["lateral"] == 0.0
    assert feats["backward"] == 0.0
    _, _, action, _ = features.score(feats)
    assert action == "CARRY"


def test_steep_forward_cut_is_carry():
    feats, _ = features.extract(path((0, 0, 0.0), (8, 14, 2.0)), +1)
    _, _, action, _ = features.score(feats)
    assert action == "CARRY"


def test_square_pass_fires_lateral():
    # near-zero forward, big lateral: a square pass, still PASS
    feats, _ = features.extract(path((0, 0, 0.0), (0.5, 10, 2.0)), +1)
    assert feats["lateral"] > 0.5
    _, _, action, _ = features.score(feats)
    assert action == "PASS"


def test_no_time_features():
    # classification must not measure draw time: no pace/speed features exist
    assert "relpace" not in features.FEATURES
    assert "bursty" not in features.FEATURES
    assert set(features.FEATURES) == {"backward", "lateral", "straight", "dist", "bent"}


# --- extract: quality features ---------------------------------------------

def test_straightness_of_straight_leg():
    feats, raw = features.extract(path((0, 0, 0.0), (10, 0, 2.0)), +1)
    assert raw["straightness"] == pytest.approx(1.0)
    expected = math.tanh((1.0 - config.F_STRAIGHT_CENTER) / config.F_STRAIGHT_SCALE)
    assert feats["straight"] == pytest.approx(expected)


def test_long_bent_stroke_is_not_a_kick():
    # 32m net displacement but a shallow bend (straightness ~0.85): a running
    # break, not a kick. Length alone must not clear the kick threshold.
    bent = path((0, 0, 0.0), (16, 9.87, 1.0), (32, 0, 2.0))
    feats, raw = features.extract(bent, +1)
    assert raw["straightness"] == pytest.approx(0.85, abs=0.02)
    assert feats["bent"] > 0
    assert features.score(feats)[2] == "CARRY"


def test_long_straight_stroke_is_a_kick():
    # same 32m, dead straight: bent veto is 0, distance carries it to KICK.
    straight = path((0, 0, 0.0), (16, 0, 1.0), (32, 0, 2.0))
    feats = features.extract(straight, +1)[0]
    assert feats["bent"] == 0.0
    assert features.score(feats)[2] == "KICK"


def test_straightness_of_l_shape():
    feats, raw = features.extract(
        path((0, 0, 0.0), (5, 0, 1.0), (5, 5, 2.0)), +1)
    assert raw["straightness"] == pytest.approx(math.hypot(5, 5) / 10.0, abs=5e-4)
    assert feats["straight"] < 0


def test_dist_feature():
    feats, _ = features.extract(path((0, 0, 0.0), (10, 0, 2.0)), +1)
    assert feats["dist"] == pytest.approx(math.tanh(10 / config.F_DIST_SCALE_M))


# --- extract: degenerate inputs --------------------------------------------

def test_zero_duration_is_defined():
    # identical timestamps must not break anything (time is unused anyway)
    feats, raw = features.extract(path((0, 0, 1.0), (10, 0, 1.0)), +1)
    assert raw["net_m"] == pytest.approx(10.0)
    for v in feats.values():
        assert math.isfinite(v)


def test_stationary_path_is_defined():
    feats, raw = features.extract(path((3, 3, 0.0), (3, 3, 1.0)), +1)
    assert raw["net_m"] == 0.0
    for v in feats.values():
        assert math.isfinite(v)


def test_two_point_path_straightness_is_one():
    _, raw = features.extract(path((0, 0, 0.0), (4, 3, 1.0)), +1)
    assert raw["straightness"] == pytest.approx(1.0)


def test_feature_names_complete():
    feats, _ = features.extract(path((0, 0, 0.0), (10, 0, 2.0)), +1)
    assert set(feats) == set(features.FEATURES)


# --- score ------------------------------------------------------------------

def zero_features():
    return dict.fromkeys(features.FEATURES, 0.0)


def test_score_default_is_carry():
    scores, probs, action, confidence = features.score(zero_features())
    assert action == "CARRY"
    assert scores["CARRY"] == 0.0
    assert scores["PASS"] == pytest.approx(config.B_PASS)
    assert scores["KICK"] == pytest.approx(config.B_KICK)
    assert sum(probs.values()) == pytest.approx(1.0)
    assert 0 < confidence < 1


def test_score_carry_wins_ties(monkeypatch):
    monkeypatch.setattr(config, "B_PASS", 0.0)
    monkeypatch.setattr(config, "B_KICK", 0.0)
    _, probs, action, confidence = features.score(zero_features())
    assert action == "CARRY"
    assert probs["CARRY"] == pytest.approx(1 / 3)
    assert confidence == pytest.approx(0.0)


def test_score_saturated_backward_is_pass():
    feats = zero_features()
    feats["backward"] = 1.0
    _, probs, action, confidence = features.score(feats)
    assert action == "PASS"
    assert probs["PASS"] > 0.99
    assert confidence > 0.98


def test_score_long_straight_is_kick():
    feats = zero_features()
    feats["dist"] = 1.0       # far
    feats["straight"] = 1.0   # straight
    _, _, action, _ = features.score(feats)
    assert action == "KICK"


def test_score_reads_config_live(monkeypatch):
    # sweep/fit setattr must take effect without reimport
    feats = zero_features()
    feats["dist"] = 1.0
    monkeypatch.setattr(config, "W_KICK_DIST", 50.0)
    _, _, action, _ = features.score(feats)
    assert action == "KICK"
