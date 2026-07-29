"""The legend pane's pure core — the drift guard.

The point of these: a key added to config.py that nobody documents is a key
nobody on the touchline knows exists.
"""

from tracer import config, legend
from tracer.canvas import ACTION_COLORS

NAMES = {"home": "Bath", "away": "Exeter"}


def _documented_keys():
    return {k for _, rows in legend.key_groups(NAMES) for r in rows for k in r.keys}


def test_every_dispatched_key_is_documented():
    dispatched = {
        *config.END_CHAIN_KEYS, *config.TAPPED_START_REASONS, *config.TEAM_KEYS,
        *config.DISCRETE_EVENT_KEYS, *config.CONVERSION_KEYS, *config.ERROR_KEYS,
        *config.TYPE_HINT_KEYS, config.LINEBREAK_KEY, "shift", *"0123456789",
    }
    assert dispatched <= _documented_keys(), dispatched - _documented_keys()


def test_no_documented_key_is_a_ghost():
    """A row for a key the app no longer dispatches teaches a lie."""
    dispatched = {
        *config.END_CHAIN_KEYS, *config.TAPPED_START_REASONS, *config.TEAM_KEYS,
        *config.DISCRETE_EVENT_KEYS, *config.CONVERSION_KEYS, *config.ERROR_KEYS,
        *config.TYPE_HINT_KEYS, config.LINEBREAK_KEY, "shift", *"0123456789",
    }
    assert _documented_keys() <= dispatched, _documented_keys() - dispatched


def test_team_rows_carry_the_real_names():
    texts = [r.text for _, rows in legend.key_groups(NAMES) for r in rows]
    assert "Bath" in texts and "Exeter" in texts


def test_line_rows_match_what_the_canvas_draws():
    colors = {ln.color for ln in legend.line_rows()}
    assert set(ACTION_COLORS.values()) <= colors
    texts = " ".join(ln.text for ln in legend.line_rows()).lower()
    assert "intercepted" in texts and "boundary" in texts
    assert any(ln.dash for ln in legend.line_rows())   # the interception cue
    assert any(ln.dot for ln in legend.line_rows())    # the boundary cue


def test_every_row_has_an_icon():
    for _, rows in legend.key_groups(NAMES):
        for r in rows:
            assert r.icon and r.cap, r
