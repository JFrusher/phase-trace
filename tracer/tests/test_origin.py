"""How the next possession begins: the start-reason inference table.

Type is never a guess the user has to correct — it is either geometrically
certain (a kick finishing at a touchline is a lineout, a score is a restart)
or explicitly typed. Only the TEAM is ambiguous, and the chip flips that.
"""

from tracer import config, fixtures
from tracer.continuity import PathPoint, Segment
from tracer.events import (assign_teams, compute_score, default_in_goal_outcome,
                           halfway_mark, infer_origin)
from tracer.match_state import MatchState, _other

PX = config.PX_PER_M
LEFT = config.IN_GOAL_DEPTH_M * PX
MID_Y = config.PITCH_WIDTH_M * PX / 2
TOUCH_Y = 0.0


def _seg(action, x0_m, x1_m, y0=MID_Y, y1=MID_Y, **kw):
    return Segment(action=action,
                   points=[PathPoint(LEFT + x0_m * PX, y0, 0.0),
                           PathPoint(LEFT + x1_m * PX, y1, 1.0)], **kw)


def _origin(segments, start_team="home", scored=None, armed=None,
            attack_dir_home=1, in_goal=None):
    final = assign_teams(segments, start_team)
    return infer_origin(segments=segments, chain_start_team=start_team,
                        final_team=final, scored_team=scored, armed=armed,
                        attack_dir_home=attack_dir_home,
                        in_goal_outcome=in_goal)


def _in_goal_default(segments, start_team="home", attack_dir_home=1):
    assign_teams(segments, start_team)
    return default_in_goal_outcome(segments, attack_dir_home)


def test_a_score_restarts_with_the_conceding_team_kicking():
    o = _origin([_seg("CARRY", 80, 99)], scored="home")
    assert o.reason == "restart"
    assert o.team == "away"      # they conceded, so they hold the ball to kick


def test_kick_finishing_at_a_touchline_is_a_lineout_to_the_other_team():
    o = _origin([_seg("KICK", 10, 60, y1=TOUCH_Y)])
    assert o.reason == "lineout"
    assert o.team == "away"          # you don't throw in to your own kick


def test_kick_to_touch_from_inside_own_22_marks_where_it_went_out():
    o = _origin([_seg("KICK", 10, 60, y1=TOUCH_Y)])
    assert round((o.mark[0] - LEFT) / PX, 1) == 60.0


def test_kick_to_touch_from_outside_own_22_marks_back_at_the_kick():
    o = _origin([_seg("KICK", 40, 75, y1=TOUCH_Y)])
    assert round((o.mark[0] - LEFT) / PX, 1) == 40.0


def test_penalty_to_touch_keeps_the_throw_and_the_ground():
    # armed by the penalty chooser: unlike open play, the kicker throws in
    # AND the mark is where it went out even from outside the 22
    o = _origin([_seg("KICK", 40, 75, y1=TOUCH_Y)], armed="kick_to_touch")
    assert o.reason == "lineout"
    assert o.team == "home"
    assert round((o.mark[0] - LEFT) / PX, 1) == 75.0


def test_kick_staying_in_the_field_is_a_return():
    o = _origin([_seg("KICK", 20, 60)])
    assert o.reason == "kick_return"
    assert o.team == "away"


def test_intercepted_pass_reads_as_an_interception():
    o = _origin([_seg("CARRY", 20, 30),
                 _seg("PASS", 30, 28, intercepted=True),
                 _seg("CARRY", 28, 20)])
    assert o.reason == "interception"
    assert o.team == "away"


def test_plain_carry_end_is_an_open_turnover_marked_where_it_died():
    o = _origin([_seg("CARRY", 20, 32)])
    assert o.reason == "turnover_open"
    assert o.team == "away"
    assert round((o.mark[0] - LEFT) / PX, 1) == 32.0


# --- out of play: touch, in-goal, dead ball ---------------------------------
def test_carrier_crossing_a_touchline_is_a_lineout_to_the_other_team():
    o = _origin([_seg("CARRY", 20, 32, y1=-2.0)])
    assert o.reason == "lineout"
    assert o.team == "away"          # you don't throw in to your own mistake
    assert o.alt_mark is None        # the kick law has nothing to say here
    assert round((o.mark[0] - LEFT) / PX, 1) == 32.0


