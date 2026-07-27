"""Emulated noisy input: fixture corpus + instant-injection harness.

noisy_path() turns waypoint scripts (metres) into human-ish pixel traces:
speed variation, hand-tremor wobble, corner rounding, sampling jitter —
deterministic per seed. inject_raw()/inject() fire raw inputs through a real
MatchState exactly as the live app would (all logic uses passed-in t, never
wall clock, so instant injection is faithful). check() compares outcomes
against a scenario's `expect` dict.

Consumed by tests/test_corpus.py, sweep.py, and the dev panel's replay.
Pure Python — no NiceGUI imports.
"""

import functools
import json
import math
import random
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .continuity import PathPoint
from .match_state import MatchState

PX = config.PX_PER_M
TRACES_DIR = Path(__file__).parent / "tests" / "traces"  # committed regressions
DEV_TRACES = Path(__file__).parent / "dev_traces"        # scratch, gitignored


def _tremor(rng, wobble_px):
    """wobble(axis, t) -> hand-tremor offset in px, from two sines per axis.

    Physiological tremor is 5-9 Hz: fast enough that the recognizer's 150ms
    heading windows average it out, exactly like a real hand. Slower wobble
    (<4 Hz) reads as deliberate heading change and would test the noise, not
    the recognizer.
    """
    tremor = [[(wobble_px * rng.uniform(0.3, 0.7), rng.uniform(5.0, 9.0),
                rng.uniform(0, 2 * math.pi)) for _ in range(2)] for _ in range(2)]

    def wobble(axis, t):
        return sum(a * math.sin(2 * math.pi * f * t + ph)
                   for a, f, ph in tremor[axis])

    return wobble


def _trace_legs(waypoints, durations, rng, hz, speed_var, wobble):
    """Walk the waypoint script leg by leg -> raw (x_px, y_px, t) samples."""
    raw = []
    t_leg = 0.0
    for (x0, y0), (x1, y1), dur in zip(waypoints, waypoints[1:], durations):
        n = max(2, int(dur * hz))
        phase = rng.uniform(0, 2 * math.pi)
        start = 1 if raw else 0  # skip duplicating the shared corner point
        for i in range(start, n + 1):
            f = i / n
            # integral of speed multiplier 1 + speed_var*sin(2*pi*f + phase):
            # endpoints preserved, monotonic for speed_var < 1
            fw = f + speed_var / (2 * math.pi) * (
                math.cos(phase) - math.cos(2 * math.pi * f + phase))
            t = t_leg + dur * f
            raw.append(((x0 + (x1 - x0) * fw) * PX + wobble(0, t),
                        (y0 + (y1 - y0) * fw) * PX + wobble(1, t), t))
        t_leg += dur
    return raw


def _round_corners(raw, rng, jitter_ms, smooth_pts):
    """Corner rounding (position moving-average) + sampling jitter on t."""
    half = smooth_pts // 2
    pts, prev_t = [], -1.0
    for i in range(len(raw)):
        win = raw[max(0, i - half):i + half + 1]
        t = raw[i][2] + rng.uniform(-jitter_ms, jitter_ms) / 1000
        t = max(t, prev_t + 1e-4)  # strictly increasing
        pts.append(PathPoint(sum(p[0] for p in win) / len(win),
                             sum(p[1] for p in win) / len(win), t))
        prev_t = t
    return pts


def noisy_path(waypoints, durations, seed, hz=60, wobble_px=2.0,
               speed_var=0.2, jitter_ms=3.0, smooth_pts=3):
    """Human-ish trace of the waypoint script, in pixels, t relative from ~0.

    The three passes draw from one rng in a fixed order; changing that order
    reshuffles every seeded fixture in the corpus.
    """
    rng = random.Random(seed)
    wobble = _tremor(rng, wobble_px)
    raw = _trace_legs(waypoints, durations, rng, hz, speed_var, wobble)
    return _round_corners(raw, rng, jitter_ms, smooth_pts)


