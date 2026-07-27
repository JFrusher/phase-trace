"""Optional, non-blocking timeline review/edit — never forced (Decision 12).

Open during a stoppage or halftime; correct team, numbers, metres, or delete
a bad event. Edits mutate match.events in place; autosave picks them up.
"""

from nicegui import ui

from . import config


def _players_str(ev) -> str:
    return ",".join(f"{p['number']}:{p['role']}" for p in ev.get("players", []))


def _parse_players(text: str):
    out = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        num, _, role = part.partition(":")
        if num.strip().isdigit():
            out.append({"number": int(num), "role": role.strip() or "start"})
    return out


def _swap_team(match, ev, touched):
    names = list(match.team_names.values())
    ev["team"] = names[1] if ev["team"] == names[0] else names[0]
    touched()


def _set_type(ev, etype, touched):
    ev["type"] = etype
    ev.pop("label", None)   # the old label names the old score
    touched()


def _set_players(match, ev, text):
    players = _parse_players(text)
    if players:
        ev["players"] = players
    else:
        ev.pop("players", None)
    match._changed()


def _phase_fields(match, ev):
    """The editable numbers + players input a phase_sequence row carries."""
    ui.number("m gained", min=0, step=0.5).bind_value(
        ev, "metres_gained").classes("w-24")
    ui.number("m from line", min=0, max=100, step=0.5).bind_value(
        ev, "end_metres_from_line").classes("w-24")
    ui.number("breaks", min=0, step=1).bind_value(
        ev, "linebreaks").classes("w-20")
    ui.input("players", value=_players_str(ev),
             on_change=lambda e, ev=ev: _set_players(match, ev, e.value),
             placeholder="9:start,10:end").classes("w-40")


def _event_row(match, i, ev, touched):
    with ui.row().classes("items-center gap-2 w-full"):
        ui.label(f"{ev['minute']:g}'").classes("w-10 font-mono")
        ui.button(ev["team"],
                  on_click=lambda e=ev: _swap_team(match, e, touched)).props("flat dense")
        if ev["type"] in config.POINTS:
            # a mis-tapped T instead of N is the common correction,
            # and it is worth 5 points against the wrong column
            ui.select(sorted(config.POINTS), value=ev["type"],
                      on_change=lambda e, ev=ev: _set_type(ev, e.value, touched)
                      ).props("dense options-dense borderless").classes("w-32")
        else:
            ui.label(ev["type"]).classes("w-32")
        if ev["type"] == "phase_sequence":
            _phase_fields(match, ev)
        ui.space()
        ui.button(icon="delete",
                  on_click=lambda idx=i: (match.events.pop(idx), touched())
                  ).props("flat dense color=negative")


def open_review(match):
    with ui.dialog() as dialog, ui.card().classes("min-w-[760px] max-h-[85vh] overflow-auto"):
        ui.label("Timeline review").classes("text-lg font-bold")

        def touched():
            match._changed()
            rows.refresh()

        @ui.refreshable
        def rows():
            if not match.events:
                ui.label("No events yet.")
            for i, ev in enumerate(match.events):
                _event_row(match, i, ev, touched)

        rows()
        ui.button("Close", on_click=dialog.close).props("flat")
    dialog.open()
    return dialog