def test_carrier_running_near_the_touchline_stays_in_play():
    inside = config.TOUCH_MARGIN_M * PX      # inside the kick margin, still on
    o = _origin([_seg("CARRY", 20, 32, y1=inside)])
    assert o.reason == "turnover_open"


def test_a_trace_ending_in_the_attacking_in_goal_reads_as_a_try():
    assert _in_goal_default([_seg("CARRY", 90, 103)]) == "try"


def test_a_kick_into_the_in_goal_reads_as_a_drop_out_not_a_try():
    # the defenders field it far more often than the chase wins the race
    assert _in_goal_default([_seg("KICK", 60, 103)]) == "drop_out"


def test_a_trace_ending_in_your_own_in_goal_reads_as_a_drop_out():
    assert _in_goal_default([_seg("CARRY", 10, -3)]) == "drop_out"


def test_nothing_to_choose_when_the_trace_stayed_on_the_field():
    assert _in_goal_default([_seg("CARRY", 20, 32)]) is None


def test_held_up_is_a_five_metre_scrum_to_the_attacking_side():
    o = _origin([_seg("CARRY", 90, 103)], in_goal="held_up")
    assert o.reason == "scrum"
    assert o.team == "home"                              # attacking that end
    assert round((o.mark[0] - LEFT) / PX, 1) == 95.0     # 5m out


def test_drop_out_goes_to_the_side_defending_that_in_goal():
    o = _origin([_seg("CARRY", 90, 103)], in_goal="drop_out")
    assert o.reason == "drop_out_22"
    assert o.team == "away"                              # away defends the right
    assert round((o.mark[0] - LEFT) / PX, 1) == 78.0     # their 22


def test_ball_kicked_over_the_dead_ball_line_is_a_drop_out():
    # no choice to make: it is dead, whoever put it there
    o = _origin([_seg("KICK", 60, 111)])
    assert o.reason == "drop_out_22"
    assert o.team == "away"
    assert round((o.mark[0] - LEFT) / PX, 1) == 78.0


# --- tapped origins, through the real MatchState ---------------------------
def _trace(m, x0_m, x1_m, t0, dur, y=MID_Y, y1=None, n=60):
    y1 = y if y1 is None else y1
    m.mouse_down(LEFT + x0_m * PX, y, t0)
    for i in range(1, n + 1):
        f = i / n
        m.mouse_move(LEFT + (x0_m + (x1_m - x0_m) * f) * PX, y + (y1 - y) * f,
                     t0 + dur * f)
    return t0 + dur


def _match():
    """Mid-match, clock stopped: a fresh match pends a kickoff, which snaps the
    start to the centre spot and forces the first segment to a KICK."""
    return fixtures.open_play_match(home="ENG", away="WAL")


def test_first_chain_of_the_match_is_a_kickoff():
    m = MatchState("ENG", "WAL")
    assert m.pending_start_reason == "kickoff"


# --- restarts: taken from the centre spot, always a kick --------------------
def test_a_kickoff_starts_from_the_centre_spot_wherever_you_press():
    m = MatchState("ENG", "WAL")
    m.clock.start(t=100.0)
    at = m.mouse_down(LEFT + 20 * PX, MID_Y + 60, 100.0)   # a sloppy press
    assert at == halfway_mark(m.cal)          # returned so the canvas draws it
    assert (m.recorder.points[0].x, m.recorder.points[0].y) == at
    assert round((m.recorder.points[0].x - LEFT) / PX) == 50


def test_a_snapped_kickoff_shifts_the_whole_path_not_just_its_start():
    # moving only the first point would leave the gap between the spot and the
    # press as a leg of its own — and that leg would become the kick
    m = MatchState("ENG", "WAL")
    m.clock.start(t=100.0)
    t = _trace(m, 20, 60, 100.0, 1.0)         # pressed 30m left of the spot
    m.key_down("a", t)
    assert [s.action for s in m.last_chain.segments] == ["KICK"]
    pts = m.last_chain.segments[0].points
    assert round((pts[0].x - LEFT) / PX) == 50          # taken from the spot
    assert round((pts[-1].x - LEFT) / PX) == 90         # 40m drawn, 40m kicked


