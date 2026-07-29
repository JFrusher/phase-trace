"""Per-action stream: chain_to_actions + MatchState.actions wiring.

chain_to_actions is the raw-export counterpart to chain_to_events: it keeps
every carry/pass/kick as its own row (not collapsed into a phase_sequence) so
a coach gets per-action detail. Player/flag fields are optional — a
partially-tagged chain is still valid data.
"""

import pytest

from tracer import config, fixtures
from tracer.continuity import PathPoint, PlayChain, PlayerTag, Segment
from tracer.events import actor, assign_teams, chain_to_actions
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


# --- chain_to_actions (pure) ------------------------------------------------
def test_one_row_per_segment_with_metres():
    chain = make_chain([
        seg("CARRY", 10, 20, 100.0, 102.5),
        seg("PASS", 20, 19, 102.5, 103.0),
        seg("CARRY", 19, 33, 103.0, 106.0),
    ])
    acts = chain_to_actions(chain, NAMES, attack_dir_home=1)
    assert [a["type"] for a in acts] == ["carry", "pass", "carry"]
    assert all(a["team"] == "ENG" for a in acts)
    assert acts[0]["metres_gained"] == 10.0
    assert acts[0]["end_metres_from_line"] == 80.0
    assert acts[2]["metres_gained"] == 14.0
    assert acts[0]["minute"] == 12.4


def test_player_attributed_when_tagged_absent_otherwise():
    tagged = seg("CARRY", 10, 20, 100.0, 102.5)
    tagged.players.append(PlayerTag(number=7, role="start", at_ts=100.1))
    plain = seg("CARRY", 20, 30, 102.5, 104.0)
    acts = chain_to_actions(make_chain([tagged, plain]), NAMES, attack_dir_home=1)
    assert acts[0]["player"] == 7
    assert "player" not in acts[1]


def test_end_role_tag_still_attributes():
    s = seg("CARRY", 10, 20, 100.0, 102.5)
    s.players.append(PlayerTag(number=4, role="end", at_ts=102.4))
    assert actor(s) == 4      # falls back to any tag when no "start" present


def test_start_role_wins_over_end():
    s = seg("CARRY", 10, 20, 100.0, 102.5)
    s.players.append(PlayerTag(number=4, role="end", at_ts=100.0))
    s.players.append(PlayerTag(number=7, role="start", at_ts=100.1))
    assert actor(s) == 7


def test_optional_flags_only_present_when_set():
    lb = seg("CARRY", 10, 25, 100.0, 103.0, linebreak=True)
    icpt = seg("PASS", 25, 24, 103.0, 103.4, intercepted=True)
    acts = chain_to_actions(make_chain([lb, icpt]), NAMES, attack_dir_home=1)
    assert acts[0]["linebreak"] is True and "intercepted" not in acts[0]
    assert acts[1]["intercepted"] is True and "linebreak" not in acts[1]


def test_kick_attributes_to_kicking_team_receiver_to_other():
    acts = chain_to_actions(make_chain([
        seg("CARRY", 10, 20, 100.0, 102.0),
        seg("KICK", 20, 60, 102.0, 102.6),
        seg("CARRY", 60, 55, 102.6, 105.0),   # receiver attacks -x = away
    ]), NAMES, attack_dir_home=1)
    assert acts[1]["type"] == "kick" and acts[1]["team"] == "ENG"
    assert acts[2]["team"] == "WAL"


def test_start_reason_stamped_on_the_first_action_of_a_possession():
    acts = chain_to_actions(make_chain([
        seg("CARRY", 10, 20, 100.0, 102.5),
        seg("CARRY", 20, 30, 102.5, 104.0),
    ]), NAMES, attack_dir_home=1, start_reason="lineout")
    assert acts[0]["start_reason"] == "lineout"
    assert "start_reason" not in acts[1]   # same possession, same team


def test_a_kick_inside_a_chain_names_the_possession_it_started():
    """A handover mid-chain begins a possession as much as one between chains.

    Both used to be treated differently: a chain that ENDED on a kick handed the
    next one `kick_return`, while a kick in the middle of one left the receiving
    run with no origin at all — about one possession in six reaching the export
    unable to say how it began.
    """
    acts = chain_to_actions(make_chain([
        seg("KICK", 20, 60, 100.0, 101.0),
        seg("CARRY", 60, 70, 101.0, 103.0),
    ]), NAMES, attack_dir_home=1, start_reason="scrum")
    assert [a["start_reason"] for a in acts] == ["scrum", "kick_return"]
    assert acts[0]["team"] != acts[1]["team"]


