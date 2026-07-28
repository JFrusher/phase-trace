"""Set-piece chips: the correction UI, drawn where the set piece happened.

Every inferred attribution renders as a chip, and the chip's team badge is a
switch — there are two teams, so a wrong guess is always one click from right.
The type is never editable where geometry settles it (a kick finishing at a
touchline is a lineout, a score is a restart): a lineout would never become a
scrum, so offering that would be noise. The exceptions are the two things a
line genuinely cannot show — what a team chose to do with a penalty, and
whether the ball was grounded in the in-goal — and those get a chooser row.

Chips are DOM elements positioned over the image rather than shapes drawn into
it: ui.interactive_image reports mouse coordinates, not element targets, so a
clickable shape inside its content would be unreachable. The layer itself is
pointer-events-none so drags still reach the canvas underneath.

Anchors are percentages, not pixels, so a chip stays on its mark when the
image scales down on a narrow window.
"""

from nicegui import ui

from . import config
from .pitch import IMAGE_W, IMAGE_H

ICONS = {
    "lineout": "swap_vert", "scrum": "groups", "penalty": "sports",
    "restart": "replay", "turnover_open": "cached",
    "interception": "back_hand", "kick_return": "sports_rugby",
    "kickoff": "flag", "drop_out_22": "vertical_align_top",
}
OPTION_LABELS = {
    "kick_to_touch": "to touch", "at_goal": "at goal",
    "tap_and_go": "tap", "scrum": "scrum",
    "try": "try", "held_up": "held up", "drop_out": "drop-out",
}
REASON_LABELS = {
    "offside": "offside", "high": "high", "ruck": "ruck",
    "scrum": "scrum·pen", "foul": "foul", "other": "other",
}


def build_chips(match, layer):
    """Draw match.last_origin inside `layer`. Returns the refreshable."""

    @ui.refreshable
    def chip():
        _target(match)          # "press here" dot on the mark the next press snaps to
        o = match.last_origin
        if o is None or o.mark is None:
            return
        x, y = o.mark
        # Floats clear of its mark, like a map pin: anchored ON the point it
        # would sit over the traced line and swallow the clicks that
        # re-classify the segment underneath. A lineout mark is by definition
        # at a touchline, so near the top edge it hangs below instead of
        # sailing off the pitch.
        shift = "-125%" if y > IMAGE_H * 0.15 else "25%"
        if o.reason in config.CENTRE_SPOT_REASONS:
            # the centre spot is where the next trace must START, so hanging a
            # clickable chip over it would eat the press that begins the kick
            y += config.CHIP_CLEARANCE_M * config.PX_PER_M
            shift = "25%"
        with ui.element("div").classes("absolute pointer-events-auto").style(
                f"left:{x / IMAGE_W * 100:.2f}%;top:{y / IMAGE_H * 100:.2f}%;"
                f"transform:translate(-50%,{shift})"):
            with ui.column().classes("items-center gap-1"):
                _badge(match, o)
                if o.reason == "penalty":
                    _chooser(config.PENALTY_OPTIONS, match.penalty_option,
                             match.choose_penalty_option)
                    _chooser(config.PENALTY_REASONS, match.penalty_reason,
                             match.choose_penalty_reason, REASON_LABELS)
                elif match.in_goal_choice:
                    _chooser(config.IN_GOAL_OUTCOMES, match.in_goal_choice,
                             match.choose_in_goal_outcome)

    with layer:
        chip()
    return chip


def _target(match):
    """A small dot on the mark the next press will snap onto (MatchState.pending_mark).

    Gives the operator something to aim at, so the press lands inside the snap
    tolerance and the whole trace barely shifts. Sits on the exact mark while the
    origin badge floats clear of it; it inherits the layer's pointer-events-none,
    so the press it marks passes straight through to the canvas underneath.
    """
    mark = match.pending_mark
    if mark is None:
        return
    x, y = mark
    ui.element("div").classes(
        "absolute rounded-full border-2 border-slate-600 bg-white/70"
    ).style(f"left:{x / IMAGE_W * 100:.2f}%;top:{y / IMAGE_H * 100:.2f}%;"
            "width:10px;height:10px;transform:translate(-50%,-50%)")


def _badge(match, o):
    with ui.row().classes(
            "items-center gap-1 rounded-md pl-2 pr-1 py-0.5 "
            "text-xs font-bold text-white whitespace-nowrap"
    ).style(f"background:{match.team_colors[o.team]}"):
        # An open turnover has nothing to correct but the team, and the colour
        # already says which — so the bubble is just the name that took over.
        if o.reason != "turnover_open":
            ui.icon(ICONS.get(o.reason, "place")).classes("text-sm")
            ui.label(o.reason.replace("_", " ").upper())
        ui.button(match.team_names[o.team], on_click=match.flip_origin_team) \
            .props("flat dense no-caps size=sm color=white") \
            .tooltip("wrong team? click to swap")
        if o.alt_mark:
            ui.button(icon="swap_horiz", on_click=match.flip_origin_mark) \
                .props("flat dense size=sm color=white") \
                .tooltip("it bounced before going out — move the mark")


def _chooser(options, selected, on_pick, labels=OPTION_LABELS):
    """Pre-selected on the guess; ignoring it accepts that. Nothing blocks.

    Used for the things a traced line cannot show: what a team did with a
    penalty, why the penalty was given, and whether the ball was grounded.
    """
    with ui.row().classes("gap-0 rounded-sm border border-slate-300 bg-white"):
        for opt in options:
            chosen = selected == opt
            ui.button(labels[opt], on_click=lambda o=opt: on_pick(o)) \
                .props(f"dense no-caps size=sm {'unelevated' if chosen else 'flat'} "
                       f"color={'primary' if chosen else 'grey-8'}")
