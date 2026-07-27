"""Match/clock/possession orchestration + tap dispatch. Pure (no NiceGUI).

app.py wires UI events in and reads state back; optional callbacks
(on_commit, on_change) let the UI react without this module importing it.
"""

import math
import time
from typing import Optional

from . import config, segmentation
from .continuity import ChainRecorder, PlayChain, new_chain_id
from .events import (actor, assign_teams, chain_to_actions, chain_to_events,
                     ChainOrigin, default_in_goal_outcome, halfway_mark,
                     in_goal_defender, infer_origin, penalty_at_goal_scored,
                     set_piece_record, summarise, RESTART_SCORE_TYPES)
from .geometry import canonical_xy, PitchCalibration
from .keystate import KeyState
from .segmentation import apply_taps, reclassify_downstream, segment_path


def _other(team):
    return "away" if team == "home" else "home"


class MatchClock:
    """start/pause wall clock; time.monotonic()-based, rehydrates paused."""

    def __init__(self, base_seconds: float = 0.0):
        self.base_seconds = base_seconds
        self.running = False
        self._started_at: Optional[float] = None

    def start(self, t: Optional[float] = None):
        if not self.running:
            self._started_at = time.monotonic() if t is None else t
            self.running = True

    def pause(self, t: Optional[float] = None):
        if self.running:
            now = time.monotonic() if t is None else t
            self.base_seconds += now - self._started_at
            self.running = False
            self._started_at = None

    def toggle(self):
        self.pause() if self.running else self.start()

    def seconds(self, t: Optional[float] = None) -> float:
        now = time.monotonic() if t is None else t
        return self.base_seconds + (now - self._started_at if self.running else 0.0)

    def minute(self, t: Optional[float] = None) -> float:
        return self.seconds(t) / 60


