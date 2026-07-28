"""Pre-match setup screen (teams, attack direction, kickoff possession)."""

from nicegui import ui

from . import config
from .match_state import MatchState


def setup_form(container, on_start, saved: dict = None):
    """Render the setup card into container; call on_start(MatchState) when ready."""
    with container:
        with ui.card() as card:
            ui.label("Match setup").classes("text-xl font-bold")
            if saved and saved.get("events"):
                ui.label(f"Unfinished session found "
                         f"({saved['teams']['home']} vs {saved['teams']['away']}, "
                         f"{len(saved['events'])} events).").classes("text-amber-700")
                ui.button("Resume session",
                          on_click=lambda: on_start(MatchState.from_dict(saved)))
                ui.separator()
            with ui.row().classes("items-end gap-2"):
                home = ui.input("Home team", value="HOME")
                home_color = ui.color_input(
                    label="Home colour", value=config.TEAM_COLORS["home"]).classes("w-32")
            with ui.row().classes("items-end gap-2"):
                away = ui.input("Away team", value="AWAY")
                away_color = ui.color_input(
                    label="Away colour", value=config.TEAM_COLORS["away"]).classes("w-32")
            with ui.row().classes("items-end gap-2"):
                # self-describing metadata for a season of exported files
                date = ui.input("Date", placeholder="2026-02-14").classes("w-40")
                competition = ui.input("Competition",
                                       placeholder="BUCS Prem").classes("w-48")
            direction = ui.select({1: "Home attacks →", -1: "Home attacks ←"},
                                  value=1, label="First-half direction")
            # possession always means who HAS the ball, so this is the kicker
            possession = ui.select({"home": "Home", "away": "Away"},
                                   value="home", label="Kicks off (has the ball)")
            # ponytail: squad-number rosters skipped; add if digit-tap typos get annoying
            ui.button("Start match", on_click=lambda: on_start(MatchState(
                home.value.strip() or "HOME", away.value.strip() or "AWAY",
                attack_dir_home=direction.value, possession=possession.value,
                team_colors={"home": home_color.value, "away": away_color.value},
                date=date.value.strip(), competition=competition.value.strip())))
    return card
