"""PlayChain -> raw rugby event dict(s). Pure translation, no UI.

Team attribution walks the chain: a carry never flips possession, a kick
always does (receiver is the opposing team), an intercepted pass does. Each
flip splits the chain; every sub-chain becomes one phase_sequence dict in
the exact shape RugbySport.translate() consumes. An interception also logs
turnover_won for the gaining team; a kick does not (tactical choice, not a
forced error).

`weight` is never emitted — translators/rugby_weights.json and
_territory_weight() stay the single source of truth.
"""

from dataclasses import dataclass

from . import config
from .geometry import canonical_xy, PitchCalibration

# Score types that end a possession and trigger a restart (the conceding team
# takes the drop kick). Conversions follow a try by the same team, so they
# don't independently determine the next possessor.
RESTART_SCORE_TYPES = ("try", "penalty_try", "penalty_kick", "drop_goal")


def _other(team):
    return "away" if team == "home" else "home"


def assign_teams(segments, start_team: str) -> str:
    """Set each segment's team in place; return who has possession after."""
    team = start_team
    for seg in segments:
        seg.team = team
        if seg.action == "KICK" or (seg.action == "PASS" and seg.intercepted):
            team = _other(team)
    return team


def infer_next_possession(chain_start_team: str, final_team: str,
                          scored_team) -> str:
    """Who has the ball for the NEXT chain, given how this one ended.

    - a score -> the team that conceded restarts, so they hold the ball for
      the drop kick (possession here always means "who has the ball", never
      "who will receive"; the restart kick itself hands it over);
    - a kick/interception already flipped possession in-chain (final_team);
    - otherwise the possession was lost at the breakdown (knock-on / scrum /
      jackal = the coarse "turnover"), so it goes to the other side.
    ponytail: plain-end assumes possession lost; tap Z/X if it was retained
    (e.g. penalty won and played on).
    """
    if scored_team:
        return _other(scored_team)
    if final_team != chain_start_team:
        return final_team
    return _other(chain_start_team)


@dataclass(frozen=True)
class ChainOrigin:
    """How the next possession begins, and where to draw its chip."""
    reason: str
    team: str                      # "home"/"away" — who has the ball next
    mark: tuple | None = None      # (x_px, y_px) chip anchor; None = no chip
    alt_mark: tuple | None = None  # the other lawful mark, when there are two


def in_goal_defender(cal: PitchCalibration, x_px: float,
                     attack_dir_home: int) -> str:
    """Who defends the in-goal at this end. Geometry, not possession.

    A team attacking towards +x defends the left end, so which side owns an
    in-goal never depends on who happens to be carrying when the ball gets
    there — which is the point, since both teams end up in both in-goals.
    """
    return "home" if (attack_dir_home > 0) == cal.is_left_end(x_px) else "away"


def default_in_goal_outcome(segments, attack_dir_home: int,
                            cal: PitchCalibration = PitchCalibration()):
    """What a trace ending over a try line most likely was, or None.

    Grounding is invisible in a line, so this is a guess the chip lets you
    change. Carrying into the in-goal you are attacking reads as a try;
    ending in your own reads as a defender making it dead, and so does a kick
    into the in-goal, which the defenders field far more often than the chase
    wins. Past the dead-ball line is not a choice at all, so it returns None.
    """
    last = segments[-1]
    end = last.points[-1]
    if not cal.in_goal(end.x) or cal.crossed_dead_ball(end.x):
        return None
    attackers = _other(in_goal_defender(cal, end.x, attack_dir_home))
    if last.team != attackers or last.action == "KICK":
        return "drop_out"
    return "try"


