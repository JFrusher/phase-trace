"""Raw per-action + summary export for squad analysis.

The tracer keeps two logs (see match_state): `events` — momentum-shaped
phase_sequences plus scoring/discipline discretes — and `actions` — the rich
per-action rows plus set-piece / penalty-reason / error records. This dumps
them for a squad to slice in a spreadsheet, plus one JSON that preserves
structure:

  actions.csv    one row per carry/pass/kick and per discrete event
  players.csv    per-jersey attacking + scoring totals
  team.csv       per-team scalar summary
  positions.csv  one row per located thing (x_m/y_m), for heatmaps
  match.json     meta + full action stream + both summaries

Everything tolerates missing fields: a column is blank when a match never
tagged that piece, which is the whole point — get out whatever was captured.
"""

import csv
import json
from collections import defaultdict
from pathlib import Path

from .events import compute_score

# points-scoring event types, for the per-team breakdown
_SCORE_COUNT = {"try": "tries", "conversion": "conversions",
                "penalty_kick": "penalty_kicks", "drop_goal": "drop_goals",
                "penalty_try": "penalty_tries"}


def action_stream(events: list[dict], actions: list[dict]) -> list[dict]:
    """The flat per-action stream: rich actions + every non-bundled event.

    phase_sequence is the momentum viz's bundled view of the same carries, so
    it is dropped here to avoid double-counting; its scoring/discipline
    siblings (try, penalty, card, turnover, ...) are kept.
    """
    discretes = [e for e in events if e.get("type") != "phase_sequence"]
    return sorted([*actions, *discretes], key=lambda e: e.get("minute", 0))


# --- summaries --------------------------------------------------------------
def _fold_player(stats: dict, e: dict):
    """Attribute one stream entry to its (team, jersey) totals."""
    team, num, typ = e.get("team"), e.get("player"), e.get("type")
    if typ == "carry" and num is not None:
        s = stats[(team, num)]
        s["carries"] += 1
        s["carry_metres"] += e.get("metres_gained", 0.0)
        s["linebreaks"] += 1 if e.get("linebreak") else 0
    elif typ == "kick" and num is not None:
        s = stats[(team, num)]
        s["kicks"] += 1
        s["kick_metres"] += e.get("metres_gained", 0.0)
    elif typ == "try":
        if num is not None:
            stats[(team, num)]["tries"] += 1
        if e.get("assist") is not None:
            stats[(team, e["assist"])]["assists"] += 1


def player_rows(stream: list[dict]) -> list[dict]:
    """Per (team, jersey) attacking + scoring totals, sorted for a stable file."""
    blank = lambda: {"carries": 0, "carry_metres": 0.0, "linebreaks": 0,
                     "kicks": 0, "kick_metres": 0.0, "tries": 0, "assists": 0}
    stats: dict = defaultdict(blank)
    for e in stream:
        _fold_player(stats, e)
    rows = []
    for (team, num), s in sorted(stats.items(), key=lambda kv: (str(kv[0][0]), kv[0][1])):
        s["carry_metres"] = round(s["carry_metres"], 1)
        s["kick_metres"] = round(s["kick_metres"], 1)
        rows.append({"team": team, "number": num, **s})
    return rows


def _blank_team() -> dict:
    return {"points": 0, "possessions": 0, "metres": 0.0,
            "carries": 0, "carry_metres": 0.0, "kicks": 0, "kick_metres": 0.0,
            "linebreaks": 0, "tries": 0, "conversions": 0, "conversions_missed": 0,
            "penalty_kicks": 0, "drop_goals": 0, "penalty_tries": 0,
            "turnovers_won": 0, "lineouts_won": 0, "lineouts_lost": 0,
            "scrums_won": 0, "scrums_lost": 0, "penalties_won": 0,
            "penalties_conceded": 0, "errors": 0, "sin_bins": 0, "red_cards": 0,
            "penalty_reasons": defaultdict(int), "error_kinds": defaultdict(int)}


def _fold_action(s: dict, a: dict):
    typ = a.get("type")
    if typ == "carry":
        s["carries"] += 1
        s["carry_metres"] += a.get("metres_gained", 0.0)
        s["linebreaks"] += 1 if a.get("linebreak") else 0
    elif typ == "kick":
        s["kicks"] += 1
        s["kick_metres"] += a.get("metres_gained", 0.0)
    elif typ == "set_piece":
        kind = "lineouts" if a["kind"] == "lineout" else "scrums"
        s[f"{kind}_{a['outcome']}"] += 1
    elif typ == "error":
        s["errors"] += 1
        s["error_kinds"][a.get("kind", "other")] += 1


def _fold_event(s: dict, e: dict, summ: dict, other: dict):
    typ = e.get("type")
    if typ in _SCORE_COUNT:
        s[_SCORE_COUNT[typ]] += 1
    elif typ == "phase_sequence":
        s["possessions"] += 1
    elif typ == "conversion_missed":
        s["conversions_missed"] += 1
    elif typ == "turnover_won":
        s["turnovers_won"] += 1
    elif typ == "sin_bin":
        s["sin_bins"] += 1
    elif typ == "red_card":
        s["red_cards"] += 1
    elif typ == "penalty_won":
        s["penalties_won"] += 1
        conceder = summ[other[e["team"]]]
        conceder["penalties_conceded"] += 1
        if e.get("reason"):
            conceder["penalty_reasons"][e["reason"]] += 1