@dataclass(frozen=True)
class Scenario:
    name: str
    waypoints: tuple = ()   # ((x_m, y_m), ...) metre coords, mid-pitch y≈35
    durations: tuple = ()   # per-leg seconds, len == len(waypoints) - 1
    taps: tuple = ()        # ((rel_t_s, key), ...) fed to MatchState.key_down
    shift: tuple = ()       # ((rel_t0, rel_t1), ...) held-Shift intervals
    expect: dict = field(default_factory=dict)
    attack_dir: int = 1
    possession: str = "home"
    end: str = "a"          # "a" | "mouseup" — how the chain is ended

    @property
    def seed(self) -> int:
        return zlib.crc32(self.name.encode())  # stable across processes


SCENARIOS: dict[str, Scenario] = {}


def _sc(name, **kw):
    SCENARIOS[name] = Scenario(name=name, **kw)


# --- corpus ----------------------------------------------------------------
# Durations set a plausible tracing pace, but classification no longer reads
# absolute speed: the same shapes segment identically at any pace (pinned by
# test_pace_invariance). Distances are what matter — kicks 30m+, carries
# shorter, passes lateral/backward; corners score clear of BOUNDARY_ACCEPT.
CS = dict(waypoints=((10, 35), (22, 35)), durations=(3.0,))       # 1-seg carry
CPC = dict(waypoints=((10, 35), (20, 35), (19, 43), (31, 43)),    # boundary
           durations=(2.5, 0.45, 3.0))                            # ~2.5s, ~2.95s

# geometry: every movement shape the recognizer must get right
_sc("carry_straight", **CS, expect={"actions": ["CARRY"]})
_sc("carry_diagonal", waypoints=((10, 30), (20, 38)), durations=(2.5,),
    expect={"actions": ["CARRY"]})                    # lat 8 < 1.2 x fwd 10
_sc("carry_weave", waypoints=((10, 35), (16, 34), (22, 36), (28, 35)),
    durations=(1.5, 1.5, 1.5),                        # ~28 deg turns: no split
    expect={"forbid": {"PASS", "KICK"}, "n_segments": (1, 2)})
_sc("pass_backward", waypoints=((40, 35), (33, 37)), durations=(0.5,),
    expect={"actions": ["PASS"]})
_sc("pass_lateral", waypoints=((40, 35), (41, 45)), durations=(0.5,),
    expect={"actions": ["PASS"]})
_sc("forward_lateral_carry", waypoints=((40, 35), (46, 45)), durations=(0.6,),
    expect={"actions": ["CARRY"]})   # fwd 6 + lat 10: gains ground => CARRY, not
                                     # a (forward, illegal) pass — the reported bug
_sc("carry_ratio_edge", waypoints=((40, 35), (50, 45)), durations=(1.8,),
    expect={"actions": ["CARRY"]})                    # fwd 10 lat 10: CARRY
_sc("kick_long", waypoints=((30, 35), (68, 33)), durations=(0.55,),
    expect={"actions": ["KICK"]})
_sc("kick_return", waypoints=((30, 35), (62, 35), (52, 34)),
    durations=(0.5, 2.5),                             # receiver runs it back
    expect={"actions": ["KICK", "CARRY"]})
_sc("carry_pass_carry", **CPC, expect={"actions": ["CARRY", "PASS", "CARRY"]})
_sc("carry_pass_carry_kick",
    waypoints=CPC["waypoints"] + ((71, 38),), durations=CPC["durations"] + (0.5,),
    expect={"actions": ["CARRY", "PASS", "CARRY", "KICK"]})
_sc("phase_chain_5",
    waypoints=((10, 35), (18, 35), (17, 42), (26, 42), (25, 50), (34, 50)),
    durations=(2.0, 0.45, 2.2, 0.45, 2.2),
    expect={"actions": ["CARRY", "PASS", "CARRY", "PASS", "CARRY"]})
_sc("switchback_cut", waypoints=((10, 35), (18, 35), (16.5, 35), (26, 35)),
    durations=(2.0, 0.3, 2.0),                        # 300ms agility cut
    expect={"forbid": {"PASS", "KICK"}, "n_segments": (1, 3)})
