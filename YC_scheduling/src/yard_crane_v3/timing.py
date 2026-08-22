from __future__ import annotations

from dataclasses import dataclass

from .model import MotionParameters, Position, Slot


@dataclass(frozen=True, slots=True)
class TimeModel:
    parameters: MotionParameters

    def travel_seconds(self, origin: Position, destination: Position) -> float:
        gantry = abs(destination.bay - origin.bay) * self.parameters.gantry_seconds_per_bay
        trolley = abs(destination.row - origin.row) * self.parameters.trolley_seconds_per_row
        return max(gantry, trolley)

    def pickup_seconds(self, slot: Slot | None = None) -> float:
        return self.parameters.pickup_seconds + self._hoist_seconds(slot)

    def drop_seconds(self, slot: Slot | None = None) -> float:
        return self.parameters.drop_seconds + self._hoist_seconds(slot)

    def _hoist_seconds(self, slot: Slot | None) -> float:
        if slot is None:
            return 0.0
        return slot.tier * self.parameters.hoist_seconds_per_tier
