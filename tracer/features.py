"""Segment feature extraction + per-class linear scoring (Rubine-style).

extract() turns one segment's raw points into named squashed features;
score() turns features into per-class scores, softmax probabilities, the
winning action, and a confidence margin. CARRY is the fixed reference class
(score 0): PASS/KICK scores read as evidence *against* the carry default.

Every feature is PURELY SPATIAL — computed from point positions only, never
from timestamps. The time taken to draw the line is not measured and plays no
part in classification (a user varies drawing speed freely).

Both classes are defined by a veto as much as by evidence. A pass cannot gain
forward ground, so forward progress vetoes the lateral/backward PASS evidence.
A kick must be straight as well as long, so `bent` vetoes KICK — without it a
32m running break clears the distance bias and wrongly flips possession.

Weights/biases/scales are flat constants in config.py, read via getattr at
call time so sweep.py and fit.py setattr take effect without reimport.
"""

import math

from . import config

FEATURES = ("backward", "lateral", "straight", "dist", "bent")
SCORED_CLASSES = ("PASS", "KICK")
CLASSES = ("CARRY",) + SCORED_CLASSES  # tie-break order: CARRY wins


def _rect_tanh(value, scale):
    return math.tanh(max(0.0, value) / scale)


def extract(points, attack_dir):
    """(features, raw) for one segment. attack_dir: +1 = +x, -1 = -x.

    Classification is time-free: only point positions are read, never timestamps.
    """
    px = config.PX_PER_M
    start, end = points[0], points[-1]
    fwd_m = attack_dir * (end.x - start.x) / px
    lat_m = (end.y - start.y) / px
    net_m = math.hypot(end.x - start.x, end.y - start.y) / px
    path_m = sum(math.hypot(b.x - a.x, b.y - a.y) / px
                 for a, b in zip(points, points[1:]))
    straightness = net_m / path_m if path_m > 1e-9 else 1.0

    features = {
        # PASS evidence, both vetoed by forward gain: a pass never advances.
        "backward": _rect_tanh(-fwd_m, config.F_BACK_SCALE_M),
        "lateral": _rect_tanh(abs(lat_m) - config.LATERAL_FWD_PENALTY * max(0.0, fwd_m),
                              config.F_LAT_SCALE_M),
        # KICK evidence: long and straight.
        "straight": math.tanh((straightness - config.F_STRAIGHT_CENTER)
                              / config.F_STRAIGHT_SCALE),
        "dist": _rect_tanh(net_m, config.F_DIST_SCALE_M),
        # KICK veto: rectified bentness, positive only below F_BENT_CENTER, so a
        # long BENT run can't clear the distance bias a straight kick does.
        "bent": _rect_tanh(config.F_BENT_CENTER - straightness, config.F_BENT_SCALE),
    }
    raw = {"fwd_m": round(fwd_m, 2), "lat_m": round(lat_m, 2),
           "net_m": round(net_m, 2), "straightness": round(straightness, 3)}
    return features, raw


def class_weights(cls):
    """(bias, {feature: weight}) read live from config."""
    bias = getattr(config, f"B_{cls}")
    return bias, {f: getattr(config, f"W_{cls}_{f.upper()}") for f in FEATURES}


def score(features):
    """(scores, probs, action, confidence) — confidence = top prob - second."""
    scores = {"CARRY": 0.0}
    for cls in SCORED_CLASSES:
        bias, weights = class_weights(cls)
        scores[cls] = bias + sum(weights[f] * features[f] for f in FEATURES)
    peak = max(scores.values())
    exps = {c: math.exp(s - peak) for c, s in scores.items()}
    total = sum(exps.values())
    probs = {c: e / total for c, e in exps.items()}
    action = max(CLASSES, key=lambda c: (scores[c], -CLASSES.index(c)))
    ranked = sorted(probs.values(), reverse=True)
    return scores, probs, action, ranked[0] - ranked[1]