_sc("hesitation_carry", waypoints=((10, 35), (16, 35), (16.8, 35), (24, 35)),
    durations=(1.5, 0.6, 2.0),                        # slow-down, no turn
    expect={"forbid": {"PASS", "KICK"}, "n_segments": (1, 3)})
_sc("speed_burst_carry", waypoints=((10, 35), (16, 35), (30, 35)),
    durations=(2.0, 1.0),                             # accelerates but stays a
    expect={"forbid": {"PASS", "KICK"}})              # carry-distance run: CARRY
_sc("accidental_twitch", waypoints=((30, 35), (30.3, 35)), durations=(0.2,),
    expect={"rejected": True})
_sc("mirrored_attack", attack_dir=-1,
    waypoints=((90, 35), (80, 35), (81, 43), (69, 43)),
    durations=(2.5, 0.45, 3.0),
    expect={"actions": ["CARRY", "PASS", "CARRY"]})
_sc("away_possession_chain", possession="away",
    waypoints=((60, 35), (48, 35)), durations=(3.0,),
    # plain carry-end = possession lost at the breakdown -> other side
    expect={"actions": ["CARRY"], "possession_after": "home"})

# taps & keys: digits, hints, linebreak, interception
_sc("digit_start_actor", **CS, taps=((0.15, "9"),),
    expect={"actions": ["CARRY"], "players": [(0, 9, "start")]})
_sc("digit_two_digit", **CS, taps=((0.15, "1"), (0.27, "0")),
    expect={"players": [(0, 10, "start")]})
_sc("digit_burst_split", **CS, taps=((0.15, "1"), (0.70, "0")),
    # 550ms gap > DIGIT_BURST_MS: splits into 1 and 0 — the documented sharp edge
    expect={"players": [(0, 1, "start"), (0, 0, "start")]})
_sc("digit_before_boundary", **CPC, taps=((2.30, "1"), (2.42, "2")),
    expect={"players": [(0, 12, "end")]})
_sc("digit_after_boundary", **CPC, taps=((2.62, "7"),),
    expect={"players": [(1, 7, "start")]})
_sc("digit_end_of_chain", **CS, taps=((3.1, "8"),),
    expect={"players": [(0, 8, "end")]})
_sc("hint_k", **CS, taps=((1.0, "k"),),
    # relabel does NOT re-run the kick direction flip (geometry already ran)
    expect={"actions": ["KICK"]})
_sc("hint_p", **CS, taps=((1.0, "p"),), expect={"actions": ["PASS"]})
_sc("hint_r", waypoints=((40, 35), (33, 37)), durations=(0.5,),
    taps=((0.3, "r"),),                               # intercept-return correction
    expect={"actions": ["CARRY"]})
_sc("hint_grace_late", **CS, taps=((3.15, "k"),),
    expect={"actions": ["KICK"]})                     # within 250ms grace
_sc("hint_beyond_grace", **CS, taps=((3.35, "k"),),
    expect={"actions": ["CARRY"]})                    # 350ms > grace: ignored
_sc("linebreak_carry", **CS, taps=((1.5, "l"),), expect={"linebreaks": [0]})
_sc("linebreak_pass_ignored", waypoints=((40, 35), (33, 37)), durations=(0.5,),
    taps=((0.25, "l"),),
    expect={"actions": ["PASS"], "linebreaks": []})   # L only applies to CARRY
_sc("shift_intercept_pass", **CPC, shift=((2.55, 2.90),),
    expect={"intercepted": [1], "possession_after": "away",
            "event_types": ["phase_sequence", "phase_sequence", "turnover_won"]})
_sc("shift_during_carry_only", **CPC, shift=((0.5, 1.5),),
    # no interception, so it's a plain carry/pass chain -> possession lost
    expect={"intercepted": [], "possession_after": "away"})

