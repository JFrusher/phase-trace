"""Side pane: what the drawn lines mean, and what every key does.

Both halves are generated from the tables the app actually dispatches on —
`canvas.ACTION_COLORS` and `config.py`'s key vocabulary — not hand-listed, so a
key that lands in the recognizer cannot go undocumented on screen.
`tests/test_legend.py` fails when one does.

The line swatches are drawn with the same colour, width and dash the canvas
renders, on the same grass, because a legend whose white line sits on a white
card is teaching the wrong thing.

TODO: mouse/click gestures (hold = trace, release = fallback end, click a
segment = cycle its action, click a chip = correct it) are documented nowhere on
screen. Decide whether they belong in this pane as a third group.
"""

from typing import NamedTuple, Optional

from nicegui import ui

from . import config
from .canvas import ACTION_COLORS
from .pitch import GRASS


class Line(NamedTuple):
    color: str
    width: int
    dash: bool
    dot: bool
    text: str


class Row(NamedTuple):
    keys: tuple      # the config keys this row documents (drives the drift test)
    cap: str         # what the keycap reads
    icon: str
    text: str
    color: Optional[str] = None


ACTION_TEXT = {"CARRY": "Carry", "PASS": "Pass", "KICK": "Kick"}

ICONS = {
    "scrum": "groups", "penalty": "sports",            # as chips.py draws them
    "try": "sports_score", "penalty_try": "gavel",
    "penalty_kick": "gps_fixed", "drop_goal": "arrow_upward",
    "turnover_won": "cached", "sin_bin": "square", "red_card": "square",
    "conversion": "check_circle", "conversion_missed": "cancel",
    "knock_on": "front_hand", "forward_pass": "arrow_forward",
    "handling": "pan_tool",
}
CARD_COLORS = {"sin_bin": "#f5c518", "red_card": "#d32f2f"}


def line_rows() -> list:
    """The trace vocabulary, in the order the canvas colours it."""
    rows = [Line(color, 4, False, False, ACTION_TEXT[action])
            for action, color in ACTION_COLORS.items()]
    return rows + [
        Line(ACTION_COLORS["PASS"], 4, True, False, "Intercepted — possession flips"),
        Line("white", 2, False, False, "Live trace, unclassified"),
        Line("white", 0, False, True, "Segment boundary"),
    ]


def _label(event_type: str) -> str:
    text = event_type.replace("_", " ").replace("knock on", "knock-on")
    return text[0].upper() + text[1:]


def key_groups(team_names: dict) -> list:
    """[(title, [Row, ...])] — every tap the app recognises, grouped by job."""
    scores = {k: v for k, v in config.DISCRETE_EVENT_KEYS.items() if v in config.POINTS}
    others = {k: v for k, v in config.DISCRETE_EVENT_KEYS.items() if v not in scores.values()}
    return [
        ("End play", [
            Row(tuple(config.END_CHAIN_KEYS), "A / Space", "stop_circle",
                "End the play chain"),
            Row((), "Ctrl+Z", "undo", "Undo last chain"),
        ]),
        ("Set piece", [
            Row((k,), k.upper(), ICONS[reason], f"{_label(reason)} (ends play)")
            for k, reason in config.TAPPED_START_REASONS.items()
        ]),
        ("Fix a segment", [
            *[Row((k,), k.upper(), "horizontal_rule",
                  f"Force {ACTION_TEXT[action].lower()}", ACTION_COLORS[action])
              for k, action in config.TYPE_HINT_KEYS.items()],
            Row((config.LINEBREAK_KEY,), config.LINEBREAK_KEY.upper(), "bolt",
                "Linebreak on this carry"),
            Row(("shift",), "Shift", "call_split", "Hold: pass intercepted"),
            Row(tuple("0123456789"), "0-9", "tag", "Player number"),
        ]),
        ("Possession", [
            Row((k,), k.upper(), "circle", team_names[side], config.TEAM_COLORS[side])
            for k, side in config.TEAM_KEYS.items()
        ]),
        ("Score", [
            *[Row((k,), k.upper(), ICONS[t], _label(t)) for k, t in scores.items()],
            *[Row((k,), k.upper(), ICONS[t], _label(t))
              for k, t in config.CONVERSION_KEYS.items()],
        ]),
        ("Other events", [
            Row((k,), k.upper(), ICONS[t], _label(t), CARD_COLORS.get(t))
            for k, t in others.items()
        ]),
        ("Errors", [
            Row((k,), k.upper(), ICONS[t], _label(t))
            for k, t in config.ERROR_KEYS.items()
        ]),
    ]


def _swatch(line: Line) -> str:
    if line.dot:
        shape = ('<circle cx="17" cy="7" r="4" fill="white" stroke="#333" '
                 'stroke-width="1.5" />')
    else:
        dash = ' stroke-dasharray="6,5"' if line.dash else ""
        shape = (f'<line x1="2" y1="7" x2="32" y2="7" stroke="{line.color}" '
                 f'stroke-width="{line.width}" stroke-linecap="round"{dash} />')
    return f'<svg width="34" height="14">{shape}</svg>'


TEXT = "text-slate-700 leading-tight"


def _line_part():
    ui.label("LINES").classes("text-xs font-bold tracking-wide text-slate-500")
    for line in line_rows():
        with ui.row().classes("items-center gap-2 no-wrap"):
            ui.html(_swatch(line)).classes("rounded-sm px-0.5 leading-none") \
                .style(f"background:{GRASS}")
            ui.label(line.text).classes(f"text-xs {TEXT}")


def _key_row(row: Row):
    with ui.row().classes("items-center gap-2 no-wrap"):
        ui.label(row.cap).classes(
            "font-mono text-xs font-bold px-1.5 rounded border leading-snug "
            "border-slate-400 bg-slate-100 text-slate-700 text-center shrink-0"
        ).style("min-width:3.2rem")
        icon = ui.icon(row.icon).classes("text-base shrink-0")
        if row.color:
            icon.style(f"color:{row.color}")
        ui.label(row.text).classes(f"text-xs {TEXT}")


def _key_part(match):
    ui.label("KEYS").classes("text-xs font-bold tracking-wide text-slate-500")
    for title, rows in key_groups(match.team_names):
        ui.label(title).classes("text-xs font-semibold text-slate-400 mt-1")
        with ui.column().classes("gap-0.5 w-full"):
            for row in rows:
                _key_row(row)


def build_legend(match):
    """Collapsible pane for the right of the pitch. Returns its refreshable body."""

    @ui.refreshable
    def body():   # refreshable so team names/colours can't go stale
        # scrolls rather than pushing the export row off the page: on a short
        # window the keys outrun the pitch's height, and the pitch owns the fold
        with ui.column().classes("gap-2 w-64 shrink-0 overflow-y-auto") \
                .style("max-height:calc(100vh - 7rem)"):
            with ui.card().classes("w-full p-2 gap-0.5"):
                _line_part()
            with ui.card().classes("w-full p-2 gap-0.5"):
                _key_part(match)

    with ui.row().classes("items-start gap-1 no-wrap"):
        toggle = ui.button(icon="chevron_right").props("flat dense size=sm")
        holder = ui.element("div")   # collapsing this shrinks the pane to the
        with holder:                 # button, handing the width back to the pitch
            body()

        def flip():
            holder.visible = not holder.visible
            toggle.props(f"icon={'chevron_right' if holder.visible else 'menu_book'}")

        toggle.on_click(flip)
    return body