def test_a_restart_is_a_kick_however_short_it_was_drawn():
    # a restart tapped short is still a kick, and reading it as a carry would
    # leave the ball with the side that just conceded
    m = MatchState("ENG", "WAL")
    m.clock.start(t=100.0)
    t = _trace(m, 50, 58, 100.0, 1.0)         # 8m: geometry alone says CARRY
    m.key_down("a", t)
    assert [s.action for s in m.last_chain.segments][0] == "KICK"
    assert m.possession == "away"             # the kick handed it over
    assert m.events[0]["start_reason"] == "kickoff"


def test_a_score_arms_the_same_treatment_for_the_restart():
    m = _match()
    m.pending_start_reason = "scrum"
    m.clock.start(t=100.0)
    t = _trace(m, 20, 34, 100.0, 3.0)
    m.key_down("t", t)                        # ENG score
    m.key_down("a", t + 0.01)
    assert m.pending_start_reason == "restart"
    at = m.mouse_down(LEFT + 30 * PX, MID_Y, t + 1)
    assert at == halfway_mark(m.cal)


def test_scrum_tap_ends_the_play_and_feeds_the_other_team():
    m = _match()
    m.clock.start(t=100.0)
    t = _trace(m, 20, 32, 100.0, 3.0)
    m.key_down("s", t)                      # knock-on by the team carrying
    assert m.pending_start_reason == "scrum"
    assert m.possession == "away"
    assert m.events                         # the chain still committed


def test_penalty_tap_awards_against_the_team_in_possession():
    m = _match()
    m.clock.start(t=100.0)
    m.key_down("f", 160.0)
    assert m.pending_start_reason == "penalty"
    assert m.possession == "away"
    assert [(e["type"], e["team"]) for e in m.events] == [("penalty_won", "WAL")]


def test_penalty_arms_a_kick_to_touch_by_default():
    m = _match()
    m.clock.start(t=100.0)
    m.key_down("f", 160.0)
    assert m.armed_next_action == "kick_to_touch"


def test_choosing_tap_and_go_disarms_the_kick():
    m = _match()
    m.clock.start(t=100.0)
    m.key_down("f", 160.0)
    m.choose_penalty_option("tap_and_go")
    assert m.armed_next_action is None
    assert m.pending_start_reason == "penalty"


def test_penalty_kicked_to_touch_keeps_the_ball_and_the_ground():
    m = _match()
    m.clock.start(t=100.0)
    m.key_down("f", 160.0)                  # penalty to WAL (away, attacks -x)
    assert m.possession == "away"
    t = _trace(m, 75, 40, 161.0, 1.0, y1=TOUCH_Y)   # away kicks to touch
    m.key_down("a", t)
    assert m.last_origin.reason == "lineout"
    assert m.possession == "away"           # kicker throws in, unlike open play
    assert round((m.last_origin.mark[0] - LEFT) / PX) == 40   # ground kept


def test_arming_is_one_shot():
    m = _match()
    m.clock.start(t=100.0)
    m.key_down("f", 160.0)
    t = _trace(m, 75, 40, 161.0, 1.0, y1=TOUCH_Y)
    m.key_down("a", t)
    assert m.armed_next_action is None


def test_the_pending_reason_lands_on_the_next_chain_then_clears():
    m = _match()
    m.pending_start_reason = "scrum"
    m.clock.start(t=100.0)
    t = _trace(m, 20, 34, 100.0, 3.0)
    m.key_down("a", t)                      # chain 1 exported off that scrum
    assert m.events[0]["start_reason"] == "scrum"
    assert m.pending_start_reason == "turnover_open"


def test_undo_restores_the_pending_origin():
    m = _match()
    m.pending_start_reason = "scrum"
    m.clock.start(t=100.0)
    t = _trace(m, 20, 34, 100.0, 3.0)
    m.key_down("a", t)
    m.undo_last()
    assert m.pending_start_reason == "scrum"
    assert m.possession == "home"


def test_clicking_a_segment_cycles_its_action_and_re_commits():
    m = _match()
    m.clock.start(t=100.0)
    t = _trace(m, 20, 34, 100.0, 3.0)
    m.key_down("a", t)
    assert m.last_chain.segments[0].action == "CARRY"
    m.reclassify_segment(0)
    assert m.last_chain.segments[0].action == "PASS"
    assert len(m.events) == 1            # re-committed, not appended twice
    m.reclassify_segment(0)
    assert m.last_chain.segments[0].action == "KICK"
    assert m.last_end_reason == "kick"   # possession consequences follow


