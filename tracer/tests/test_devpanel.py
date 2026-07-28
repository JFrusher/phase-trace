"""format_report is the dev panel's pure core — test it off-UI."""

from tracer import fixtures
from tracer.devpanel import format_report


def _run(name):
    m = fixtures.open_play_match()
    fixtures.inject(m, fixtures.SCENARIOS[name])
    return m


def test_format_report_committed_chain():
    m = _run("carry_pass_carry")
    r = format_report(m.last_debug, m.last_chain)
    assert "committed" in r and "segments:" in r and "boundaries:" in r
    assert "rule=" in r and "straight" in r


def test_format_report_rejected_chain():
    m = _run("accidental_twitch")
    r = format_report(m.last_debug, m.last_chain)
    assert "REJECTED" in r and "net movement" in r


def test_format_report_shows_hint_relabel():
    m = _run("hint_k")
    r = format_report(m.last_debug, m.last_chain)
    assert "CARRY->KICK (hint)" in r


def test_format_report_shows_score_table():
    m = _run("carry_pass_carry")
    r = format_report(m.last_debug, m.last_chain)
    for feat in ("backward", "lateral", "straight", "dist"):
        assert feat in r
    assert "probs" in r and "conf" in r


def test_format_report_shows_boundary_baselines():
    m = _run("carry_straight")
    r = format_report(m.last_debug, m.last_chain)
    assert "baseline:" in r and "accept>=" in r
