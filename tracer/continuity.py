"""PathPoint/Segment/PlayChain dataclasses + chain recording lifecycle. Pure."""

import itertools
from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass(frozen=True)
class PathPoint:
    x: float
    y: float
    t: float  # time.monotonic() at capture, seconds


@dataclass(frozen=True)
class PlayerTag:
    number: int
    role: Literal["start", "end"]
    at_ts: float


@dataclass
class Segment:
    action: Literal["CARRY", "PASS", "KICK"]
    points: list  # list[PathPoint], the slice of the path this segment covers
    team: Literal["home", "away"] = "home"
    intercepted: bool = False
    linebreak: bool = False
    players: list = field(default_factory=list)  # list[PlayerTag]
    scores: dict = field(default_factory=dict)   # {class: linear score}, CARRY = 0
    confidence: float | None = None              # top prob minus second prob
    # Does this segment hand possession to the other team (and flip attack
    # direction)? A KICK normally does; None means "unset -> a KICK flips"
    # (backward-compatible default). Set False for a KICK too weak to trust
    # with the frame flip (see segmentation._should_flip).
    flips_possession: bool | None = None

    @property
    def start_t(self) -> float:
        return self.points[0].t

    @property
    def end_t(self) -> float:
        return self.points[-1].t


_chain_counter = itertools.count(1)


@dataclass
class PlayChain:
    chain_id: str
    team: Literal["home", "away"]
    start_minute: float
    segments: list = field(default_factory=list)  # list[Segment]
    ended_by: Literal["tackle_ruck", "whistle"] = "tackle_ruck"

    @property
    def t0(self) -> Optional[float]:
        return self.segments[0].points[0].t if self.segments else None


class ChainRecorder:
    """Accumulates PathPoints between mousedown and the chain-end signal."""

    def __init__(self):
        self.points: list[PathPoint] = []
        self.active = False

    def start(self, x: float, y: float, t: float):
        self.points = [PathPoint(x, y, t)]
        self.active = True

    def extend(self, x: float, y: float, t: float):
        if self.active:
            self.points.append(PathPoint(x, y, t))

    def finish(self) -> list[PathPoint]:
        pts, self.points, self.active = self.points, [], False
        return pts


def new_chain_id() -> str:
    return f"chain-{next(_chain_counter)}"
