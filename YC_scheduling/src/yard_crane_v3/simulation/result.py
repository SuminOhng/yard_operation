"""Structured output of one physical schedule replay."""

from __future__ import annotations

from dataclasses import dataclass

from ..model import (
    ContainerStatus,
    Position,
    Slot,
    StackKey,
    YardState,
)


@dataclass(frozen=True, slots=True)
class StackDelta:
    key: StackKey
    before: tuple[str, ...]
    after: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TransferDelta:
    slot_id: str
    before: tuple[str, ...]
    after: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StateDelta:
    crane_id: str
    crane_position_before: Position
    crane_position_after: Position
    crane_load_before: str | None
    crane_load_after: str | None
    container_id: str | None = None
    container_status_before: ContainerStatus | None = None
    container_status_after: ContainerStatus | None = None
    container_slot_before: Slot | None = None
    container_slot_after: Slot | None = None
    stack_changes: tuple[StackDelta, ...] = ()
    transfer_changes: tuple[TransferDelta, ...] = ()


@dataclass(frozen=True, slots=True)
class SimulationViolation:
    code: str
    message: str
    time: float
    operation_index: int | None = None
    crane_id: str | None = None
    job_id: str | None = None


@dataclass(frozen=True, slots=True)
class OperationTrace:
    operation_index: int
    start_time: float
    end_time: float
    accepted: bool
    violation_codes: tuple[str, ...] = ()
    state_delta: StateDelta | None = None


@dataclass(frozen=True, slots=True)
class SimulationResult:
    valid: bool
    initial_state: YardState
    final_state: YardState
    violations: tuple[SimulationViolation, ...]
    operation_traces: tuple[OperationTrace, ...]
    completed_job_ids: frozenset[str]
    makespan: float | None
    handover_count: int
