"""Phase-4 proof: tracer output feeds the REAL RugbySport translator.

Expected weights are hand-computed from _territory_weight()'s formula and
hard-coded, so a drift in either side fails loudly.
"""

from core.engine import MomentumEngine
from translators.rugby import RugbySport

from tracer import config
from tracer.continuity import PathPoint, PlayChain, PlayerTag, Segment
from tracer.events import assign_teams, chain_to_events, summarise
from tracer import fixtures
from tracer.match_state import MatchState

PX = config.PX_PER_M
LEFT = config.IN_GOAL_DEPTH_M * PX
NAMES = {"home": "ENG", "away": "WAL"}


def seg(action, x0_m, x1_m, t0, t1, **kw):
    return Segment(action=action,
                   points=[PathPoint(LEFT + x0_m * PX, 280, t0),
                           PathPoint(LEFT + x1_m * PX, 280, t1)], **kw)


def make_chain(segments, team="home", start_minute=12.4):
    chain = PlayChain(chain_id="c1", team=team, start_minute=start_minute,
                      segments=segments)
    assign_teams(segments, team)
    return chain


def test_single_possession_weight_matches_hand_computed():
    # 10m -> 33m net, ends 67m out, one linebreak:
    # base = .15 + .35*(23/40) = .35125; territory = .3*(1-.67) = .099
    # weight = round((.35125+.099)*1.25, 2) = 0.56
    chain = make_chain([
        seg("CARRY", 10, 20, 100.0, 102.5),
        seg("PASS", 20, 19, 102.5, 103.0),
        seg("CARRY", 19, 33, 103.0, 106.0, linebreak=True),
    ])
    events = chain_to_events(chain, NAMES, attack_dir_home=1)
    assert len(events) == 1
    ev = events[0]
    assert ev["type"] == "phase_sequence" and ev["team"] == "ENG"
    assert ev["metres_gained"] == 23.0
    assert ev["end_metres_from_line"] == 67.0
    assert ev["linebreaks"] == 1
    (std,) = RugbySport().translate(events)
    assert std.weight == 0.56
    assert std.team == "ENG" and std.t == 12.4


def test_kick_splits_chain_no_turnover():
    chain = make_chain([
        seg("CARRY", 10, 20, 100.0, 102.5),
        seg("KICK", 20, 60, 102.5, 103.1),
        seg("CARRY", 60, 55, 103.1, 106.0),  # receiver (away) attacks -x
    ])
    events = chain_to_events(chain, NAMES, attack_dir_home=1)
    assert [e["type"] for e in events] == ["phase_sequence", "phase_sequence"]
    kicker, receiver = events
    assert kicker["team"] == "ENG" and kicker["metres_gained"] == 50.0
    assert receiver["team"] == "WAL" and receiver["metres_gained"] == 5.0
    assert receiver["end_metres_from_line"] == 55.0  # 55m from left try line


def test_interception_splits_and_logs_turnover():
    chain = make_chain([
        seg("CARRY", 30, 40, 100.0, 102.0),
        seg("PASS", 40, 39, 102.0, 102.4, intercepted=True),
        seg("CARRY", 39, 25, 102.4, 105.0),
    ])
    events = chain_to_events(chain, NAMES, attack_dir_home=1)
    assert [e["type"] for e in events] == ["phase_sequence", "phase_sequence",
                                           "turnover_won"]
    assert events[2]["team"] == "WAL"
    assert events[1]["metres_gained"] == 14.0  # 39 -> 25 toward -x


def test_players_attached():
    s = seg("CARRY", 10, 20, 100.0, 102.5)
    s.players.append(PlayerTag(number=9, role="start", at_ts=100.1))
    events = chain_to_events(make_chain([s]), NAMES, attack_dir_home=1)
    assert events[0]["players"] == [{"number": 9, "role": "start"}]


def test_match_state_full_flow_trace_plus_taps():
    """Phase-4 exit criteria: traced + tap-annotated chain -> expected weight."""
    # mid-match: a fresh match is waiting on a kickoff, which snaps the start
    # to the centre spot and forces a KICK — a carry can't be traced from it
    m = fixtures.open_play_match(home="ENG", away="WAL")
    m.pending_start_reason = "lineout"
    m.clock.start(t=100.0)
    m.mouse_down(LEFT + 10 * PX, 280, 100.0)
    for i in range(1, 151):  # 10m -> 20m carry over 2.5s at 60Hz
        m.mouse_move(LEFT + (10 + 10 * i / 150) * PX, 280, 100.0 + 2.5 * i / 150)
    m.key_down("9", 100.15)   # actor tapped just after chain start
    m.key_down("l", 101.2)    # linebreak mid-carry
    m.key_down("a", 102.6)    # authoritative chain end
    assert not m.recorder.active
    (ev,) = m.events
    # 10m gained, ends 80m out, 1 linebreak, off a lineout (origin factor 1.15):
    # round((.15+.35*.25 + .3*.2)*1.25*1.15, 2) = 0.43
    assert ev["metres_gained"] == 10.0
    assert ev["end_metres_from_line"] == 80.0
    assert ev["linebreaks"] == 1
    assert ev["start_reason"] == "lineout"
    assert ev["players"] == [{"number": 9, "role": "start"}]
    (std,) = RugbySport().translate([ev])
    assert std.weight == 0.43
    # evidence capture: raw inputs + segmentation debug snapshot per chain
    assert m.chain_seq == 1
    assert m.last_chain is not None
    assert len(m.last_raw["points"]) == 151
    assert m.last_debug["segments"]


