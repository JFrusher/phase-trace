"""Catch drift between config.py's event-type strings and the translator's
vocabulary.

The parallel checks against RADL's published vocabularies live in
test_radl_contract.py, which needs the optional `radl` package; this file must
keep working without it.
"""

import json
from pathlib import Path

from tracer import config

WEIGHTS = json.loads(
    (Path(__file__).parents[2] / "translators" / "rugby_weights.json").read_text())

# types rugby.py's translate() special-cases rather than looking up in the table
SPECIAL = {*config.CARD_TYPES, "phase_sequence"}


def test_discrete_event_types_known_to_translator():
    for etype in config.DISCRETE_EVENT_KEYS.values():
        assert etype in WEIGHTS or etype in SPECIAL, etype


def test_conversion_types_known_to_translator():
    for etype in config.CONVERSION_KEYS.values():
        assert etype in WEIGHTS, etype


def test_no_key_collisions_across_vocab():
    groups = [set(config.TYPE_HINT_KEYS), {config.LINEBREAK_KEY},
              set(config.TEAM_KEYS), config.END_CHAIN_KEYS,
              set(config.DISCRETE_EVENT_KEYS), set(config.CONVERSION_KEYS),
              set(config.TAPPED_START_REASONS), set("0123456789")]
    seen = set()
    for g in groups:
        assert not (g & seen), g & seen
        seen |= g


# --- the dead-data guard ---------------------------------------------------
# rugby_weights.json has a "_default" that silently swallows any type the
# translator does not recognise. Without these, a new event type would export,
# chart, and mean nothing. Failing here is the point.
def test_every_start_reason_has_an_origin_factor():
    factors = WEIGHTS["origin_factor"]
    for reason in config.START_REASONS:
        assert reason in factors, reason


def test_no_origin_factor_is_orphaned():
    for reason in WEIGHTS["origin_factor"]:
        assert reason in config.START_REASONS, reason


def test_penalty_won_is_declared_not_defaulted():
    assert config.PENALTY_WON_TYPE in WEIGHTS


def test_tapped_start_reasons_are_part_of_the_vocabulary():
    for reason in config.TAPPED_START_REASONS.values():
        assert reason in config.START_REASONS, reason