def team_summary(events: list[dict], actions: list[dict], team_names: dict) -> dict:
    """Per-team totals, keyed by team name. Nested breakdowns for the JSON."""
    summ = {name: _blank_team() for name in team_names.values()}
    other = {team_names["home"]: team_names["away"],
             team_names["away"]: team_names["home"]}
    score = compute_score(events, team_names)
    for key, name in team_names.items():
        summ[name]["points"] = score[key]

    for a in actions:
        if a.get("team") in summ:
            _fold_action(summ[a["team"]], a)
    for e in events:
        if e.get("team") in summ:
            _fold_event(summ[e["team"]], e, summ, other)

    for s in summ.values():
        s["carry_metres"] = round(s["carry_metres"], 1)
        s["kick_metres"] = round(s["kick_metres"], 1)
        s["metres"] = round(s["carry_metres"] + s["kick_metres"], 1)
    return summ


# --- writers ----------------------------------------------------------------
_ACTION_COLS = ["minute", "type", "team", "player", "kind", "outcome", "reason",
                "metres_gained", "start_x_m", "start_y_m", "end_x_m", "end_y_m",
                "x_m", "y_m",   # single-point position for discrete events
                "end_metres_from_line", "attack_dir", "linebreak", "intercepted",
                "conceded_by", "assist", "label"]
# positions.csv: every located thing as one point row. A carry/pass/kick uses
# its start as the point (with its end kept), a discrete event its own x_m/y_m.
_POSITION_COLS = ["minute", "type", "team", "conceded_by", "x_m", "y_m",
                  "end_x_m", "end_y_m", "kind", "outcome", "reason", "label"]
_PLAYER_COLS = ["team", "number", "carries", "carry_metres", "linebreaks",
                "kicks", "kick_metres", "tries", "assists"]
_TEAM_COLS = ["team", "points", "possessions", "metres", "carries",
              "carry_metres", "kicks", "kick_metres", "linebreaks", "tries",
              "conversions", "conversions_missed", "penalty_kicks", "drop_goals",
              "penalty_tries", "turnovers_won", "lineouts_won", "lineouts_lost",
              "scrums_won", "scrums_lost", "penalties_won", "penalties_conceded",
              "errors", "sin_bins", "red_cards"]


def _write_csv(path: Path, cols: list[str], rows: list[dict]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _action_cols(stream: list[dict]) -> list[dict]:
    present = {k for e in stream for k in e}
    return [k for k in _ACTION_COLS if k in present] + sorted(present - set(_ACTION_COLS))


def position_rows(stream: list[dict]) -> list[dict]:
    """One row per located thing, projected to a single (x_m, y_m) point.

    A traced action's start is its point (its end is kept so a line can still
    be drawn); a discrete event uses its own stamped x_m/y_m. Anything with no
    position is skipped, so this is exactly what a pitch heatmap needs.
    """
    rows = []
    for e in stream:
        x = e.get("x_m", e.get("start_x_m"))
        y = e.get("y_m", e.get("start_y_m"))
        if x is None or y is None:
            continue
        rows.append({"minute": e.get("minute"), "type": e.get("type"),
                     "team": e.get("team"), "conceded_by": e.get("conceded_by"),
                     "x_m": x, "y_m": y,
                     "end_x_m": e.get("end_x_m"), "end_y_m": e.get("end_y_m"),
                     "kind": e.get("kind"), "outcome": e.get("outcome"),
                     "reason": e.get("reason"), "label": e.get("label")})
    return rows


def _plain(summ: dict) -> dict:
    """defaultdict breakdowns -> plain dict, for JSON."""
    out = {}
    for name, s in summ.items():
        out[name] = {k: (dict(v) if isinstance(v, defaultdict) else v)
                     for k, v in s.items()}
    return out


def export_raw(out_dir, meta: dict, team_names: dict,
               events: list[dict], actions: list[dict]) -> str:
    """Write actions.csv, players.csv, team.csv, match.json into out_dir."""
    stream = action_stream(events, actions)
    players = player_rows(stream)
    team = team_summary(events, actions, team_names)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    _write_csv(out / "actions.csv", _action_cols(stream), stream)
    _write_csv(out / "players.csv", _PLAYER_COLS, players)
    _write_csv(out / "team.csv", _TEAM_COLS,
               [{"team": n, **s} for n, s in team.items()])
    _write_csv(out / "positions.csv", _POSITION_COLS, position_rows(stream))
    payload = {
        "meta": {"teams": team_names, "date": meta.get("date", ""),
                 "competition": meta.get("competition", "")},
        "actions": stream,
        "summary": {"players": players, "team": _plain(team)},
    }
    (out / "match.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return str(out)