# state-level: possession keys, kick flips, discrete events, fallback end
_sc("team_key_then_chain", taps=((-0.2, "x"),),       # X tapped before the trace
    waypoints=((60, 35), (48, 35)), durations=(3.0,),
    # X sets away in possession; the carry then ends and hands it back to home
    expect={"actions": ["CARRY"], "possession_after": "home"})
_sc("kick_flips_possession", waypoints=((10, 35), (20, 35), (60, 35)),
    durations=(2.5, 0.5),
    expect={"actions": ["CARRY", "KICK"], "possession_after": "away",
            "event_types": ["phase_sequence"]})
_sc("kick_tennis",
    waypoints=((30, 35), (62, 35), (57, 35), (25, 34), (30, 34)),
    durations=(0.5, 1.2, 0.5, 1.5),                   # kick, return, kick back
    # two kicks land the ball back with home, whose trailing carry then ends
    expect={"actions": ["KICK", "CARRY", "KICK", "CARRY"],
            "possession_after": "away",
            "event_types": ["phase_sequence"] * 3})
_sc("discrete_try_conversion", taps=((0.0, "t"), (5.0, "c")),
    expect={"event_types": ["try", "conversion"]})
_sc("discrete_all_events",
    taps=((0.0, "t"), (5.0, "n"), (10.0, "g"), (15.0, "v"), (20.0, "b")),
    expect={"event_types": ["try", "penalty_kick", "drop_goal",
                            "turnover_won", "sin_bin"],
            "possession_after": "away"})
_sc("mouseup_fallback_end", **CS, end="mouseup",
    expect={"actions": ["CARRY"], "event_types": ["phase_sequence"]})


# --- harness ---------------------------------------------------------------
def _merge_stream(points, taps, shift):
    """(t, kind, payload) in timestamp order; kind: 0=down 1=move 2=keydown 3=keyup."""
    stream = []
    for i, (x, y, t) in enumerate(points):
        stream.append((t, 0 if i == 0 else 1, (x, y)))
    for key, t in taps:
        stream.append((t, 2, key))
    for t_down, t_up in shift:
        stream.append((t_down, 2, "shift"))
        stream.append((t_up, 3, "shift"))
    stream.sort(key=lambda ev: (ev[0], ev[1]))
    return stream


def _fire(match, kind, payload, t):
    """Replay one merged event into the MatchState."""
    if kind == 0:
        match.mouse_down(payload[0], payload[1], t)
    elif kind == 1:
        match.mouse_move(payload[0], payload[1], t)
    elif kind == 2:
        match.key_down(payload, t)
    else:
        match.key_up(payload, t)


def inject_raw(match, points, taps=(), shift=(), t0=0.0, end="a"):
    """Fire raw inputs into a MatchState instantly, merged in timestamp order.

    points: [[x, y, t_rel], ...]; taps: [[key, t_rel], ...];
    shift: [[t_down, t_up], ...] — exactly the saved-trace JSON shape.
    Ends the chain (key 'a' or mouse_up) just after the last input.
    Returns match.last_chain.
    """
    stream = _merge_stream(points, taps, shift)
    for t, kind, payload in stream:
        _fire(match, kind, payload, t0 + t)
    if points:
        t_end = t0 + max(ev[0] for ev in stream) + 0.05
        if end == "a":
            match.key_down("a", t_end)
        else:
            match.mouse_up(t_end)
    return match.last_chain


def inject(match, sc: Scenario, t0=0.0):
    """Run a scenario's synthetic inputs; the caller owns match setup."""
    pts = noisy_path(sc.waypoints, sc.durations, sc.seed) if sc.waypoints else []
    return inject_raw(match, [[p.x, p.y, p.t] for p in pts],
                      taps=[[k, t] for t, k in sc.taps],
                      shift=sc.shift, t0=t0, end=sc.end)


# --- expect-vocabulary checks ----------------------------------------------
# Each takes (match, segs, expect) and returns (want, got) on failure, else
# None. CHECKS is ordered: it decides the order failures are reported in.
def _check_actions(match, segs, expect):
    got = [s.action for s in segs]
    if got != expect["actions"]:
        return expect["actions"], got or "no chain"
    return None


