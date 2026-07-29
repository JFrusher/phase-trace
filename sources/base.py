"""Plug-in interface a data-provider adapter must implement.

A DataSource only knows how to parse one provider's raw match data (Opta,
StatsBomb, a custom JSON bank, ...) into a common shape. It has no knowledge
of sport-specific event vocabulary or weighting -- that is a Sport
translator's job, kept as an independent axis so Sport x DataSource compose
freely instead of multiplying into one class per pair.
"""

from abc import ABC, abstractmethod


class BaseDataSource(ABC):
    @abstractmethod
    def parse(self, path: str) -> dict:
        """Load and normalize one match's raw data.

        Returns a dict shaped:
            {
              "events": [ {...provider-specific raw event...}, ... ],
              "teams": {"home": str, "away": str},
              "colors": {"home": str, "away": str},   # optional
              "title": str,                            # optional
              "footer": str,                            # optional
            }

        Field names inside "events" are provider-specific -- only the Sport
        translator chosen for this match needs to understand them.
        """

# TODO(radl-vendor): this interface feeds the MOMENTUM path (Sport translator ->
# StandardEvent -> MomentumEngine), and a vendor feed should not be squeezed
# through it to reach RADL. A converter from a real provider (Opta, Stats
# Perform, a tracking engine) belongs in the radl package as a sibling of
# radl/phase_trace.py, converting the raw feed straight to an action frame --
# routing it through phase-trace's match.json would make every other producer
# inherit phase-trace's quirks. See docs/radl-backend-roadmap.md.
