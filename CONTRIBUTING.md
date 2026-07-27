# Contributing

This is a one-person project, so open an issue before starting anything
substantial. I'd rather talk about it first than have you write something I
was already half way through, or something I'd end up saying no to.

Small stuff (typos, a broken link, an obviously wrong docstring) needs no
ceremony. Just send the PR.

## Setup

Python 3.11+.

```bash
pip install -e ".[dev]"
python -m pytest -q          # 256 tests, ~3 seconds
```

CI runs the same `pytest -q` on every push and pull request, on 3.11. If it's
green locally it should be green there.

## Changing the recognizer

The part that turns a traced line into carries, passes and kicks lives in
`tracer/segmentation.py` and `tracer/features.py`, and every threshold and
weight it uses is a plain constant in `tracer/config.py`. Read
[tracer/TUNING.md](tracer/TUNING.md) before touching any of it. Two things
matter more than they look:

**Nothing in the recognizer may read time.** The line is classified from its
geometry only, so that a trace drawn slowly off paused video lands the same
as one drawn live. Reintroducing a millisecond or m/s constant breaks that
silently. `tracer/tests/test_pace_invariance.py` is the fence.

**Tuning is done by evidence, not by feel.** If a trace is misread, run the
app in dev mode (`python -m tracer.app 8080 dev`), use *Save last trace*, then
promote the saved trace into `tracer/tests/traces/` with an `"expect"` block.
It joins the corpus, `test_corpus.py` picks it up, and `python -m tracer.sweep`
and `python -m tracer.fit` will tell you what the constants should be. A third
tool, `python -m tracer.calibrate`, is `fit` plus the segment corrections
operators log live in the app (SQLite, `tracer/feedback/`; see TUNING.md). All
three print and none writes `config.py`, so the final edit is yours.

A recognizer PR that changes a constant without a corpus case demonstrating
why won't get merged, not because of process, but because there's no way to
tell whether it fixed anything.

## Adding a sport or a data source

Implement `BaseSport` in `translators/` (or `BaseDataSource` in `sources/`)
and register it in the package's `__init__.py`. `translators/rugby.py` is the
worked example. Neither the engine nor the chart renderer should need
changing; if you find yourself editing `core/` to add a sport, something has
gone wrong in the translator and it's worth an issue.

## Style

Match the file you're in. Tests are plain pytest functions with no fixtures
beyond what's already there. Commit messages use `type: summary`
(`feat:`, `fix:`, `docs:`, `chore:`).
