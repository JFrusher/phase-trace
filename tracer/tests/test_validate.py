from tracer.export import build_payload, export_json
from tracer.validate import validate_events

GOOD = [
    {"type": "phase_sequence", "team": "ENG", "minute": 3.0,
     "metres_gained": 20.0, "end_metres_from_line": 40.0, "linebreaks": 0},
    {"type": "try", "team": "WAL", "minute": 10.0},
]


def test_good_events_pass():
    assert validate_events(GOOD, "ENG", "WAL") == []


def test_every_start_reason_is_priced_and_exportable():
    # the translator falls back to 1.0 for an unknown start_reason rather than
    # failing, so nothing downstream would ever complain about a reason the
    # weights table forgot — which makes this the only place it gets caught
    from tracer import config
    from translators.rugby import _WEIGHTS
    assert set(config.START_REASONS) <= set(_WEIGHTS["origin_factor"])
    events = [{**GOOD[0], "minute": float(i), "start_reason": reason}
              for i, reason in enumerate(config.START_REASONS)]
    assert validate_events(events, "ENG", "WAL") == []


def test_missing_field_caught_by_real_translator():
    errors = validate_events([{"type": "try", "minute": 1.0}], "ENG", "WAL")
    assert errors and "translate() rejected" in errors[0]


def test_empty_match_fails_engine_dry_run():
    errors = validate_events([], "ENG", "WAL")
    assert errors and "engine dry-run failed" in errors[0]


def test_export_blocks_on_errors(tmp_path):
    out = tmp_path / "out.json"
    errors = export_json(out, {"home": "ENG", "away": "WAL"}, [{"type": "try", "minute": 1}])
    assert errors and not out.exists()


def test_export_writes_sorted_payload(tmp_path):
    out = tmp_path / "out.json"
    shuffled = [GOOD[1], GOOD[0]]
    assert export_json(out, {"home": "ENG", "away": "WAL"}, shuffled) == []
    import json
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [e["minute"] for e in data["events"]] == [3.0, 10.0]
    assert data["teams"] == {"home": "ENG", "away": "WAL"}


def test_build_payload_default_title():
    p = build_payload({"home": "ENG", "away": "WAL"}, [])
    assert "ENG vs WAL" in p["title"]