def test_reclassifying_via_a_real_click_does_not_duplicate_events():
    # the click that re-classifies is itself a mouse_down/up, which overwrites
    # the undo snapshot before the handler runs — rewinding to THAT leaves the
    # committed chain in place and appends a second copy
    m = _match()
    m.clock.start(t=100.0)
    t = _trace(m, 20, 34, 100.0, 3.0)
    m.key_down("a", t)
    assert len(m.events) == 1
    for n in range(3):
        m.mouse_down(LEFT + 27 * PX, MID_Y, t + 1 + n)   # the click
        m.reclassify_segment(0)
        assert len(m.events) == 1, f"duplicated on click {n + 1}"


def test_a_score_survives_reclassifying_through_a_click():
    m = _match()
    m.clock.start(t=100.0)
    t = _trace(m, 80, 99, 100.0, 3.0)
    m.key_down("t", t)                    # try mid-chain
    m.key_down("a", t + 0.01)
    assert m.last_origin.reason == "restart"
    m.mouse_down(LEFT + 90 * PX, MID_Y, t + 1)
    m.reclassify_segment(0)
    assert m.last_origin.reason == "restart"   # the try is still found
    assert compute_score(m.events, m.team_names) == {"home": 5, "away": 0}


def test_reclassifying_a_missing_segment_is_a_noop():
    m = _match()
    m.reclassify_segment(0)
    assert m.events == []


# --- every indicator is a switch -------------------------------------------
def test_the_chip_flips_the_team():
    m = _match()
    m.clock.start(t=100.0)
    t = _trace(m, 20, 34, 100.0, 3.0)
    m.key_down("a", t)
    assert m.last_origin.team == "away"
    m.flip_origin_team()                    # it was ENG's ball at the breakdown
    assert m.possession == "home"
    assert m.last_origin.team == "home"
    assert m.last_origin.reason == "turnover_open"   # type never changes


def test_the_header_tag_flips_possession():
    m = _match()
    m.clock.start(t=100.0)
    t = _trace(m, 20, 34, 100.0, 3.0)
    m.key_down("a", t)
    before = m.possession
    m.flip_possession()                     # the header possession tag is a button
    assert m.possession == _other(before)
    assert m.last_origin.team == m.possession        # origin kept in step
    m.flip_possession()                     # and back
    assert m.possession == before
    assert m.last_origin.team == before


def test_flip_possession_works_before_any_origin():
    m = _match()                            # kickoff, nothing traced yet
    before = m.possession
    assert m.last_origin is None
    m.flip_possession()                     # a mis-set kickoff team, one click to fix
    assert m.possession == _other(before)
    assert m.last_origin is None            # nothing to keep in step, no crash


def test_a_lineout_chip_offers_the_other_mark():
    # kicked from outside the 22, so the tool assumes on the full and marks
    # back at the kick. It bounced, so the operator clicks the mark across.
    m = _match()
    m.clock.start(t=100.0)
    t = _trace(m, 40, 75, 100.0, 1.0, y1=TOUCH_Y)
    m.key_down("a", t)
    assert round((m.last_origin.mark[0] - LEFT) / PX) == 40
    m.flip_origin_mark()
    assert round((m.last_origin.mark[0] - LEFT) / PX) == 75
    m.flip_origin_mark()                    # and back
    assert round((m.last_origin.mark[0] - LEFT) / PX) == 40


def test_flipping_a_mark_that_has_no_alternative_does_nothing():
    m = _match()
    m.clock.start(t=100.0)
    t = _trace(m, 20, 34, 100.0, 3.0)
    m.key_down("a", t)
    before = m.last_origin.mark
    m.flip_origin_mark()
    assert m.last_origin.mark == before


def test_the_kickers_own_direction_decides_the_on_the_full_law():
    # away intercepts, then kicks from 18m. Away defends the RIGHT line, so
    # 18m is nowhere near its own 22 and the ball comes back to the kick.
    # Using the chain-start team's direction instead would read 18m as deep
    # in its own 22 and wrongly mark the lineout at 40m.
    o = _origin([_seg("PASS", 20, 18, intercepted=True),
                 _seg("KICK", 18, 40, y1=TOUCH_Y)], start_team="home")
    assert o.reason == "lineout"
    assert round((o.mark[0] - LEFT) / PX, 1) == 18.0
