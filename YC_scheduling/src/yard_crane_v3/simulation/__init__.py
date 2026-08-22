"""Event-based physical state transition engine."""

from .engine import replay_schedule
from .conflicts import CraneConflict, detect_crane_conflicts, first_crane_conflict
from .result import (
    OperationTrace,
    SimulationResult,
    SimulationViolation,
    StackDelta,
    StateDelta,
    TransferDelta,
)

__all__ = [
    "OperationTrace",
    "CraneConflict",
    "SimulationResult",
    "SimulationViolation",
    "StackDelta",
    "StateDelta",
    "TransferDelta",
    "detect_crane_conflicts",
    "first_crane_conflict",
    "replay_schedule",
]