def infer_origin(*, segments, chain_start_team, final_team, scored_team,
                 armed, attack_dir_home, cal: PitchCalibration = PitchCalibration(),
                 in_goal_outcome=None) -> ChainOrigin:
    """Read how this chain ended to decide how the next one starts.

    Everything here is derived from geometry the trace already contains, so
    the common cases need no extra input. What cannot be seen in a line — a
    penalty, a knock-on, whether the ball was grounded — is tapped or chosen
    instead. A try arrives here as `scored_team`, not as an in_goal_outcome.
    """
    team = infer_next_possession(chain_start_team, final_team, scored_team)
    if scored_team:
        return ChainOrigin("restart", team, halfway_mark(cal))

    last = segments[-1]
    end = last.points[-1]
    if _ball_out_of_touch(last, end, cal):
        return _lineout(last, end, team, chain_start_team, armed,
                        attack_dir_home, cal)
    if cal.crossed_dead_ball(end.x) or in_goal_outcome == "drop_out":
        # the defending side drops out from their own 22, whoever put it there
        defenders = in_goal_defender(cal, end.x, attack_dir_home)
        mark_x = cal.drop_out_mark_x(cal.is_left_end(end.x))
        return ChainOrigin("drop_out_22", defenders, (mark_x, cal.width_px / 2))
    if in_goal_outcome == "held_up":
        attackers = _other(in_goal_defender(cal, end.x, attack_dir_home))
        mark_x = cal.five_m_mark_x(cal.is_left_end(end.x))
        return ChainOrigin("scrum", attackers, (mark_x, end.y))
    if last.action == "KICK":
        return ChainOrigin("kick_return", team)
    if any(s.intercepted for s in segments):
        return ChainOrigin("interception", team)
    return ChainOrigin("turnover_open", team, (end.x, end.y))


def _ball_out_of_touch(last, end, cal) -> bool:
    """The ball crossed a touchline — carried over, or kicked out and landing there."""
    return cal.crossed_touch(end.y) or (last.action == "KICK"
                                        and cal.ends_in_touch(end.y))


def _lineout(last, end, team, chain_start_team, armed, attack_dir_home,
             cal) -> ChainOrigin:
    """The ball is out. Who throws in, and where the line-out forms."""
    if last.action != "KICK":
        # carried out: the mark is simply where the carrier crossed, and the
        # kick-to-touch law has nothing to say about it
        return ChainOrigin("lineout", team, (end.x, end.y))
    if armed == "kick_to_touch":
        # a penalty to touch keeps the throw AND the ground, unlike an
        # open-play kick, which is why the armed case bypasses the law
        return ChainOrigin("lineout", chain_start_team, (end.x, end.y))
    kicker_dir = attack_dir_home if last.team == "home" else -attack_dir_home
    kick_from = last.points[0].x
    mark_x = cal.lineout_mark_x(kick_from, end.x, kicker_dir)
    # the other lawful mark: a bounce before the line makes it the exit
    # point, a kick on the full makes it the kick itself
    alt_x = end.x if mark_x == kick_from else kick_from
    return ChainOrigin("lineout", team, (mark_x, end.y), (alt_x, end.y))


def penalty_at_goal_scored(last_seg, attack_dir: int,
                           cal: PitchCalibration = PitchCalibration()) -> bool:
    """Did an at-goal penalty kick pass between the posts?

    Rugby is three-dimensional and a top-down trace is not, so this reads only
    the horizontal line: where the ball's ground track crosses the goal line,
    and whether that crossing is between the uprights. A line drawn through the
    posts is a successful kick — the analyst draws it that way on purpose. A
    kick that never reaches the line (falls short) or crosses wide is a miss.
    """
    gx = cal.goal_line_px(attack_dir)
    pts = last_seg.points
    for a, b in zip(pts, pts[1:]):
        if (a.x - gx) * (b.x - gx) <= 0 and a.x != b.x:
            f = (gx - a.x) / (b.x - a.x)
            return cal.between_posts(a.y + f * (b.y - a.y))
    return False


def halfway_mark(cal: PitchCalibration) -> tuple:
    """Centre spot — where a kickoff or a restart is taken."""
    return (cal.left_try_line_px + config.PITCH_LENGTH_M / 2 * cal.px_per_m,
            cal.width_px / 2)


