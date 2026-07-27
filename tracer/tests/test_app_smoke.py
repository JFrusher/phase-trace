"""Smoke test for the NiceGUI page wiring in app.py.

The rest of the suite is pure logic; nothing else imports app.py, so the
handler plumbing (partial-bound key handler, setup_form -> _build_match_ui,
partial-bound refresh) would break silently. Builds the real match UI against
NiceGUI's auto-index client, which needs no browser and no event loop.
"""

import inspect
from functools import partial

from nicegui import ui

from tracer import app
from tracer.match_state import MatchState


def _match():
    return MatchState("BATH", "BRIS", attack_dir_home=1, possession="home")


def test_handler_signatures_survive_partial_binding():
    """NiceGUI counts handler parameters to decide what to pass in."""
    ctx = {"match": None, "canvas": None}
    assert len(inspect.signature(partial(app._handle_key, ctx)).parameters) == 1
    # setup_form calls on_start(match) positionally
    begin = partial(app._build_match_ui, ctx=ctx, root=None, dev=False)
    assert list(inspect.signature(begin).parameters)[0] == "m"


def test_key_handler_ignores_events_before_kickoff():
    app._handle_key({"match": None, "canvas": None}, object())  # no AttributeError


def test_build_match_ui_renders_header_and_refreshes():
    m = _match()
    ctx = {"match": None, "canvas": None}
    app._build_match_ui(m, ctx, ui.column(), dev=False)

    assert ctx["match"] is m and ctx["canvas"] is not None
    assert m.on_commit is not None and m.on_change is not None


def test_refresh_writes_clock_score_and_possession():
    m = _match()
    ctx = {"match": None, "canvas": None}
    root = ui.column()
    app._build_match_ui(m, ctx, root, dev=False)

    # _build_match_ui already ran refresh() once; assert on what it wrote
    labels = [e.text for e in root.descendants() if isinstance(e, ui.label)]
    assert "00:00" in labels
    assert "BATH 0" in labels
    assert "0 BRIS" in labels
    assert "BATH →" in labels
    assert "0 events" in labels


class _StubWidget:
    """Enough of a ui.label / ui.button for _refresh to write into."""

    def __init__(self):
        self.text = None
        self.icon = None
        self.background = None

    def props(self, s):
        self.icon = s

    def style(self, s):
        self.background = s


class _StubCanvas:
    def __init__(self):
        self.pitches = []

    def set_pitch(self, svg):
        self.pitches.append(svg)


def _stub_widgets():
    return {k: _StubWidget() for k in
            ("clock", "clock_btn", "home_chip", "away_chip", "poss", "status")}


def test_refresh_retints_pitch_only_when_direction_changes():
    m, w, canvas = _match(), _stub_widgets(), _StubCanvas()
    shown = {"score": None, "dir": m.attack_dir_home, "poss": None}

    app._refresh(m, canvas, w, shown)
    assert canvas.pitches == []      # nothing flipped yet

    m.attack_dir_home = -m.attack_dir_home
    app._refresh(m, canvas, w, shown)
    assert len(canvas.pitches) == 1  # retinted once

    app._refresh(m, canvas, w, shown)
    assert len(canvas.pitches) == 1  # and not again


def test_refresh_restyles_possession_only_on_change():
    m, w, canvas = _match(), _stub_widgets(), _StubCanvas()
    shown = {"score": None, "dir": m.attack_dir_home, "poss": None}

    app._refresh(m, canvas, w, shown)
    assert w["poss"].text == "BATH →"
    assert w["poss"].background == f"background:{m.team_colors['home']}"

    w["poss"].background = None
    app._refresh(m, canvas, w, shown)
    assert w["poss"].background is None   # unchanged possession, no restyle

    m.possession = "away"
    app._refresh(m, canvas, w, shown)
    assert w["poss"].text == "BRIS ←"
    assert w["poss"].background == f"background:{m.team_colors['away']}"


def test_refresh_shows_clock_and_pause_icon_when_running():
    m, w, canvas = _match(), _stub_widgets(), _StubCanvas()
    shown = {"score": None, "dir": m.attack_dir_home, "poss": None}

    app._refresh(m, canvas, w, shown)
    assert w["clock"].text == "00:00"
    assert w["clock_btn"].icon == "icon=play_arrow"

    m.clock.toggle()
    app._refresh(m, canvas, w, shown)
    assert w["clock_btn"].icon == "icon=pause"
