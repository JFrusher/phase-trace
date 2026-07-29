"""Path -> classified Segments. The highest-risk module; pure, no NiceGUI.

Splits one continuous traced path into segments at geometric boundaries
(sharp heading changes, sudden speed changes), then classifies each as
CARRY/PASS/KICK:

  - PASS: net displacement backward or predominantly lateral. A forward pass
    is illegal in rugby, so this is the one reliable signal.
  - KICK: long AND straight. Distance alone is not enough — a long bent run
    is a break, not a kick, and `bent` vetoes it (features.py).
  - CARRY: everything else, and the deliberate default. CARRY is the fixed
    reference class scoring 0, and ties go to it, so ambiguity always lands
    on the answer that does not flip possession.

Nothing here reads a timestamp. Classification is geometry only, so the same
shape classifies identically however fast it was drawn; tests/test_pace_
invariance.py is the fence around that.

Attack direction flips after every KICK segment: the receiver attacks the
other way, so their onward carry must not read as "backward = pass".
Interceptions are unknown at geometry time; a mislabelled return run is
corrected by an R type-hint tap or in review.
"""

import math
from typing import Literal, Optional

from . import config, features
from .continuity import PathPoint, PlayerTag, Segment

Action = Literal["CARRY", "PASS", "KICK"]

# Evidence from the most recent segment_path() + apply_taps() call, for the
# dev panel. Rebuilt per call; MatchState snapshots a reference per chain.
# Module-level is safe: NiceGUI handlers run synchronously on one event loop.
last_debug: dict = {}


def _smooth(points: list[PathPoint]) -> list[PathPoint]:
    half = config.SMOOTH_WINDOW_PTS // 2
    out = []
    for i in range(len(points)):
        if i == 0 or i == len(points) - 1:
            out.append(points[i])  # keep true endpoints (exact metres gained)
            continue
        window = points[max(0, i - half):i + half + 1]
        out.append(PathPoint(
            sum(p.x for p in window) / len(window),
            sum(p.y for p in window) / len(window),
            points[i].t,
        ))
    return out


def _resample(points):
    """Re-space points uniformly by arc-length (RESAMPLE_STEP_M apart).

    Fixed-rate input sampling puts more points per metre when the line is
    drawn slowly; resampling removes that pace dependence so every downstream
    point-count window covers a consistent spatial span. Timestamps are
    linearly interpolated, preserving each part's true duration (and pace).
    Endpoints are preserved exactly.
    """
    arc = _arc_lengths(points)
    total = arc[-1]
    if total < config.RESAMPLE_STEP_M:
        return points
    n = max(1, round(total / config.RESAMPLE_STEP_M))
    out, j = [], 1
    for k in range(n + 1):
        target = total * k / n
        while j < len(arc) - 1 and arc[j] < target:
            j += 1
        a, b = points[j - 1], points[j]
        span = arc[j] - arc[j - 1]
        f = (target - arc[j - 1]) / span if span > 1e-9 else 0.0
        out.append(PathPoint(a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f,
                             a.t + (b.t - a.t) * f))
    return out


def _arc_lengths(points):
    """Cumulative traced path length in metres at each point (arc[0] = 0)."""
    arc, total = [0.0], 0.0
    for a, b in zip(points, points[1:]):
        total += math.hypot(b.x - a.x, b.y - a.y) / config.PX_PER_M
        arc.append(total)
    return arc


def _mean_velocity(points, arc, i, side):
    """Mean velocity over HEADING_WINDOW_M of arc before (-1) / after (+1) i.

    Only the vector's direction is pace-invariant and used downstream; the
    arc-length window keeps that direction estimate over a consistent spatial
    span no matter how fast the line was drawn.
    """
    horizon = config.HEADING_WINDOW_M
    a0 = arc[i]
    if side < 0:
        sel = [p for j, p in enumerate(points[:i + 1]) if a0 - arc[j] <= horizon]
    else:
        sel = [p for j, p in enumerate(points[i:], i) if arc[j] - a0 <= horizon]
    if len(sel) < 2 or sel[-1].t <= sel[0].t:
        return None
    dt = sel[-1].t - sel[0].t
    return ((sel[-1].x - sel[0].x) / dt, (sel[-1].y - sel[0].y) / dt)