def test_discrete_events_and_conversion_window():
    m = MatchState("ENG", "WAL")
    m.clock.start(t=100.0)
    m.key_down("t", 160.0)                    # ENG try at 1'
    m.key_down("c", 200.0)                    # conversion within window
    m.key_down("v", 260.0)                    # WAL turnover; possession flips
    assert m.possession == "away"
    m.key_down("b", 300.0)                    # sin bin: against non-possessing ENG
    types = [(e["type"], e["team"]) for e in m.events]
    assert types == [("try", "ENG"), ("conversion", "ENG"),
                     ("turnover_won", "WAL"), ("sin_bin", "ENG")]


# --- origin as context on the possession's weight --------------------------
def test_origin_scales_the_territory_weight():
    base = {"type": "phase_sequence", "team": "ENG", "minute": 5.0,
            "metres_gained": 20.0, "end_metres_from_line": 40.0, "linebreaks": 0}
    plain = RugbySport().translate([base])[0].weight
    off_lineout = RugbySport().translate(
        [{**base, "start_reason": "lineout"}])[0].weight
    off_restart = RugbySport().translate(
        [{**base, "start_reason": "restart"}])[0].weight
    assert off_lineout > plain > off_restart


def test_unknown_origin_leaves_the_weight_alone():
    base = {"type": "phase_sequence", "team": "ENG", "minute": 5.0,
            "metres_gained": 20.0, "end_metres_from_line": 40.0, "linebreaks": 0}
    plain = RugbySport().translate([base])[0].weight
    assert RugbySport().translate(
        [{**base, "start_reason": "nonsense"}])[0].weight == plain


def test_penalty_won_is_a_standalone_swing():
    # a concrete weight, not just "> 0": _default would satisfy that and the
    # whole point is that this type is declared rather than swallowed
    (std,) = RugbySport().translate(
        [{"type": config.PENALTY_WON_TYPE, "team": "ENG", "minute": 5.0}])
    assert std.weight == 0.6


# --- chain origin on the export --------------------------------------------
def test_first_sub_chain_carries_the_origin_and_its_field_position():
    chain = make_chain([seg("CARRY", 20, 34, 0.0, 2.0)], team="home")
    evs = chain_to_events(chain, NAMES, attack_dir_home=1, start_reason="lineout")
    assert evs[0]["start_reason"] == "lineout"
    assert evs[0]["start_metres_from_line"] == 80.0


def test_only_the_first_sub_chain_carries_the_origin():
    # the kick splits possession; the second sub-chain's origin is already
    # implied by the kick that created it
    chain = make_chain([seg("KICK", 20, 60, 0.0, 1.0),
                        seg("CARRY", 60, 70, 1.0, 3.0)], team="home")
    evs = chain_to_events(chain, NAMES, attack_dir_home=1, start_reason="scrum")
    assert evs[0]["start_reason"] == "scrum"
    assert "start_reason" not in evs[1]


def test_origin_is_omitted_when_there_is_none():
    chain = make_chain([seg("CARRY", 20, 34, 0.0, 2.0)], team="home")
    evs = chain_to_events(chain, NAMES, attack_dir_home=1)
    assert "start_reason" not in evs[0]
    assert evs[0]["start_metres_from_line"] == 80.0   # position is free either way


# --- commit feedback -------------------------------------------------------
def test_summary_names_team_action_sequence_and_metres():
    evs = [{"type": "phase_sequence", "team": "ENG", "metres_gained": 12.0}]
    assert summarise(evs, ["CARRY", "PASS"]) == "ENG · CARRY-PASS · 12m"


def test_summary_sums_metres_across_an_intercepted_chain():
    evs = [{"type": "phase_sequence", "team": "ENG", "metres_gained": 8.0},
           {"type": "turnover_won", "team": "WAL"},
           {"type": "phase_sequence", "team": "WAL", "metres_gained": 5.5}]
    assert summarise(evs, ["CARRY", "PASS", "CARRY"]) == \
        "ENG · CARRY-PASS-CARRY · 13.5m"


def test_summary_of_nothing_is_empty():
    assert summarise([], []) == ""


def test_synthetic_match_round_trips_through_engine():
    m = MatchState("ENG", "WAL")
    m.clock.start(t=0.0)
    m.key_down("t", 60.0)
    m.key_down("n", 120.0)  # note: N logs for possessing team (still home)
    chain = make_chain([seg("CARRY", 10, 30, 200.0, 205.0)], team="away")
    m.events.extend(chain_to_events(chain, NAMES, attack_dir_home=1))
    std = RugbySport().translate(m.events)
    MomentumEngine(half_life_minutes=4.5).compute(std, "ENG", "WAL", 82)  # must not raise