def summarise(events: list[dict], actions: list[str]) -> str:
    """One-line commit summary for the UI toast — 'ENG · CARRY-PASS · 12m'.

    Reads the events the chain just produced rather than recomputing geometry,
    so the toast can never disagree with what was actually recorded.
    """
    if not events:
        return ""
    metres = sum(e.get("metres_gained", 0) for e in events)
    return f"{events[0]['team']} · {'-'.join(actions)} · {metres:g}m"


def compute_score(events, team_names: dict) -> dict:
    """Sum point-scoring events into {"home": int, "away": int}."""
    score = {"home": 0, "away": 0}
    name_to_key = {v: k for k, v in team_names.items()}
    for e in events:
        pts = config.POINTS.get(e.get("type"))
        key = name_to_key.get(e.get("team"))
        if pts and key:
            score[key] += pts
    return score


def chain_to_events(chain, team_names: dict, attack_dir_home: int,
                    cal: PitchCalibration = PitchCalibration(),
                    start_reason: str = None, flip: bool = False) -> list[dict]:
    """chain.segments must already be tap-applied and team-assigned.

    `flip` folds any exported position into the first-half frame (second-half
    ends swapped); see geometry.canonical_xy. phase_sequence carries only
    orientation-independent metres, so only the interception point is folded.
    """
    if not chain.segments:
        return []
    t0 = chain.t0

    def minute_at(t):
        return round(chain.start_minute + (t - t0) / 60, 1)

    subs = _split_by_team(chain.segments)
    out = []
    for i, sub in enumerate(subs):
        ev = _phase_event(sub, team_names, attack_dir_home, cal, minute_at)
        if i == 0:
            # origin keys precede players so the exported key order is stable
            _add_origin(ev, sub, attack_dir_home, cal, start_reason)
        players = [{"number": p.number, "role": p.role}
                   for s in sub for p in s.players]
        if players:
            ev["players"] = players  # harmless extra, ignored by the translator
        out.append(ev)
        if i > 0 and subs[i - 1][-1].action == "PASS":  # interception split
            out.append(_turnover_event(sub, team_names, cal, flip, minute_at))
    return out


def _split_by_team(segments) -> list[list]:
    """Group into runs of consecutive same-team segments."""
    subs, current = [], [segments[0]]
    for seg in segments[1:]:
        if seg.team == current[-1].team:
            current.append(seg)
        else:
            subs.append(current)
            current = [seg]
    subs.append(current)
    return subs


def _phase_event(sub, team_names, attack_dir_home, cal, minute_at) -> dict:
    team = sub[0].team
    attack_dir = attack_dir_home if team == "home" else -attack_dir_home
    start_pt, end_pt = sub[0].points[0], sub[-1].points[-1]
    return {
        "type": "phase_sequence",
        "team": team_names[team],
        "minute": minute_at(sub[0].start_t),
        "metres_gained": cal.metres_gained(start_pt.x, end_pt.x, attack_dir),
        "end_metres_from_line": cal.end_metres_from_line(end_pt.x, attack_dir),
        "linebreaks": sum(1 for s in sub if s.linebreak),
    }


def _add_origin(ev, sub, attack_dir_home, cal, start_reason):
    """Name where the first sub-chain began (mutates ev in place).

    Only the first sub-chain has an origin worth naming: later ones exist
    because a kick or interception split this chain, which is already recorded
    in the segment that did it.
    """
    team = sub[0].team
    attack_dir = attack_dir_home if team == "home" else -attack_dir_home
    ev["start_metres_from_line"] = cal.metres_from_line(sub[0].points[0].x, attack_dir)
    if start_reason:
        ev["start_reason"] = start_reason


def _turnover_event(sub, team_names, cal, flip, minute_at) -> dict:
    """Where the ball was picked off — the gaining run's first point."""
    team = sub[0].team
    start_pt = sub[0].points[0]
    ix, iy = canonical_xy(cal.field_x_m(start_pt.x), cal.field_y_m(start_pt.y), flip)
    return {
        "type": "turnover_won",
        "team": team_names[team],
        "minute": minute_at(sub[0].start_t),
        "x_m": round(ix, 1), "y_m": round(iy, 1),
    }


