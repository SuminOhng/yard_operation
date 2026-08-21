"""Fixed stacking results consumed by the static crane scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .geometry import Position, Slot


class MoveDirection(str, Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    container_id: str
    direction: MoveDirection
    origin: Position
    destination: Position
    final_slot: Slot | None
    release_time: float = 0.0
    agv_ready_time: float = 0.0

    @property
    def ready_time(self) -> float:
        return max(self.release_time, self.agv_ready_time)