def _angle_deg(a, b) -> float:
    na, nb = math.hypot(*a), math.hypot(*b)
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    dot = (a[0] * b[0] + a[1] * b[1]) / (na * nb)
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def _measure_turns(points, arc):
    """(index, heading change deg, speed ratio) for every usable interior point."""
    measured = []
    for i in range(1, len(points) - 1):
        before = _mean_velocity(points, arc, i, -1)
        after = _mean_velocity(points, arc, i, +1)
        if before is None or after is None:
            continue
        speed_b, speed_a = math.hypot(*before), math.hypot(*after)
        if speed_b < 1e-6 and speed_a < 1e-6:
            continue  # stationary hover, heading is noise
        ratio = max(speed_b, speed_a) / max(min(speed_b, speed_a), 1e-6)
        measured.append((i, _angle_deg(before, after), ratio))
    return measured


def _evidence_baselines(measured):
    """(med_angle, med_ratio, angle_base, ratio_base) from this path's own medians."""
    med_angle = sorted(a for _, a, _ in measured)[len(measured) // 2]
    med_ratio = sorted(r for _, _, r in measured)[len(measured) // 2]
    angle_base = (max(config.BOUNDARY_ANGLE_FLOOR_DEG, med_angle)
                  * config.BOUNDARY_ANGLE_BASE_MULT)
    ratio_base = (max(config.BOUNDARY_RATIO_FLOOR, med_ratio)
                  * config.BOUNDARY_RATIO_BASE_MULT)
    return med_angle, med_ratio, angle_base, ratio_base


def _evidence_score(angle, ratio, angle_base, ratio_base):
    """Combined heading/speed-change evidence — either alone can clear accept."""
    return (config.W_BOUNDARY_ANGLE * math.tanh(
                max(0.0, angle - angle_base) / config.BOUNDARY_ANGLE_SCALE_DEG)
            + config.W_BOUNDARY_SPEED * math.tanh(
                max(0.0, ratio - ratio_base) / config.BOUNDARY_RATIO_SCALE))


def _boundary_candidates(points, arc):
    """(candidates, info): per-point evidence scores vs path-adaptive baselines.

    candidates: (index, score, angle, ratio) tuples where the combined
    heading/speed-change evidence clears BOUNDARY_ACCEPT. Baselines are this
    path's own medians (floored), so a wobbly hand raises the bar and either
    evidence alone can still clear the accept threshold.
    """
    measured = _measure_turns(points, arc)
    if not measured:
        return [], {}
    med_angle, med_ratio, angle_base, ratio_base = _evidence_baselines(measured)
    accepted, near = [], []
    for i, angle, ratio in measured:
        score = _evidence_score(angle, ratio, angle_base, ratio_base)
        if score >= config.BOUNDARY_ACCEPT:
            accepted.append((i, score, angle, ratio))
        elif score > 0:
            near.append((score, i, angle, ratio))
    info = {"med_angle": round(med_angle, 1), "med_ratio": round(med_ratio, 2),
            "angle_base": round(angle_base, 1), "ratio_base": round(ratio_base, 2),
            "accept": config.BOUNDARY_ACCEPT,
            "near_misses": [{"i": i, "score": round(s, 2), "angle": round(a, 1),
                             "ratio": round(r, 2)}
                            for s, i, a, r in sorted(near, reverse=True)[:3]]}
    return accepted, info


def _group_candidates(arc, candidates, notes):
    """Collapse candidates within BOUNDARY_GROUP_M of arc into one turn each."""
    groups, current = [], [candidates[0]]
    for cand in candidates[1:]:
        if arc[cand[0]] - arc[current[-1][0]] <= config.BOUNDARY_GROUP_M:
            current.append(cand)
        else:
            groups.append(current)
            current = [cand]
    groups.append(current)
    picked = [max(g, key=lambda c: c[1]) for g in groups]
    for g, p in zip(groups, picked):
        if len(g) > 1:
            notes.append(f"group of {len(g)} cands @{arc[p[0]]:.1f}m"
                         f" -> picked i={p[0]}")
    return picked


def _drop_near_ends(arc, picked, notes):
    """Drop boundaries hugging the path's ends — too short to be a segment."""
    min_gap = config.MIN_SEGMENT_M
    a_end = arc[-1]
    survivors = []
    for c in picked:
        hugs_end = arc[c[0]] < min_gap or a_end - arc[c[0]] < min_gap
        if hugs_end:
            notes.append(f"cand @{arc[c[0]]:.1f}m dropped:"
                         f" within {config.MIN_SEGMENT_M}m of path end")
        else:
            survivors.append(c)
    return survivors


def _thin_to_min_gap(arc, survivors, notes):
    """Thin to MIN_SEGMENT_M spacing, keeping the stronger of any close pair."""
    min_gap = config.MIN_SEGMENT_M
    kept = []
    for cand in survivors:
        crowds_previous = kept and arc[cand[0]] - arc[kept[-1][0]] < min_gap
        if not crowds_previous:
            kept.append(cand)
        elif cand[1] > kept[-1][1]:
            notes.append(f"cand @{arc[kept[-1][0]]:.1f}m dropped:"
                         f" <{config.MIN_SEGMENT_M}m before stronger cand")
            kept[-1] = cand
        else:
            notes.append(f"cand @{arc[cand[0]]:.1f}m dropped:"
                         f" <{config.MIN_SEGMENT_M}m after previous, weaker")
    return kept


def _pick_boundaries(arc, candidates, notes):
    """Collapse candidate runs to one boundary each, enforce min segment length.

    All spacing is in metres of traced path (arc), not time — the same shape
    segments identically however fast it was drawn. Appends one human-readable
    string per drop/demote decision into notes.
    """
    if not candidates:
        return []
    picked = _group_candidates(arc, candidates, notes)
    survivors = _drop_near_ends(arc, picked, notes)
    return [c[0] for c in _thin_to_min_gap(arc, survivors, notes)]


def _classify(points: list[PathPoint], attack_dir: int) -> tuple:
    """(action, evidence dict) — per-class weighted feature scores, argmax wins."""
    feats, raw = features.extract(points, attack_dir)
    scores, probs, action, confidence = features.score(feats)
    if action == "CARRY":
        rule = f"carry (default, margin {confidence:.2f})"
    else:
        _, weights = features.class_weights(action)
        top = max(features.FEATURES, key=lambda f: weights[f] * feats[f])
        rule = (f"{action.lower()}: {top} {weights[top] * feats[top]:+.1f}"
                f" (p={probs[action]:.2f})")
    return action, {
        "action_geo": action, "rule": rule,
        "forward_px": round(raw["fwd_m"] * config.PX_PER_M, 1),
        "lateral_px": round(raw["lat_m"] * config.PX_PER_M, 1),
        "net_m": raw["net_m"], "n_points": len(points), "attack_dir": attack_dir,
        "features": {f: round(feats[f], 3) for f in features.FEATURES},
        "raw": raw,
        "scores": {c: round(s, 2) for c, s in scores.items()},
        "probs": {c: round(p, 3) for c, p in probs.items()},
        "confidence": round(confidence, 3),
    }


def _segment_at(segments, t, grace_s):
    """Segment whose window contains t; else one that ended within grace_s before t."""
    for seg in segments:
        if seg.start_t <= t <= seg.end_t:
            return seg
    late = [s for s in segments if 0 < t - s.end_t <= grace_s]
    return late[-1] if late else None


def _digit_bursts(taps):
    """Group sequential digit taps within DIGIT_BURST_MS into (number, first_t)."""
    out, digits, t0, last_t = [], "", 0.0, None
    for tap in taps:
        if not tap.key.isdigit():
            continue
        if digits and (tap.t - last_t) * 1000 > config.DIGIT_BURST_MS:
            out.append((int(digits), t0))
            digits = ""
        if not digits:
            t0 = tap.t
        digits += tap.key
        last_t = tap.t
    if digits:
        out.append((int(digits), t0))
    return out


def _apply_type_hint(segments, tap, t0, grace, log):
    """K/P/R tap: relabel the segment under the cursor. Never splits one."""
    seg = _segment_at(segments, tap.t, grace)
    if seg is None:
        log.append(f"{tap.t - t0:.2f}s '{tap.key}' hint -> "
                   "no segment within grace")
        return
    log.append(f"{tap.t - t0:.2f}s '{tap.key}' hint -> "
               f"seg{segments.index(seg)} {seg.action}->"
               f"{config.TYPE_HINT_KEYS[tap.key]}")
    seg.action = config.TYPE_HINT_KEYS[tap.key]


def _apply_linebreak(segments, tap, t0, grace, log):
    """L tap: flag a CARRY as a linebreak; only a carry can break the line."""
    seg = _segment_at(segments, tap.t, grace)
    if seg is None:
        log.append(f"{tap.t - t0:.2f}s 'l' -> no segment within grace")
    elif seg.action != "CARRY":
        log.append(f"{tap.t - t0:.2f}s 'l' -> ignored: "
                   f"seg{segments.index(seg)} is {seg.action}")
    else:
        seg.linebreak = True
        log.append(f"{tap.t - t0:.2f}s 'l' -> seg{segments.index(seg)} linebreak")


def _tag_target(segments, b, t):
    """(segment, role) for a digit burst at t whose nearest boundary is b."""
    if t >= b:  # just after a boundary: actor starting the next action
        following = [s for s in segments if s.start_t == b]
        return (following[0], "start") if following else (segments[-1], "end")
    # just before: whoever ended the previous action
    ending = [s for s in segments if s.end_t == b]
    return (ending[-1], "end") if ending else (segments[0], "start")


def _apply_player_numbers(segments, taps, t0, log):
    """Player numbers: the nearest boundary decides both segment and role."""
    boundaries = [segments[0].start_t] + [s.end_t for s in segments]
    for number, t in _digit_bursts(taps):
        b = min(boundaries, key=lambda bt: abs(bt - t))
        seg, role = _tag_target(segments, b, t)
        seg.players.append(PlayerTag(number=number, role=role, at_ts=t))
        log.append(f"{t - t0:.2f}s digit-burst {number} -> boundary @{b - t0:.2f}s "
                   f"({'after' if t >= b else 'before'}) -> "
                   f"seg{segments.index(seg)} {role}")


def _overlapping_shift(seg, shift_intervals):
    """First Shift interval held across seg's window, if any."""
    return next(((s, e) for s, e in shift_intervals
                 if s < seg.end_t and e > seg.start_t), None)


def _mark_intercepts(segments, shift_intervals, t0, log):
    """Shift held over a PASS means the other side took it out of the air."""
    for seg in segments:
        if seg.action != "PASS":
            continue
        held = _overlapping_shift(seg, shift_intervals)
        if held:
            seg.intercepted = True
            log.append(f"shift {held[0] - t0:.2f}-{held[1] - t0:.2f}s overlaps "
                       f"seg{segments.index(seg)} PASS -> intercepted")


def apply_taps(segments: list[Segment], taps, shift_intervals) -> list[Segment]:
    """Layer keyboard annotations onto geometrically-detected segments.

    Taps never move a boundary; they relabel, flag and attribute. That keeps
    segmentation deterministic on the geometry alone, so a mistimed tap
    degrades one label rather than restructuring the chain. Unrecognized keys
    are ignored, so callers can feed the whole per-chain tap log straight in.
    """
    if not segments:
        return segments
    log = last_debug.setdefault("taps", [])  # harmless on standalone calls
    t0 = segments[0].start_t
    grace = config.TYPE_HINT_GRACE_MS / 1000

    for tap in taps:
        if tap.key in config.TYPE_HINT_KEYS:
            _apply_type_hint(segments, tap, t0, grace, log)
        elif tap.key == config.LINEBREAK_KEY:
            _apply_linebreak(segments, tap, t0, grace, log)

    _apply_player_numbers(segments, taps, t0, log)
    _mark_intercepts(segments, shift_intervals, t0, log)
    return segments


def segment_path(points: list[PathPoint], attack_dir: int,
                 force_first: Optional[Action] = None) -> list[Segment]:
    """Split one traced path into classified Segments. attack_dir: +1 = +x, -1 = -x.

    force_first overrides the first segment's class where the laws of the game
    already settle it (a restart is a kick, however it was drawn). It is
    applied inside the loop, not patched on afterwards, so the direction flip
    a KICK causes reaches the segments that follow it.
    """
    global last_debug
    d: dict = {"rejected": None}
    last_debug = d
    if len(points) < 3:
        d["rejected"] = f"too few points ({len(points)} < 3)"
        return []
    net_px = math.hypot(points[-1].x - points[0].x, points[-1].y - points[0].y)
    duration = points[-1].t - points[0].t
    d.update(t0=points[0].t, n_points=len(points), duration_s=round(duration, 3),
             hz=round((len(points) - 1) / duration, 1) if duration > 0 else 0.0,
             net_px=round(net_px, 1))
    if net_px < config.MIN_MOVEMENT_PX:
        d["rejected"] = f"net movement {net_px:.1f}px < {config.MIN_MOVEMENT_PX}px"
        return []
    smoothed = _smooth(_resample(points))
    arc = _arc_lengths(smoothed)
    candidates, boundary_info = _boundary_candidates(smoothed, arc)
    notes: list[str] = []
    boundaries = _pick_boundaries(arc, candidates, notes)
    _record_boundary_debug(d, smoothed, points[0].t, candidates, boundaries,
                           boundary_info, notes)
    return _classify_slices(_slice_at(smoothed, boundaries), attack_dir,
                            force_first, d)


def _record_boundary_debug(d, smoothed, t0, candidates, boundaries,
                           boundary_info, notes):
    """Fill the dev-panel view of what the boundary pass saw and chose."""
    d["boundary"] = boundary_info
    d["candidates"] = [{"i": i, "t": smoothed[i].t - t0, "x": round(smoothed[i].x, 1),
                        "y": round(smoothed[i].y, 1), "angle": round(angle, 1),
                        "ratio": round(ratio, 2), "strength": round(score, 2),
                        "score": round(score, 2)}
                       for i, score, angle, ratio in candidates]
    d["picked"] = [{"i": b, "t": smoothed[b].t - t0, "x": round(smoothed[b].x, 1),
                    "y": round(smoothed[b].y, 1)} for b in boundaries]
    d["boundary_notes"] = notes
    d["segments"] = []


def _slice_at(smoothed, boundaries):
    """Cut the path at each boundary index; the boundary point joins both sides."""
    slices, prev = [], 0
    for b in boundaries:
        slices.append(smoothed[prev:b + 1])
        prev = b
    slices.append(smoothed[prev:])
    return slices


def _should_flip(action, confidence, forced) -> bool:
    """Does this segment hand possession over (flip attack direction)?

    A KICK normally does — the receiver attacks the other way. Two exceptions:
    a forced kick (kickoff/restart) always flips, it is a kick by law; and a
    GEOMETRIC kick below KICK_FLIP_MIN_CONF does not, so a barely-a-kick (a
    long bent run misread as a kick) can't silently invert the frame for every
    downstream segment. confidence None (segments built outside classification)
    keeps the old "a KICK flips" behaviour.
    """
    if action != "KICK":
        return False
    if forced or confidence is None:
        return True
    return confidence >= config.KICK_FLIP_MIN_CONF


def _classify_slices(slices, attack_dir, force_first, d):
    """Classify each slice, flipping attack direction after each handover KICK."""
    segments, direction = [], attack_dir
    for i, sl in enumerate(slices):
        action, evidence = _classify(sl, direction)
        forced = i == 0 and bool(force_first)
        if forced:
            evidence["forced_by"] = force_first
            action = force_first
        flips = _should_flip(action, evidence["confidence"], forced)
        if action == "KICK" and not flips:
            evidence["flip_suppressed"] = True  # low-confidence kick: frame held
        d["segments"].append(evidence)
        segments.append(Segment(action=action, points=sl,
                                scores=evidence["scores"],
                                confidence=evidence["confidence"],
                                flips_possession=flips if action == "KICK" else None))
        if flips:
            direction = -direction  # receiver attacks the other way
    return segments


def reclassify_downstream(segments, base_dir, start_index):
    """Re-derive direction + geometric class for segments AFTER start_index.

    Toggling a segment's action (canvas reclassify) can add or remove a KICK,
    which changes the attack-direction frame for everything downstream — those
    segments were classified in the stale frame. Walk the flip sequence from
    base_dir and re-run _classify for every segment past start_index in the
    corrected frame. Segments up to and including start_index keep their
    (now user-set) action and flips_possession.
    """
    direction = base_dir
    for i, seg in enumerate(segments):
        if i > start_index:
            action, evidence = _classify(seg.points, direction)
            seg.action = action
            seg.scores = evidence["scores"]
            seg.confidence = evidence["confidence"]
            seg.flips_possession = (_should_flip(action, evidence["confidence"], False)
                                    if action == "KICK" else None)
        if seg.action == "KICK" and seg.flips_possession is not False:
            direction = -direction
