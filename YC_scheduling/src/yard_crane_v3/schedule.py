from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .model import Position, Slot
from .policy import CooperationPolicy


class OperationType(str, Enum):
    MOVE_EMPTY = "MOVE_EMPTY"
    PICKUP = "PICKUP"
    MOVE_LOADED = "MOVE_LOADED"
    HANDOVER_DROP = "HANDOVER_DROP"
    HANDOVER_PICKUP = "HANDOVER_PICKUP"
    FINAL_DROP = "FINAL_DROP"
    WAIT = "WAIT"


class OperationPurpose(str, Enum):
    PRIMARY_JOB = "PRIMARY_JOB"
    HANDOVER = "HANDOVER"
    RESHUFFLE = "RESHUFFLE"


@dataclass(frozen=True, slots=True)
class ScheduledOperation:
    crane_id: str
    operation_type: OperationType
    start_time: float
    end_time: float
    start_position: Position
    end_position: Position
    job_id: str | None = None
    transfer_slot_id: str | None = None
    container_id: str | None = None
    target_slot: Slot | None = None
    purpose: OperationPurpose = OperationPurpose.PRIMARY_JOB


@dataclass(frozen=True, slots=True)
class CandidateSchedule:
    instance_id: str
    policy: CooperationPolicy
    operations: tuple[ScheduledOperation, ...]