class MatchState:
    def __init__(self, home: str, away: str, attack_dir_home: int = 1,
                 possession: str = "home", cal: Optional[PitchCalibration] = None,
                 team_colors: Optional[dict] = None, date: str = "",
                 competition: str = ""):
        self.team_names = {"home": home, "away": away}
        self.team_colors = dict(team_colors or config.TEAM_COLORS)
        self.date = date              # self-describing metadata for the export
        self.competition = competition
        self.possession = possession
        self.kickoff_team = possession   # who kicked off; the other side does H2
        self.attack_dir_home = attack_dir_home
        # the first-half orientation. Every exported position is folded back to
        # this frame (see _flipped / geometry.canonical_xy) so second-half data
        # shares one orientation with the first — heatmaps and per-team maps
        # aggregate across the whole match instead of splitting to both ends.
        self.canon_attack_dir_home = attack_dir_home
        self.cal = cal or PitchCalibration()
        self.clock = MatchClock()
        self.keystate = KeyState()
        self.recorder = ChainRecorder()
        self.events: list[dict] = []
        # rich per-action stream for the raw export, kept separate from
        # self.events so nothing new can break the validated momentum path
        self.actions: list[dict] = []
        self._chain_start_minute: Optional[float] = None
        self._chain_events_start = 0   # len(events) at chain start, for score detection
        self.last_end_reason: Optional[str] = None  # "kick"/"turnover"/"score"
        self._pending_try = None  # (team_key, deadline_monotonic)
        self._undo = None         # state snapshot taken at mouse_down
        self._precommit = None    # state snapshot taken at commit, for re-classify
        self.last_summary = ""    # one-line commit description for the UI toast
        # how the NEXT possession begins, and whether a penalty option has
        # pre-armed what the next stroke means. Two nullable fields, not a
        # state machine: nothing here can get stuck.
        self.pending_start_reason = "kickoff"
        self.armed_next_action = None
        self.last_origin = None   # ChainOrigin for the chip the UI draws
        self.penalty_option = None
        self.penalty_reason = None   # chooser pick for the last penalty won
        self._last_penalty = None    # the penalty_won event a reason attaches to
        self.in_goal_choice = None   # what the last chain's in-goal end meant
        self._in_goal_override = None  # the chooser's pick, cleared per chain
        self._snap = (0.0, 0.0)   # path shift onto the centre spot, per chain
        self._chain_start_team = possession
        self.on_commit = None     # callback(chain) after a chain is committed
        self.on_change = None     # callback() after any state change
        self.on_correction = None  # callback(payload) when an operator corrects a tag
        # dev-panel evidence: last end_chain attempt, accepted or rejected
        self.chain_seq = 0
        self.last_debug: dict = {}
        self.last_raw: Optional[dict] = None
        self.last_chain: Optional[PlayChain] = None

    # --- mouse -----------------------------------------------------------
    def mouse_down(self, x, y, t):
        """Begin a chain. Returns the point actually recorded, which the canvas
        draws from — a snapped start must not leave the line and the data
        disagreeing about where the play began.

        The new possession begins at the mark the last one left (a lineout, a
        scrum, the spot a turnover happened, the centre spot for a restart), so
        the whole path is shifted onto it rather than only its first point:
        moving the start alone would turn the gap between the mark and a sloppy
        press into a leg of its own, and that leg would become a phantom action.
        """
        self._snap = (0.0, 0.0)
        mark = self._start_mark()
        if mark is not None:
            mx, my = mark
            self._snap = (mx - x, my - y)
            x, y = mx, my
        self.recorder.start(x, y, t)
        self._chain_start_minute = self.clock.minute(t)
        self._chain_events_start = len(self.events)
        self._chain_start_team = self.possession
        # snapshot here, not in end_chain: taps landing mid-trace (a try, a
        # turnover) already mutated events and possession by the time the
        # chain commits, and undo has to take those back too
        self._undo = (len(self.events), len(self.actions), self.possession,
                      self.last_end_reason, self._pending_try,
                      self.pending_start_reason, self.armed_next_action)
        return x, y

    def _start_mark(self):
        """Where the pending possession begins, or None to press free-hand.

        Every inferred origin already carries the mark its chip is drawn at, so
        the next trace snaps onto it. The initial kickoff has no origin yet, so
        a centre-spot reason falls back to halfway.
        """
        o = self.last_origin
        if o is not None and o.mark is not None:
            return o.mark
        if self.pending_start_reason in config.CENTRE_SPOT_REASONS:
            return halfway_mark(self.cal)
        return None

    def mouse_move(self, x, y, t):
        """Returns the recorded point, which the canvas draws (see mouse_down)."""
        x, y = x + self._snap[0], y + self._snap[1]
        self.recorder.extend(x, y, t)
        if self.recorder.active and self._left_field(x, y):
            self.end_chain(t)   # ball out of play: the play is over, in law
        return x, y

    def _left_field(self, x, y) -> bool:
        """Has the ball just gone out of play — touch, or the dead-ball line?

        Guarded by the same displacement segment_path() rejects on, so a trace
        started on a line cannot end itself before it has drawn anything.
        Proximity is deliberately not enough here: a winger runs inside the
        touch margin all game without going out.
        """
        pts = self.recorder.points
        if len(pts) < 3:
            return False
        if math.hypot(x - pts[0].x, y - pts[0].y) < config.MIN_MOVEMENT_PX:
            return False
        return self.cal.crossed_touch(y) or self.cal.crossed_dead_ball(x)

    def mouse_up(self, t):
        """Fallback chain-end: primary flow is the A/Space tap."""
        if self.recorder.active:
            self.end_chain(t)

    # --- keys --------------------------------------------------------------
    def key_down(self, key: str, t: float):
        k = key.lower()
        if k in config.TAPPED_START_REASONS:
            self._tap_origin(k, t)
        elif k in config.END_CHAIN_KEYS:
            if self.recorder.active:
                self.end_chain(t)
        elif k in config.TEAM_KEYS:
            self.possession = config.TEAM_KEYS[k]
            self._changed()
        elif k in config.DISCRETE_EVENT_KEYS:
            self._discrete_event(k, t)
        elif k in config.CONVERSION_KEYS:
            self._conversion(k, t)
        elif k in config.ERROR_KEYS:
            self._log_error(k, t)
        else:
            self.keystate.key_down(key, t)

    def key_up(self, key: str, t: float):
        self.keystate.key_up(key, t)

    # --- chain lifecycle ---------------------------------------------------
    def end_chain(self, t: float) -> Optional[PlayChain]:
        points = self.recorder.finish()
        self._in_goal_override = None   # a chooser pick never outlives its chain
        taps = list(self.keystate.taps)
        intervals = self.keystate.intervals_until(t)
        self.keystate.clear_chain()
        self.chain_seq += 1
        self.last_raw = {"points": [[p.x, p.y, p.t] for p in points],
                         "taps": [[tp.key, tp.t] for tp in taps],
                         "shift": [list(iv) for iv in intervals],
                         "possession": self.possession,
                         "attack_dir_home": self.attack_dir_home}
        attack_dir = (self.attack_dir_home if self.possession == "home"
                      else -self.attack_dir_home)
        force = ("KICK" if self.pending_start_reason in config.KICK_START_REASONS
                 or self.armed_next_action in config.KICK_ARMED_ACTIONS
                 else None)
        segments = segment_path(points, attack_dir, force_first=force)
        self.last_debug = segmentation.last_debug  # by ref; apply_taps appends
        if not segments:
            self.last_chain = None
            return None
        pre = [s.action for s in segments]   # geometric labels before hint relabels
        apply_taps(segments, taps, intervals)
        chain = PlayChain(
            chain_id=new_chain_id(),
            team=self.possession,
            start_minute=self._chain_start_minute
            if self._chain_start_minute is not None else self.clock.minute(t),
            segments=segments,
        )
        self.last_chain = chain
        self._log_hints(chain, segments, pre)
        self._commit_chain(chain)
        return chain

    def _commit_chain(self, chain):
        """Team assignment, origin inference and export for one chain.

        Separate from end_chain so re-classifying a segment can rewind and run
        it again over the same points — the alternative is duplicating the
        whole tail and letting the two copies drift.
        """
        segments = chain.segments
        # Snapshot the pre-commit state so re-classifying can rerun this
        # cleanly. mouse_down's undo snapshot is no use: re-classifying happens
        # via a CLICK, which is itself a mouse_down and overwrites that
        # snapshot with the post-commit state before the handler runs.
        self._precommit = (self._chain_events_start, len(self.events),
                           len(self.actions), self.possession,
                           self.last_end_reason, self._pending_try,
                           self.pending_start_reason, self.armed_next_action)
        final_team = assign_teams(segments, chain.team)
        scored_team, try_team = self._resolve_score(segments)
        # the reason this chain BEGAN was decided when the last one ended;
        # capture it before inference overwrites it with the next one
        began_as = self.pending_start_reason
        origin = infer_origin(segments=segments, chain_start_team=chain.team,
                              final_team=final_team, scored_team=scored_team,
                              armed=self.armed_next_action,
                              attack_dir_home=self.attack_dir_home, cal=self.cal,
                              in_goal_outcome=self.in_goal_choice)
        self.possession = origin.team
        self.pending_start_reason = origin.reason
        self.last_origin = origin
        self.armed_next_action = None      # one-shot: arming never outlives a stroke
        self.last_end_reason = ("score" if scored_team
                                else "kick" if segments[-1].action == "KICK"
                                else "turnover")
        self._emit_chain(chain, segments, began_as, try_team)
        if self.on_commit:
            self.on_commit(chain)

    def _resolve_score(self, segments) -> tuple:
        """(scored_team, try_team), also setting self.in_goal_choice.

        A trace that finished over a try line: the geometry guesses, the chip's
        chooser overrides. A try is expressed as a scored_team, so everything
        downstream (score, restart, conversion listener) is the path the T tap
        already takes. A tapped score outranks all of it, and hides the chooser
        rather than offering a control that can't win.
        """
        scored_team = self._scored_team_this_chain()
        self.in_goal_choice = None
        if self.armed_next_action == "kick_at_goal":
            # a kick at goal is judged by the posts, not by grounding: no
            # try/held-up chooser, and a line through the uprights is the score
            kick = segments[0]
            kick_dir = (self.attack_dir_home if kick.team == "home"
                        else -self.attack_dir_home)
            if not scored_team and penalty_at_goal_scored(kick, kick_dir, self.cal):
                self._log_penalty_kick(kick.team, kick.end_t)
                scored_team = kick.team
        elif not scored_team:
            self.in_goal_choice = self._in_goal_override or default_in_goal_outcome(
                segments, self.attack_dir_home, self.cal)
        if self.in_goal_choice == "try":
            scored_team = try_team = self._in_goal_attacker(segments)
            return scored_team, try_team
        return scored_team, None

    def _emit_chain(self, chain, segments, began_as, try_team):
        """Turn the committed chain into events, actions, set-piece + try records."""
        flip = self._flipped()
        new_events = chain_to_events(
            chain, self.team_names, self.attack_dir_home, self.cal,
            start_reason=began_as, flip=flip)
        self.events.extend(new_events)
        self.actions.extend(chain_to_actions(
            chain, self.team_names, self.attack_dir_home, self.cal,
            start_reason=began_as, flip=flip))
        # a chain that BEGAN at a set piece records its outcome: the awarded
        # team (possession at mouse_down) fed it; chain.team came away with it
        sp = set_piece_record(began_as, self._chain_start_team, chain.team,
                              self.team_names, chain.start_minute)
        if sp:
            self.actions.append(self._stamp(
                sp, self._pos_m((segments[0].points[0].x, segments[0].points[0].y))))
        if try_team:
            last = segments[-1]
            prev = segments[-2] if len(segments) >= 2 else None
            assist = actor(prev) if prev and prev.action == "PASS" else None
            self._log_try(try_team, last.end_t, player=actor(last), assist=assist)
        self.last_summary = summarise(new_events, [s.action for s in segments])
        self._changed()

    def reclassify_segment(self, i: int):
        """Click a drawn segment to cycle its action, then re-commit the chain.

        Rewind-and-redo rather than patching the emitted events: a changed
        action can flip possession, split the chain differently and change the
        origin, so recomputing is both shorter and the only correct option.
        """
        chain = self.last_chain
        if chain is None or self._precommit is None or not 0 <= i < len(chain.segments):
            return
        order = ("CARRY", "PASS", "KICK")
        seg = chain.segments[i]
        before = seg.action
        seg.action = order[(order.index(seg.action) + 1) % len(order)]
        self._log_correction("reclassify", chain, i, seg, before)
        # a manual KICK asserts a handover; toggling one on/off re-frames every
        # segment after it, so re-derive their classification in the new frame
        seg.flips_possession = seg.action == "KICK"
        base_dir = (self.attack_dir_home if chain.team == "home"
                    else -self.attack_dir_home)
        reclassify_downstream(chain.segments, base_dir, i)
        self._rewind_and_recommit(chain)

    # --- correction logging (adaptive feedback loop) -----------------------
    def _seg_evidence(self, i: int) -> dict:
        """The classification evidence dict for segment i, captured at
        segmentation time (features/scores/probs/confidence/attack_dir)."""
        evs = self.last_debug.get("segments") or []
        return evs[i] if i < len(evs) else {}

    def _log_correction(self, kind: str, chain, i: int, seg, before: str):
        """Fire on_correction for one segment tag override (reclassify or hint).

        No-op unless a sink is wired: tests and fixtures never set on_correction,
        so they write nothing to the feedback DB. Reclassifies feed weight
        calibration; hints are audit-only (see feedback.training_pairs).
        """
        if not self.on_correction:
            return
        ev = self._seg_evidence(i)
        self.on_correction({
            "kind": kind,
            "home": self.team_names["home"], "away": self.team_names["away"],
            "segment_id": f"{chain.chain_id}#{i}",
            "original": before, "corrected": seg.action,
            "attack_dir": ev.get("attack_dir"),
            "points": [[p.x, p.y, p.t] for p in seg.points],
            "features": ev.get("features"),
            "context": {"scores": ev.get("scores"), "probs": ev.get("probs"),
                        "confidence": ev.get("confidence"),
                        "geometric": ev.get("action_geo"),
                        "minute": chain.start_minute, "team": chain.team},
        })

    def _log_hints(self, chain, segments, pre):
        """Log any K/P/R hint that overrode a segment's geometric class.

        A hint that changed the action means the operator disagreed with the
        geometry; recorded (audit only) via the same payload as a reclassify.
        """
        for i, (was, seg) in enumerate(zip(pre, segments)):
            if was != seg.action:
                self._log_correction("hint", chain, i, seg, was)

    def choose_in_goal_outcome(self, outcome: str):
        """The in-goal chip: try / held up / drop-out for the last chain.

        Same rewind-and-redo as reclassify_segment, because switching away
        from a try has to un-log the try event and the points that came with
        it — replaying the commit is the only way that stays consistent.
        """
        chain = self.last_chain
        if chain is None or self._precommit is None or self.in_goal_choice is None:
            return
        self._in_goal_override = outcome
        self._rewind_and_recommit(chain)

    def _rewind_and_recommit(self, chain):
        (self._chain_events_start, n, na, self.possession, self.last_end_reason,
         self._pending_try, self.pending_start_reason,
         self.armed_next_action) = self._precommit
        del self.events[n:]
        del self.actions[na:]
        self._undo = self._precommit[1:]   # the re-committed chain stays undoable
        self._commit_chain(chain)

    def undo_last(self):
        """Rewind the last committed chain. Single level — no undo stack.

        ponytail: one level covers the "I just saw that go wrong" case, which
        is the only one that happens in practice; make _undo a deque if a real
        trace shows multi-step regret.
        """
        if self._undo is None:
            return
        (n, na, possession, reason, pending_try,
         start_reason, armed) = self._undo
        del self.events[n:]
        del self.actions[na:]
        self.possession = possession
        self.last_end_reason = reason
        self._pending_try = pending_try
        self.pending_start_reason = start_reason
        self.armed_next_action = armed
        self._undo = None
        self.last_chain = None
        self.last_origin = None
        self._last_penalty = None   # its event may have just been truncated
        self.last_summary = ""
        self._changed()

    def _scored_team_this_chain(self) -> Optional[str]:
        """Home/away key if a restart-triggering score was tapped this chain."""
        name_to_key = {v: k for k, v in self.team_names.items()}
        found = None
        for e in self.events[self._chain_events_start:]:
            if e.get("type") in RESTART_SCORE_TYPES:
                found = name_to_key.get(e.get("team"))
        return found

    # --- tapped origins: what geometry can't see ------------------------------
    def _tap_origin(self, k: str, t: float):
        """S (scrum) / F (penalty) — the two set pieces a traced line can't show.

        A knock-on looks exactly like a tackle; a penalty looks like nothing at
        all. Both award against whoever was carrying, which is right most of the
        time — the chip flips the team when it isn't.
        """
        reason = config.TAPPED_START_REASONS[k]
        held_by = self._chain_start_team if self.recorder.active else self.possession
        mark = self._last_point()
        if self.recorder.active:
            self.end_chain(t)              # the tap ends the play as well
        team = _other(held_by)
        self.possession = team
        self.pending_start_reason = reason
        self.last_origin = ChainOrigin(reason, team, mark)
        if reason == "penalty":
            ev = {"type": config.PENALTY_WON_TYPE,
                  "team": self.team_names[team],
                  # the side that gave it away, so a coach can map their own
                  # discipline (where they were penalised) not just penalties won
                  "conceded_by": self.team_names[held_by],
                  "minute": round(self.clock.minute(t), 1)}
            self._stamp(ev, self._pos_m(mark))   # where the penalty happened
            self.events.append(ev)
            self._last_penalty = ev       # a reason chip may annotate it
            self.penalty_reason = None     # unknown until picked
            self.armed_next_action = config.PENALTY_DEFAULT_OPTION
            self.penalty_option = config.PENALTY_DEFAULT_OPTION
        self._changed()

    def choose_penalty_reason(self, reason: str):
        """The penalty-reason chip: why it was given (a line can't show it).

        Writes onto the penalty_won event itself as an optional extra the
        momentum translator ignores; ignoring the chip leaves it absent.
        """
        self.penalty_reason = reason
        if self._last_penalty is not None:
            self._last_penalty["reason"] = reason
        self._changed()

    def _log_error(self, k: str, t: float):
        """Knock-on / forward pass / handling error — the negative ledger.

        A pure annotation into the action stream: the turnover it causes is
        already handled by chain-end inference. Attributed to whoever holds the
        ball, so tap it while tracing the action that went wrong.
        """
        self.actions.append(self._stamp({
            "type": "error",
            "kind": config.ERROR_KEYS[k],
            "team": self.team_names[self.possession],
            "minute": round(self.clock.minute(t), 1),
        }))
        self._changed()

    def choose_penalty_option(self, option: str):
        """Non-blocking: ignoring the chooser leaves the default guess standing.

        to-touch and at-goal both arm a kick, so the next stroke is forced to
        KICK (segment force in end_chain); at-goal also lets _commit_chain judge
        the kick against the posts instead of offering a grounding chooser.
        """
        self.penalty_option = option
        armed = {"kick_to_touch": "kick_to_touch", "at_goal": "kick_at_goal"}
        self.armed_next_action = armed.get(option)
        if option == "scrum":
            self.pending_start_reason = "scrum"
        self._changed()

    def flip_origin_team(self):
        """The chip's team badge. Two teams, so wrong is always one click away."""
        o = self.last_origin
        if o is None:
            return
        self.possession = _other(o.team)
        self.last_origin = ChainOrigin(o.reason, self.possession, o.mark,
                                       o.alt_mark)
        self._changed()

    def flip_origin_mark(self):
        """Swap a lineout between its two lawful marks — it bounced, or it didn't."""
        o = self.last_origin
        if o is None or o.alt_mark is None:
            return
        self.last_origin = ChainOrigin(o.reason, o.team, o.alt_mark, o.mark)
        self._changed()

    def _last_point(self):
        """Where the ball was last seen, for anchoring a chip."""
        pts = self.recorder.points or (
            self.last_chain.segments[-1].points if self.last_chain else None)
        return (pts[-1].x, pts[-1].y) if pts else None

    def _flipped(self) -> bool:
        """Is play currently in the ends-swapped (second-half) orientation?

        True once halftime_flip has reversed attack_dir_home from the frame the
        match began in. Everything exported with a position folds by this so the
        whole match reads in one orientation.
        """
        return self.attack_dir_home != self.canon_attack_dir_home

    def _pos_m(self, pt):
        """(x_m, y_m) field-metre for a pixel point, or None.

        Folded into the first-half frame when the ends are swapped, the same as
        traced actions (events.chain_to_actions), so a tapped event plots and
        heatmaps consistently across both halves.
        """
        if pt is None:
            return None
        x, y = canonical_xy(self.cal.field_x_m(pt[0]), self.cal.field_y_m(pt[1]),
                            self._flipped())
        return (round(x, 1), round(y, 1))

    def _here_m(self):
        """Where the ball was last seen, in field metres — the live pointer
        mid-trace, else the last committed point. Position for a tapped event."""
        return self._pos_m(self._last_point())

    def _stamp(self, ev, pos=None):
        """Attach x_m/y_m to an event dict when a position is known.

        Optional, like the existing label/player extras: an event tapped before
        anything was traced simply carries no position, and every reader
        tolerates its absence.
        """
        pos = self._here_m() if pos is None else pos
        if pos is not None:
            ev["x_m"], ev["y_m"] = pos
        return ev

    def _in_goal_attacker(self, segments) -> str:
        """Whose try it is: the side attacking the in-goal the trace ended in."""
        end = segments[-1].points[-1]
        return _other(in_goal_defender(self.cal, end.x, self.attack_dir_home))

    def _log_try(self, team_key: str, t: float, player: Optional[int] = None,
                 assist: Optional[int] = None):
        """Append a try and arm the conversion listener. Tapped or inferred.

        player/assist are the scorer's and last-passer's jersey numbers when a
        traced try carried player tags; both stay absent otherwise (a T-tapped
        try mid-chain has no committed segment to read). They ride as optional
        extras the momentum translator ignores, like the existing label.
        """
        minute = round(self.clock.minute(t), 1)
        name = self.team_names[team_key]
        ev = self._stamp({"type": "try", "team": name, "minute": minute,
                          "label": f"{name} try {int(minute)}'"})
        if player is not None:
            ev["player"] = player
        if assist is not None:
            ev["assist"] = assist
        self.events.append(ev)
        self._pending_try = (team_key, t + config.CONVERSION_LISTEN_S)

    def _log_penalty_kick(self, team_key: str, t: float):
        """A kick at goal that crossed between the posts. Scores 3 like the
        N-tapped penalty_kick, and restarts play like any goal."""
        minute = round(self.clock.minute(t), 1)
        name = self.team_names[team_key]
        self.events.append(self._stamp({"type": "penalty_kick", "team": name,
                            "minute": minute, "label": f"{name} penalty {int(minute)}'"}))

    # --- discrete events -----------------------------------------------------
    def _discrete_event(self, k: str, t: float):
        etype = config.DISCRETE_EVENT_KEYS[k]
        if etype == "try":
            self._log_try(self.possession, t)
            self._changed()
            return
        minute = round(self.clock.minute(t), 1)
        if etype == "turnover_won":
            team_key = _other(self.possession)
            self.possession = team_key
        elif etype in config.CARD_TYPES:
            # ponytail: assumes the defending side got carded; flip in review if not
            team_key = _other(self.possession)
        else:
            team_key = self.possession
        name = self.team_names[team_key]
        ev = self._stamp({"type": etype, "team": name, "minute": minute})
        if etype == "penalty_try":
            # already worth the conversion, so it must NOT arm the C/M listener
            ev["label"] = f"{name} penalty try {int(minute)}'"
        elif etype in config.CARD_TYPES:
            colour = "yellow" if etype == "sin_bin" else "red"
            ev["label"] = f"{name} {colour} {int(minute)}'"
        self.events.append(ev)
        self._changed()

    def _conversion(self, k: str, t: float):
        if not self._pending_try or t > self._pending_try[1]:
            return
        team_key, _ = self._pending_try
        self._pending_try = None
        self.events.append(self._stamp({
            "type": config.CONVERSION_KEYS[k],
            "team": self.team_names[team_key],
            "minute": round(self.clock.minute(t), 1),
        }))
        self._changed()

    # --- misc ------------------------------------------------------------------
    def halftime_flip(self):
        """Swap ends, and hand the second-half kickoff to the other side.

        canon_attack_dir_home is left untouched, so attack_dir_home now differs
        from it (_flipped() is True) and every position exported in the second
        half is folded back to the first-half frame.
        """
        self.attack_dir_home = -self.attack_dir_home
        self.possession = _other(self.kickoff_team)
        self.pending_start_reason = "kickoff"
        self.armed_next_action = None
        self.last_origin = ChainOrigin("kickoff", self.possession,
                                       halfway_mark(self.cal))
        self.in_goal_choice = None
        self._changed()

    def _changed(self):
        if self.on_change:
            self.on_change()

    # --- persistence shape -------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "teams": self.team_names,
            "team_colors": self.team_colors,
            "date": self.date,
            "competition": self.competition,
            "possession": self.possession,
            "kickoff_team": self.kickoff_team,
            "attack_dir_home": self.attack_dir_home,
            "canon_attack_dir_home": self.canon_attack_dir_home,
            "clock_seconds": self.clock.seconds(),
            "events": self.events,
            "actions": self.actions,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MatchState":
        m = cls(d["teams"]["home"], d["teams"]["away"],
                attack_dir_home=d["attack_dir_home"], possession=d["possession"],
                team_colors=d.get("team_colors"), date=d.get("date", ""),
                competition=d.get("competition", ""))
        m.clock = MatchClock(base_seconds=d["clock_seconds"])  # rehydrates paused
        m.events = list(d["events"])
        m.actions = list(d.get("actions", []))   # absent in pre-overhaul sessions
        m.kickoff_team = d.get("kickoff_team", d["possession"])
        # pre-overhaul sessions never flipped in the data; treat their current
        # orientation as canonical so nothing is spuriously folded on resume
        m.canon_attack_dir_home = d.get("canon_attack_dir_home", d["attack_dir_home"])
        return m
