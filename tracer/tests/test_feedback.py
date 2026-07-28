"""Correction feedback log: dedup, training-pair extraction, calibrate wiring."""

import math

from tracer import feedback, features, fit


def _line(n, dx, dy):
    """n points from origin stepping (dx, dy) px each — a straight stroke."""
    return [[i * dx, i * dy, i * 0.01] for i in range(n)]


def _reclass(seg, original, corrected, pts):
    return {"kind": "reclassify", "home": "A", "away": "B", "segment_id": seg,
            "attack_dir": 1, "points": pts, "original": original,
            "corrected": corrected}


def test_latest_reclassify_per_segment_wins(tmp_path):
    db = tmp_path / "c.db"
    pts = _line(40, 8, 0)
    feedback.log_correction(_reclass("chain-1#0", "CARRY", "PASS", pts), db=db)
    feedback.log_correction(_reclass("chain-1#0", "PASS", "KICK", pts), db=db)
    xs, labels = feedback.training_pairs(db=db)
    assert labels == ["KICK"]                      # latest wins, one pair only
    assert set(xs[0]) == set(features.FEATURES)    # re-extracted feature dict


def test_distinct_segments_both_kept(tmp_path):
    db = tmp_path / "c.db"
    feedback.log_correction(_reclass("chain-1#0", "CARRY", "KICK", _line(40, 8, 0)), db=db)
    feedback.log_correction(_reclass("chain-2#0", "KICK", "CARRY", _line(20, 8, 0)), db=db)
    _, labels = feedback.training_pairs(db=db)
    assert sorted(labels) == ["CARRY", "KICK"]


def test_hints_and_review_edits_logged_but_not_trained(tmp_path):
    db = tmp_path / "c.db"
    feedback.log_correction({"kind": "hint", "home": "A", "away": "B",
                             "segment_id": "chain-1#0", "attack_dir": 1,
                             "points": _line(30, 8, 0), "original": "CARRY",
                             "corrected": "KICK"}, db=db)
    feedback.log_correction({"kind": "team", "home": "A", "away": "B",
                             "original": "A", "corrected": "B"}, db=db)
    xs, labels = feedback.training_pairs(db=db)
    assert xs == [] and labels == []               # neither hints nor team edits tune
    s = feedback.summary(db=db)
    assert "hint: 1" in s and "team: 1" in s


def test_calibrate_folds_corrections_into_fit(tmp_path):
    db = tmp_path / "c.db"
    feedback.log_correction(_reclass("chain-1#0", "CARRY", "KICK", _line(60, 8, 0)), db=db)
    xs, labels, _ = fit.training_set()
    fx, fl = feedback.training_pairs(db=db)
    assert len(fx) == 1                            # the logged pair reaches training
    params, losses = fit.train(xs + fx, labels + fl, epochs=50, lr=0.2, l2=0.01)
    assert set(params) == set(fit.PARAM_NAMES)
    assert all(math.isfinite(v) for v in params.values())
    assert math.isfinite(losses[-1])


def test_empty_db_yields_no_pairs(tmp_path):
    xs, labels = feedback.training_pairs(db=tmp_path / "empty.db")
    assert xs == [] and labels == []
