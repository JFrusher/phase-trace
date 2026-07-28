"""Local correction feedback log (SQLite) + the read side calibrate.py tunes on.

Every operator correction of the tracer's output is one row here. Classification
reclassifies carry the traced points + attack direction, so calibrate.py can
re-extract features under the current config and fold them into fit.py's weight
proposal. Everything else (K/P/R hints, review-dialog edits) is logged for the
audit record only.

Pure stdlib. MatchState/review fire log_correction through the on_correction
callback, so nothing here imports the UI, and a caller that never wires the
callback (every test, every fixture) writes nothing.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from . import features
from .autosave import _slug
from .continuity import PathPoint

DEFAULT_DB = Path(__file__).parent / "feedback" / "corrections.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS corrections (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  ts            TEXT NOT NULL,   -- ISO wall-clock of the correction
  match         TEXT,            -- home_v_away slug; scopes segment_id
  segment_id    TEXT,            -- "chain-N#i" (NULL for review-dialog edits)
  kind          TEXT NOT NULL,   -- reclassify | hint | team | type | delete
  original      TEXT,            -- prior value (action / team / type)
  corrected     TEXT,            -- operator value
  attack_dir    INTEGER,         -- +1/-1 frame the segment was classified in
  points_json   TEXT,            -- [[x,y,t],...]; features re-extracted at calibrate
  features_json TEXT,            -- squashed-feature snapshot (audit only)
  context_json  TEXT             -- scores/probs/confidence/minute/team (momentum context)
);
CREATE INDEX IF NOT EXISTS ix_kind ON corrections(kind);
"""

_COLS = ("ts", "match", "segment_id", "kind", "original", "corrected",
         "attack_dir", "points_json", "features_json", "context_json")


def _connect(db):
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)
    return conn


def _match_slug(payload):
    if payload.get("match"):
        return payload["match"]
    if payload.get("home") is not None:
        return f"{_slug(payload['home'])}_v_{_slug(payload['away'])}"
    return None


def log_correction(payload: dict, db=DEFAULT_DB) -> None:
    """Insert one correction row. Wired to MatchState/review on_correction."""
    blob = lambda k: json.dumps(payload[k]) if payload.get(k) is not None else None
    row = (datetime.now().isoformat(timespec="seconds"), _match_slug(payload),
           payload.get("segment_id"), payload["kind"], payload.get("original"),
           payload.get("corrected"), payload.get("attack_dir"),
           blob("points"), blob("features"), blob("context"))
    with _connect(db) as conn:
        conn.execute(f"INSERT INTO corrections ({','.join(_COLS)}) "
                     f"VALUES ({','.join('?' * len(_COLS))})", row)


def training_pairs(db=DEFAULT_DB):
    """(feature dicts, labels) from the latest reclassify per (match, segment_id).

    Features are re-extracted from the stored points under the CURRENT config, so
    a pair stays honest if feature scales are later tuned. Hints and review edits
    are excluded — only reclassifies move classifier weights (a K/P/R hint can
    relabel a carry-shaped gesture, poisoning the geometric label; see fit.py).
    """
    with _connect(db) as conn:
        rows = conn.execute(
            "SELECT points_json, attack_dir, corrected FROM corrections "
            "WHERE kind='reclassify' AND id IN ("
            "  SELECT MAX(id) FROM corrections WHERE kind='reclassify' "
            "  GROUP BY match, segment_id)").fetchall()
    xs, labels = [], []
    for points_json, attack_dir, corrected in rows:
        if points_json is None or attack_dir is None:
            continue
        pts = [PathPoint(x, y, t) for x, y, t in json.loads(points_json)]
        feats, _ = features.extract(pts, attack_dir)
        xs.append(feats)
        labels.append(corrected)
    return xs, labels


def summary(db=DEFAULT_DB) -> str:
    """Counts per kind + the reclassify original->operator confusion, for the report."""
    with _connect(db) as conn:
        kinds = conn.execute("SELECT kind, COUNT(*) FROM corrections "
                             "GROUP BY kind ORDER BY kind").fetchall()
        confusion = conn.execute(
            "SELECT original, corrected, COUNT(*) FROM corrections "
            "WHERE kind='reclassify' GROUP BY original, corrected "
            "ORDER BY original, corrected").fetchall()
    total = sum(c for _, c in kinds)
    lines = [f"corrections logged: {total} "
             + "{" + ", ".join(f"{k}: {c}" for k, c in kinds) + "}"]
    if confusion:
        lines.append("reclassify (model -> operator):")
        lines += [f"  {orig:>5} -> {corr:<5} {c}" for orig, corr, c in confusion]
    return "\n".join(lines)
