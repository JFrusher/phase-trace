"""Rugby union translator -- the sport-agnostic design's proof point.

Football has discrete "shot" events to key off of; rugby largely doesn't --
threat builds through phase play and territory. Two event shapes are
therefore handled differently:

  - Discrete scores (try, penalty_kick, drop_goal, conversion) map to a
    static weight table, same pattern as football.
  - "phase_sequence" events (a team's continuous possession) carry no
    pre-set weight; _territory_weight() derives one from metres gained,
    how close the sequence ended to the try line, and any linebreaks.

Cards (sin_bin, red_card) are deliberately marker-only, not fed into the decay
sum -- going to 14 men isn't itself threat creation, and the pressure it
invites is already captured by the phase_sequence/score events that follow.
Crediting the card directly would double-count that signal. A red is a bigger
swing than a yellow, but it is a bigger swing *because* of the phases that
follow it, which is exactly the thing already counted. This is a judgement
call, not a derived fact -- revisit once there's real match data to validate
against, the way the football model was validated against Flashscore.
"""

import json
from pathlib import Path

from core.schema import StandardEvent
from .base import BaseSport, ChartProfile

_WEIGHTS = json.loads((Path(__file__).parent / "rugby_weights.json").read_text())

_SCORE_TYPES = ("try", "penalty_try", "penalty_kick", "drop_goal")
_CARD_TYPES = ("sin_bin", "red_card")


class RugbySport(BaseSport):
    name = "rugby_union"
    # Rugby phases run longer and territory is "banked" more durably than a
    # football possession, so momentum plausibly persists longer -- starting
    # point only, tune against reference footage like football's 3.0 was.
    decay_half_life = 4.5

    def chart_profile(self):
        return ChartProfile(
            max_t=82,  # 80 + a little added time buffer
            interval_markers=[40],
            tick_positions=[0, 20, 40, 60, 80],
            tick_labels=["0'", "20'", "HT", "60'", "FT"],
        )

    def translate(self, raw_events):
        out = []
        for ev in raw_events:
            etype = ev["type"]
            if etype == "phase_sequence":
                out.append(StandardEvent(
                    team=ev["team"],
                    t=ev["minute"],
                    weight=self._territory_weight(ev),
                    category="pressure",
                ))
            elif etype in _CARD_TYPES:
                out.append(StandardEvent(
                    team=ev["team"],
                    t=ev["minute"],
                    weight=0.0,
                    category="card",
                    label=ev.get("label"),
                    marker="note",
                ))
            else:
                weight = ev.get("weight", _WEIGHTS.get(etype, _WEIGHTS["_default"]))
                is_score = etype in _SCORE_TYPES
                out.append(StandardEvent(
                    team=ev["team"],
                    t=ev["minute"],
                    weight=weight,
                    category="score" if is_score else etype,
                    label=ev.get("label"),
                    marker="score" if is_score else None,
                ))
        return out

    @staticmethod
    def _territory_weight(ev):
        """Continuous threat energy from one possession/phase sequence.

        Rugby has no discrete "shot" event -- territory gained is the
        signal. Combines metres gained, how close the sequence ended to the
        try line, and whether it produced a linebreak.

        How the possession BEGAN scales the result: an interception or a
        penalty carries threat a scrum on halfway doesn't. Set pieces get no
        weight of their own -- a lineout is not itself threat creation, it is
        context for the possession it starts, and crediting it separately
        would double-count that possession exactly the way crediting a card
        directly would. The factors below are judgement calls, unvalidated
        against real data, in the same way this module's decay_half_life and
        card handling are -- tune them once real traced matches exist.

        ev may also carry "start_metres_from_line" (where the possession
        began). It is deliberately not weighted yet: end position already
        drives territory_factor, and adding a second positional term without
        reference data to fit it against would be inventing signal.
        """
        # both positional fields arrive signed (geometry.metres_gained /
        # metres_from_line): ground lost is negative, and a position past the
        # try line is negative metres from it. Threat energy has no meaning
        # below zero -- a possession that went backwards created no threat, it
        # did not create anti-threat -- so the clamp lives here, at the one
        # place that wants it, rather than in the exported data.
        metres = max(0.0, ev.get("metres_gained", 0))
        end_m_from_line = min(100.0, max(0.0, ev.get("end_metres_from_line", 50)))
        linebreaks = ev.get("linebreaks", 0)
        origin = _WEIGHTS["origin_factor"].get(ev.get("start_reason"), 1.0)
        territory_factor = 1 - end_m_from_line / 100
        base = 0.15 + 0.35 * min(metres / 40, 1.0)
        return round((base + 0.3 * territory_factor)
                     * (1 + 0.25 * linebreaks) * origin, 2)
