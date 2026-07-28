"""Raw CSV/JSON export: merged stream, summaries, file output.

The assertions double as proof the squad's target stats are pullable:
metres-per-carry, carries-per-possession, kick-at-goal completion, and the
2D coordinates a pitch heatmap needs.
"""

import csv
import json
from pathlib import Path

from tracer.raw_export import action_stream, player_rows, team_summary, export_raw

NAMES = {"home": "ENG", "away": "WAL"}

EVENTS = [
    {"type": "phase_sequence", "team": "ENG", "minute": 1.0, "metres_gained": 10.0,
     "end_metres_from_line": 80.0, "linebreaks": 0},
    {"type": "phase_sequence", "team": "ENG", "minute": 5.0, "metres_gained": 30.0,
     "end_metres_from_line": 50.0, "linebreaks": 0},
    {"type": "phase_sequence", "team": "WAL", "minute": 10.0, "metres_gained": 5.0,
     "end_metres_from_line": 60.0, "linebreaks": 0},
    {"type": "try", "team": "ENG", "minute": 6.0, "player": 7, "assist": 10,
     "label": "ENG try 6'"},
    {"type": "conversion", "team": "ENG", "minute": 6.5},
    {"type": "conversion_missed", "team": "WAL", "minute": 20.0},
    {"type": "penalty_kick", "team": "ENG", "minute": 15.0},
    {"type": "penalty_won", "team": "ENG", "minute": 15.0, "reason": "offside"},
    {"type": "turnover_won", "team": "WAL", "minute": 22.0},
    {"type": "sin_bin", "team": "WAL", "minute": 30.0},
]

ACTIONS = [
    {"type": "carry", "team": "ENG", "minute": 1.0, "player": 7,
     "metres_gained": 8.0, "end_metres_from_line": 80.0, "start_x_m": 10.0,
     "start_y_m": 35.0, "end_x_m": 18.0, "end_y_m": 35.0, "attack_dir": 1,
     "linebreak": True},
    {"type": "pass", "team": "ENG", "minute": 1.2, "metres_gained": 0.0,
     "end_metres_from_line": 80.0, "start_x_m": 18.0, "start_y_m": 35.0,
     "end_x_m": 17.0, "end_y_m": 30.0, "attack_dir": 1},
    {"type": "kick", "team": "ENG", "minute": 5.0, "player": 10,
     "metres_gained": 30.0, "end_metres_from_line": 50.0, "start_x_m": 20.0,
     "start_y_m": 35.0, "end_x_m": 50.0, "end_y_m": 20.0, "attack_dir": 1},
    {"type": "carry", "team": "WAL", "minute": 10.0, "player": 4,
     "metres_gained": 5.0, "end_metres_from_line": 60.0, "start_x_m": 45.0,
     "start_y_m": 40.0, "end_x_m": 40.0, "end_y_m": 40.0, "attack_dir": -1},
    {"type": "set_piece", "kind": "lineout", "team": "ENG", "outcome": "won",
     "minute": 1.0},
    {"type": "set_piece", "kind": "scrum", "team": "WAL", "outcome": "lost",
     "minute": 25.0},
    {"type": "error", "kind": "knock_on", "team": "WAL", "minute": 26.0},
]


def test_stream_drops_phase_sequence_keeps_discretes_sorted():
    s = action_stream(EVENTS, ACTIONS)
    assert all(e["type"] != "phase_sequence" for e in s)
    assert any(e["type"] == "try" for e in s)
    assert [e["minute"] for e in s] == sorted(e["minute"] for e in s)


def test_player_rows_attacking_and_scoring():
    rows = {(r["team"], r["number"]): r
            for r in player_rows(action_stream(EVENTS, ACTIONS))}
    eng7 = rows[("ENG", 7)]
    assert eng7["carries"] == 1 and eng7["carry_metres"] == 8.0
    assert eng7["linebreaks"] == 1 and eng7["tries"] == 1
    eng10 = rows[("ENG", 10)]
    assert eng10["kicks"] == 1 and eng10["kick_metres"] == 30.0
    assert eng10["assists"] == 1
    assert rows[("WAL", 4)]["carries"] == 1


def test_team_summary_enables_the_asked_stats():
    t = team_summary(EVENTS, ACTIONS, NAMES)
    eng, wal = t["ENG"], t["WAL"]
    # avg carries per possession = carries / possessions
    assert eng["possessions"] == 2 and eng["carries"] == 1
    # metres per carry = carry_metres / carries; kicks kept separate
    assert eng["carry_metres"] == 8.0 and eng["kick_metres"] == 30.0
    assert eng["metres"] == 38.0
    # kick-at-goal completion = conversions / (conversions + missed)
    assert eng["conversions"] == 1 and wal["conversions_missed"] == 1
    assert eng["points"] == 10
    assert eng["lineouts_won"] == 1 and wal["scrums_lost"] == 1
    assert wal["penalties_conceded"] == 1 and wal["penalty_reasons"]["offside"] == 1
    assert wal["errors"] == 1 and wal["error_kinds"]["knock_on"] == 1
    assert wal["turnovers_won"] == 1 and wal["sin_bins"] == 1


def test_export_writes_all_files_with_coords_and_blanks(tmp_path):
    out = Path(export_raw(tmp_path / "m",
                          {"date": "2026-02-14", "competition": "BUCS"},
                          NAMES, EVENTS, ACTIONS))
    for name in ("actions.csv", "players.csv", "team.csv", "match.json"):
        assert (out / name).exists()

    with open(out / "actions.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert "end_x_m" in rows[0] and "end_y_m" in rows[0]   # heatmap coords present
    passes = [r for r in rows if r["type"] == "pass"]
    assert passes and passes[0]["player"] == ""            # missing field -> blank cell

    meta = json.loads((out / "match.json").read_text(encoding="utf-8"))
    assert meta["meta"]["date"] == "2026-02-14"
    assert meta["summary"]["team"]["WAL"]["penalty_reasons"] == {"offside": 1}
