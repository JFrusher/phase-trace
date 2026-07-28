"""Grid-sweep segmentation thresholds over the fixture corpus.

Runs every scenario in fixtures.SCENARIOS (plus promoted real traces in
tests/traces/) under each threshold combination and prints a pass-count
table. Informs manual tuning of config.py; NEVER writes config — read the
table, decide, edit by hand.

Run: .venv/Scripts/python -m tracer.sweep      Edit GRID to change knobs.
"""

import itertools

from . import config, fixtures

GRID = {
    "BOUNDARY_ACCEPT": [0.65, 0.75, 0.85],
    "MIN_SEGMENT_M": [3.0, 4.0, 5.0],
    "B_KICK": [-7.0, -6.4, -5.5],
}


def score():
    """(passed, total, failed names) over the whole corpus at current config."""
    cases = fixtures.iter_cases()
    failed = [name for name, run_case in cases if run_case()]
    return len(cases) - len(failed), len(cases), failed


def _run_grid(keys, baseline):
    """Score every GRID combination, restoring config afterwards (never writes)."""
    rows = []
    try:
        for combo in itertools.product(*(GRID[k] for k in keys)):
            for k, v in zip(keys, combo):
                setattr(config, k, v)
            passed, total, failed = score()
            rows.append((passed, total, combo, failed))
    finally:
        for k, v in zip(keys, baseline):
            setattr(config, k, v)
    return rows


def _format_row(keys, baseline, passed, total, combo, failed) -> str:
    label = " ".join(f"{k}={v}" for k, v in zip(keys, combo))
    mark = "  (baseline)" if combo == baseline else ""
    tail = ""
    if failed:
        shown = ", ".join(failed[:4]) + ("..." if len(failed) > 4 else "")
        tail = f"  fail: {shown}"
    return f"{label:<38} {passed}/{total}{mark}{tail}"


def main():
    keys = list(GRID)
    baseline = tuple(getattr(config, k) for k in keys)
    rows = _run_grid(keys, baseline)
    rows.sort(key=lambda r: -r[0])
    for passed, total, combo, failed in rows:
        print(_format_row(keys, baseline, passed, total, combo, failed))


if __name__ == "__main__":
    main()