def actor(segment) -> int | None:
    """Jersey number of the player who performed this action, or None.

    A digit tapped just after a boundary lands as role="start" on the segment
    (the actor starting it, apply_taps Decision 11); prefer that, else fall
    back to any tag present. Absent when nothing was tapped — the data model
    tolerates missing pieces.
    """
    starts = [p for p in segment.players if p.role == "start"]
    tag = starts[0] if starts else (segment.players[0] if segment.players else None)
    return tag.number if tag else None


def set_piece_record(reason: str, feed_team: str, secured_team: str,
                     team_names: dict, minute: float) -> dict | None:
    """A scrum/lineout outcome, inferred from who fed vs who secured the ball.

    `feed_team` threw in / put the ball into the scrum; `secured_team` came
    away with it (the team that started the possession the set piece began).
    Same team = `won`; opposition = `lost` (the throw was stolen, or the scrum
    turned over). Both are home/away keys. Returns None for non-set-piece
    starts, so the caller can hand it any chain origin.
    """
    if reason not in config.SET_PIECE_REASONS:
        return None
    return {
        "type": "set_piece",
        "kind": reason,                       # "scrum" / "lineout"
        "team": team_names[feed_team],        # the feeding / throwing team
        "outcome": "won" if secured_team == feed_team else "lost",
        "minute": round(minute, 1),
    }


def chain_to_actions(chain, team_names: dict, attack_dir_home: int,
                     cal: PitchCalibration = PitchCalibration(),
                     flip: bool = False) -> list[dict]:
    """One dict per segment: the rich per-action stream for the raw export.

    Parallel to chain_to_events, which collapses segments into phase_sequences
    for the momentum viz; this keeps each carry/pass/kick as its own row so a
    coach gets per-action detail. chain.segments must already be tap-applied
    and team-assigned. Optional fields (linebreak/intercepted/player) are only
    present when set, so a partially-tagged chain is still valid data.

    `flip` (second half) folds the exported coordinates into the first-half
    frame and reports attack_dir in that same frame, so a team attacks the
    same way in the data all match. metres_gained / end_metres_from_line are
    computed from the live attack_dir and stay correct either way.
    """
    if not chain.segments:
        return []
    t0 = chain.t0

    def minute_at(t):
        return round(chain.start_minute + (t - t0) / 60, 1)

    out = []
    for seg in chain.segments:
        attack_dir = attack_dir_home if seg.team == "home" else -attack_dir_home
        start_pt, end_pt = seg.points[0], seg.points[-1]
        sx, sy = canonical_xy(cal.field_x_m(start_pt.x), cal.field_y_m(start_pt.y), flip)
        ex, ey = canonical_xy(cal.field_x_m(end_pt.x), cal.field_y_m(end_pt.y), flip)
        ev = {
            "type": seg.action.lower(),   # "carry" / "pass" / "kick"
            "team": team_names[seg.team],
            "minute": minute_at(seg.start_t),
            "metres_gained": cal.metres_gained(start_pt.x, end_pt.x, attack_dir),
            "end_metres_from_line": cal.end_metres_from_line(end_pt.x, attack_dir),
            # absolute pitch coordinates in metres (x 0..100 field, in-goal
            # beyond; y 0..width), folded into the first-half frame so both
            # halves share one orientation for heatmaps / arrows.
            "start_x_m": round(sx, 1), "start_y_m": round(sy, 1),
            "end_x_m": round(ex, 1), "end_y_m": round(ey, 1),
            "attack_dir": -attack_dir if flip else attack_dir,   # canonical (first-half) sense
        }
        if seg.linebreak:
            ev["linebreak"] = True
        if seg.intercepted:
            ev["intercepted"] = True
        player = actor(seg)
        if player is not None:
            ev["player"] = player
        out.append(ev)
    return out
