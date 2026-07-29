"""Single-path segmentation cases with known ground truth.

Paths are built leg by leg at a 60 Hz mousemove rate. Classification reads
geometry, not speed: a carry is a shorter run, a pass a backward/lateral
flick, a kick a long straight stroke. Durations only set point timing;
pace-invariance is pinned separately in test_pace_invariance.py. PX_PER_M
converts the metre-based leg specs into pixel coordinates.

These cover one path at a time. The full-chain corpus is fixtures.SCENARIOS,
replayed through a real MatchState by test_corpus.py.
"""

import math

from tracer import config, segmentation
from tracer.continuity import PathPoint
from tracer.keystate import TapEvent
from tracer.segmentation import apply_taps, segment_path

PX = config.PX_PER_M


def leg(points, x0, y0, x1, y1, duration_s, hz=60):
    """Append a straight leg (metres) from (x0,y0) to (x1,y1) taking duration_s."""
    t0 = points[-1].t if points else 0.0
    n = max(2, int(duration_s * hz))
    start = 0 if points else -1  # skip duplicating the shared corner point
    for i in range(start + 1, n + 1):
        f = i / n
        points.append(PathPoint(
            (x0 + (x1 - x0) * f) * PX,
            (y0 + (y1 - y0) * f) * PX,
            t0 + duration_s * f,
        ))
    return points


def actions(segments):
    return [s.action for s in segments]


def test_should_flip_gates_kick_on_confidence():
    sf = segmentation._should_flip
    assert sf("KICK", 0.5, forced=False) is True
    assert sf("KICK", 0.01, forced=False) is False   # near-tie kick: frame held
    assert sf("KICK", 0.01, forced=True) is True      # forced (kickoff) always
    assert sf("KICK", None, forced=False) is True     # unset -> flips (legacy)
    assert sf("CARRY", 0.9, forced=False) is False


def test_reclassify_downstream_reframes_after_toggling_kick_off():
    p = []
    leg(p, 30, 35, 60, 35, 0.5)     # KICK, flips the frame
    leg(p, 60, 35, 50, 34, 2.5)     # -10x: forward for the receiver -> CARRY
    segs = segment_path(p, 1)
    assert actions(segs) == ["KICK", "CARRY"]
    # operator: that wasn't a kick. Toggle it off and re-derive downstream.
    segs[0].action = "CARRY"
    segs[0].flips_possession = False
    segmentation.reclassify_downstream(segs, base_dir=1, start_index=0)
    assert segs[1].action == "PASS"  # no flip now: -10x reads backward


def test_carry_pass_carry_kick():
    p = []
    leg(p, 10, 35, 20, 35, 2.5)          # carry: 10m forward at 4 m/s
    leg(p, 20, 35, 19, 43, 0.45)         # pass: 8m lateral, 1m back, quick flick
    leg(p, 19, 43, 31, 43, 3.0)          # carry: 12m forward
    leg(p, 31, 43, 71, 38, 0.5)          # kick: 40m downfield in half a second
    assert actions(segment_path(p, 1)) == ["CARRY", "PASS", "CARRY", "KICK"]


def test_jittery_carry_stays_one_segment():
    p = []
    leg(p, 10, 35, 22, 35, 3.0)
    jittered = [PathPoint(pt.x, pt.y + 2 * PX / 8 * math.sin(2 * math.pi * 6 * pt.t), pt.t)
                for pt in p]  # ±2px wobble at 6 Hz — hand tremor
    assert actions(segment_path(jittered, 1)) == ["CARRY"]


def test_pure_backward_pass():
    p = leg([], 40, 35, 33, 36, 0.5)
    assert actions(segment_path(p, 1)) == ["PASS"]


def test_lateral_pass():
    p = leg([], 40, 35, 41, 45, 0.5)     # 10m lateral, 1m forward
    assert actions(segment_path(p, 1)) == ["PASS"]


def test_fast_burst_is_kick():
    p = leg([], 30, 35, 65, 35, 0.6)     # 35m in 0.6s
    assert actions(segment_path(p, 1)) == ["KICK"]


def test_slow_forward_is_carry():
    p = leg([], 30, 35, 45, 35, 4.0)
    assert actions(segment_path(p, 1)) == ["CARRY"]


def test_direction_flips_after_kick():
    """Receiver runs the ball back: must read CARRY, not PASS."""
    p = []
    leg(p, 30, 35, 60, 35, 0.5)          # kick downfield
    leg(p, 60, 35, 50, 34, 2.5)          # receiver carries back toward kicker
    assert actions(segment_path(p, 1)) == ["KICK", "CARRY"]


def test_attack_dir_mirrored():
    p = []
    leg(p, 90, 35, 80, 35, 2.5)          # carry toward -x
    leg(p, 80, 35, 81, 43, 0.45)         # backward-lateral pass
    leg(p, 81, 43, 69, 43, 3.0)          # carry
    assert actions(segment_path(p, -1)) == ["CARRY", "PASS", "CARRY"]


def test_speed_change_same_heading_splits_but_stays_carryish():
    """Accel without a turn may split the segment; must never invent a PASS."""
    p = []
    leg(p, 10, 35, 16, 35, 2.0)          # 3 m/s
    leg(p, 16, 35, 40, 35, 2.0)          # 12 m/s burst, same heading, too long for kick
    result = actions(segment_path(p, 1))
    assert "PASS" not in result and "KICK" not in result


def test_accidental_click_ignored():
    p = leg([], 30, 35, 30.5, 35, 0.2)   # 4px twitch
    assert segment_path(p, 1) == []


def test_too_few_points_ignored():
    assert segment_path([PathPoint(0, 0, 0.0), PathPoint(9, 0, 0.1)], 1) == []


def test_last_debug_populated():
    p = []
    leg(p, 10, 35, 20, 35, 2.5)
    leg(p, 20, 35, 19, 43, 0.45)
    leg(p, 19, 43, 31, 43, 3.0)
    leg(p, 31, 43, 71, 38, 0.5)
    segs = segment_path(p, 1)
    d = segmentation.last_debug
    assert d["rejected"] is None
    assert d["n_points"] == len(p)
    assert 55 <= d["hz"] <= 65
    assert d["candidates"]
    assert len(d["picked"]) == len(segs) - 1
    assert len(d["segments"]) == len(segs)
    assert all(s["rule"] for s in d["segments"])
    assert d["segments"][0]["action_geo"] == "CARRY"


def test_last_debug_rejection_reason():
    segment_path([PathPoint(0, 0, 0.0), PathPoint(9, 0, 0.1)], 1)
    assert "too few points" in segmentation.last_debug["rejected"]
    segment_path(leg([], 30, 35, 30.5, 35, 0.2), 1)  # 4px twitch
    assert "net movement" in segmentation.last_debug["rejected"]


def test_apply_taps_logged():
    segs = segment_path(leg([], 10, 35, 22, 35, 3.0), 1)
    apply_taps(segs, [TapEvent("9", 0.15), TapEvent("k", 1.0)], [])
    log = segmentation.last_debug["taps"]
    assert any("'k' hint" in line for line in log)
    assert any("digit" in line for line in log)