def test_an_interception_inside_a_chain_names_the_possession_it_started():
    acts = chain_to_actions(make_chain([
        seg("PASS", 40, 38, 100.0, 100.5, intercepted=True),
        seg("CARRY", 38, 30, 100.5, 102.0),
    ]), NAMES, attack_dir_home=1, start_reason="lineout")
    assert [a["start_reason"] for a in acts] == ["lineout", "interception"]


def test_start_reason_absent_when_not_given():
    acts = chain_to_actions(make_chain([seg("CARRY", 10, 20, 100.0, 102.5)]),
                            NAMES, attack_dir_home=1)
    assert "start_reason" not in acts[0]


def test_empty_chain_yields_no_actions():
    assert chain_to_actions(make_chain([]), NAMES, attack_dir_home=1) == []


def test_contact_outcome_lands_on_the_action_it_ended():
    """It describes the contact that ended the possession, so it belongs on the
    last action -- the mirror of start_reason on the first."""
    acts = chain_to_actions(make_chain([
        seg("CARRY", 80, 90, 100.0, 102.0),
        seg("CARRY", 90, 103, 102.0, 104.0),
    ]), NAMES, attack_dir_home=1, contact_outcome="held_up")
    assert "contact_outcome" not in acts[0]
    assert acts[1]["contact_outcome"] == "held_up"


def test_contact_outcome_absent_when_not_given():
    acts = chain_to_actions(make_chain([seg("CARRY", 90, 103, 100.0, 102.0)]),
                            NAMES, attack_dir_home=1)
    assert "contact_outcome" not in acts[0]


@pytest.mark.parametrize("action", ["KICK", "PASS"])
def test_only_a_carry_takes_a_contact_outcome(action):
    """The in-goal chooser offers held-up whatever the last segment was, and you
    cannot hold up a kick. The guard drops the nonsense pick rather than
    publishing it."""
    acts = chain_to_actions(make_chain([
        seg("CARRY", 60, 80, 100.0, 102.0),
        seg(action, 80, 103, 102.0, 103.0),
    ]), NAMES, attack_dir_home=1, contact_outcome="held_up")
    assert not [a for a in acts if "contact_outcome" in a]


# --- MatchState wiring ------------------------------------------------------
def _trace_carry(m, x0_m, x1_m, t0, dur, taps=()):
    m.mouse_down(LEFT + x0_m * PX, 280, t0)
    n = 150
    for i in range(1, n + 1):
        m.mouse_move(LEFT + (x0_m + (x1_m - x0_m) * i / n) * PX, 280,
                     t0 + dur * i / n)
    for key, kt in taps:
        m.key_down(key, kt)
    m.key_down("a", t0 + dur + 0.1)   # authoritative chain end


def test_actions_populated_on_commit_and_cleared_by_undo():
    m = fixtures.open_play_match(home="ENG", away="WAL")
    m.pending_start_reason = "lineout"
    m.clock.start(t=100.0)
    _trace_carry(m, 10, 20, 100.0, 2.5, taps=[("9", 100.15)])
    assert m.actions and m.actions[0]["type"] == "carry"
    assert m.actions[0]["player"] == 9
    m.undo_last()
    assert m.actions == []            # undo truncates the action log too


def test_actions_survive_persistence_round_trip():
    m = fixtures.open_play_match(home="ENG", away="WAL")
    m.pending_start_reason = "lineout"
    m.clock.start(t=100.0)
    _trace_carry(m, 10, 25, 100.0, 3.0, taps=[("8", 100.15)])
    d = m.to_dict()
    assert d["actions"][0]["player"] == 8
    assert MatchState.from_dict(d).actions == m.actions


def test_log_try_carries_scorer_and_assist():
    m = MatchState("ENG", "WAL")
    m.clock.start(t=0.0)
    m._log_try("home", 60.0, player=11, assist=10)
    ev = m.events[-1]
    assert ev["type"] == "try" and ev["player"] == 11 and ev["assist"] == 10


def test_log_try_omits_scorer_when_untagged():
    m = MatchState("ENG", "WAL")
    m.clock.start(t=0.0)
    m._log_try("home", 60.0)
    assert "player" not in m.events[-1] and "assist" not in m.events[-1]
