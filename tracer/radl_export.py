"""RADL as an export target: match.json -> the published action frame.

phase-trace stores what it can see -- pixels, chains, segments, taps -- and
RADL publishes what an analyst reads: one flat row per action, closed
vocabularies, no geometry. Those are different jobs, so RADL is the boundary
this module writes across, not the shape MatchState holds in memory.

The conversion itself lives in the RADL package (`radl.phase_trace`), which is
the single source of truth for the schema. Duplicating it here to avoid a
dependency would be exactly the schema drift RADL exists to prevent, so this
module is a ten-line adapter and nothing more:

    match.json  --radl.read_match-->  action frame  -->  radl.csv

`radl` is an optional dependency (`pip install -e .[radl]`). Without it the raw
export still writes everything it always did; with it, every export is also
validated against the published vocabularies, and an action outside one raises
rather than reaching a corpus where it would read as part of the standard.
"""

from pathlib import Path

RADL_CSV = "radl.csv"


def available() -> bool:
    """Is the radl package importable? Everything here no-ops without it."""
    try:
        import radl  # noqa: F401
    except ImportError:
        return False
    return True


def write_radl(out_dir, match_id: str | None = None,
               halftime_minute: float | None = None) -> Path | None:
    """Convert the match.json in out_dir to radl.csv beside it.

    Returns the path written, or None when radl is not installed. Raises
    whatever the converter raises: a vocabulary violation is a real defect in
    what was traced, and the operator has to see it while the match is still
    open, not discover it in a published corpus later.

    `halftime_minute` is a fallback only. phase-trace stamps `period` on every
    row now, so the converter reads it from the data and the argument is dead
    weight for exports produced by this version -- it stays for the corpus of
    older exports that predate the field.
    """
    if not available():
        return None
    from radl.phase_trace import read_match

    out = Path(out_dir)
    frame = read_match(out / "match.json", match_id=match_id or out.name,
                       halftime_minute=halftime_minute)
    path = out / RADL_CSV
    frame.to_csv(path, index=False)
    return path


# TODO(radl-storage): the file layer stops here on purpose -- one CSV per
# export folder, read back with `radl.read_match`. The next storage step, when
# there is more than one traced match to hold:
#   * columnar file: `frame.to_parquet()` instead of to_csv preserves the
#     nullable dtypes that CSV flattens to object. Needs pyarrow; add it to the
#     [radl] extra rather than the base install.
#   * a database: RADL's frame is already one flat table, so a schema is
#     `CREATE TABLE actions (<config.COLUMNS with config.DTYPES>)` plus an index
#     on (match_id, possession_id). Write with `frame.to_sql`, read with
#     `pd.read_sql` -- do NOT hand-roll an ORM row class per action; the whole
#     point of a flat action language is that the table IS the model.
#     See docs/radl-backend-roadmap.md.
