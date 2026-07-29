"""Atomic disk persistence + rehydrate-on-launch.

Write-temp-then-os.replace keeps the session file always whole: a crash
mid-write leaves the previous good file untouched. A corrupt/missing file
loads as None — the app then offers a fresh start, which is the intended
crash-recovery behavior, not a swallowed error.
"""

import json
import os
import re
from pathlib import Path

SESSION_DIR = Path(__file__).parent / "sessions"
SESSION_FILE = SESSION_DIR / "session.json"

# TODO(radl-storage): a session file is NOT a RADL frame and should not become
# one. It holds live tracer state -- possession, armed penalty option, clock,
# attack direction, both event logs -- so that a crashed match can be resumed
# mid-trace. RADL is the published record of a finished match; the two have
# different lifetimes and different readers. When a database arrives it stores
# exported action frames (see docs/radl-backend-roadmap.md), and this stays a
# file: durable local scratch that survives the process, which is exactly what
# crash recovery needs and what a remote DB is worst at.


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "team"


def session_path(home: str, away: str, directory: Path = SESSION_DIR) -> Path:
    """One file per fixture, so a second match can't clobber the first."""
    return directory / f"{_slug(home)}_v_{_slug(away)}.json"


def latest_session(directory: Path = SESSION_DIR):
    """Most recently written session, for the resume offer. None if there is none."""
    if not directory.is_dir():
        return None
    files = sorted(directory.glob("*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return load_session(files[0]) if files else None


def save_session(state: dict, path: Path = SESSION_FILE):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def load_session(path: Path = SESSION_FILE):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def clear_session(path: Path = SESSION_FILE):
    path.unlink(missing_ok=True)