def _check_forbid(match, segs, expect):
    got = [s.action for s in segs]
    if any(a in expect["forbid"] for a in got):
        return f"none of {sorted(expect['forbid'])}", got
    return None


def _check_n_segments(match, segs, expect):
    want = expect["n_segments"]
    lo, hi = (want, want) if isinstance(want, int) else want
    if not lo <= len(segs) <= hi:
        return want, len(segs)
    return None


def _check_rejected(match, segs, expect):
    if not expect["rejected"]:      # falsy value means "don't check"
        return None
    if match.last_chain is not None or not match.last_debug.get("rejected"):
        got = [s.action for s in segs]
        return "rejected chain", got or "no rejection reason"
    return None


def _check_linebreaks(match, segs, expect):
    got = [i for i, s in enumerate(segs) if s.linebreak]
    if got != expect["linebreaks"]:
        return expect["linebreaks"], got
    return None


def _check_intercepted(match, segs, expect):
    got = [i for i, s in enumerate(segs) if s.intercepted]
    if got != expect["intercepted"]:
        return expect["intercepted"], got
    return None


def _check_players(match, segs, expect):
    got = [(i, p.number, p.role) for i, s in enumerate(segs) for p in s.players]
    want = [tuple(w) for w in expect["players"]]
    if got != want:
        return want, got
    return None


def _check_possession_after(match, segs, expect):
    if match.possession != expect["possession_after"]:
        return expect["possession_after"], match.possession
    return None


def _check_event_types(match, segs, expect):
    got = [e["type"] for e in match.events]
    if got != expect["event_types"]:
        return expect["event_types"], got
    return None


CHECKS = {
    "actions": _check_actions,
    "forbid": _check_forbid,
    "n_segments": _check_n_segments,
    "rejected": _check_rejected,
    "linebreaks": _check_linebreaks,
    "intercepted": _check_intercepted,
    "players": _check_players,
    "possession_after": _check_possession_after,
    "event_types": _check_event_types,
}


def check(match, expect: dict) -> list[str]:
    """Compare outcome against the expect vocabulary; [] = pass."""
    segs = match.last_chain.segments if match.last_chain else []
    out = []
    for key, checker in CHECKS.items():
        if key not in expect:
            continue
        failure = checker(match, segs, expect)
        if failure is not None:
            want, got = failure
            out.append(f"{key}: expected {want}, got {got}")
    return out


def open_play_match(attack_dir=1, possession="home",
                    home="HOME", away="AWAY") -> MatchState:
    """A MatchState with no set piece pending, clock running.

    A corpus case is a bare traced line being judged on its geometry, but a
    freshly built match is legitimately waiting on a kickoff — which snaps the
    start to the centre spot and forces the first segment to a KICK. Clearing
    the pending reason is what makes the scenario mean what it says.
    """
    m = MatchState(home, away, attack_dir_home=attack_dir,
                   possession=possession)
    m.pending_start_reason = None
    m.clock.start(t=0.0)
    return m


def run(sc: Scenario) -> list[str]:
    """Fresh MatchState -> inject -> check. The uniform corpus runner."""
    m = open_play_match(sc.attack_dir, sc.possession)
    inject(m, sc)
    return check(m, sc.expect)


def run_trace_file(path) -> list[str]:
    """Saved-trace JSON -> fresh MatchState -> inject_raw -> check."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    m = open_play_match(d.get("attack_dir_home", 1), d.get("possession", "home"))
    inject_raw(m, d["points"], d.get("taps", ()), d.get("shift", ()))
    return check(m, d.get("expect", {}))


def iter_cases():
    """(name, runner) per scenario + committed real-trace regressions."""
    cases = [(name, functools.partial(run, sc)) for name, sc in SCENARIOS.items()]
    if TRACES_DIR.is_dir():
        cases += [(f"trace:{f.stem}", functools.partial(run_trace_file, f))
                  for f in sorted(TRACES_DIR.glob("*.json"))]
    return cases
