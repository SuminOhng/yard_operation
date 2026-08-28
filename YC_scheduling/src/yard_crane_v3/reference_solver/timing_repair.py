"""Precedence-preserving timing constraints and schedule repair."""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, replace
from enum import Enum

from ..model import StaticSchedulingInstance
from ..policy import constraints_for
from ..schedule import CandidateSchedule, ScheduledOperation
from ..simulation import CraneConflict, first_crane_conflict
from ..validator import ValidationResult, validate_schedule


class TimingConstraintReason(str, Enum):
    CRANE_CONFLICT_REPAIR = "CRANE_CONFLICT_REPAIR"
    TRANSFER_CAPACITY_ORDER = "TRANSFER_CAPACITY_ORDER"
    TRANSFER_ACCESS_ORDER = "TRANSFER_ACCESS_ORDER"


@dataclass(frozen=True, slots=True)
class TimingConstraint:
    operation_index: int
    earliest_start: float
    delayed_crane_id: str
    conflict_time: float
    opposing_operation_index: int | None
    reason: TimingConstraintReason = TimingConstraintReason.CRANE_CONFLICT_REPAIR

    def __post_init__(self) -> None:
        if self.operation_index < 0:
            raise ValueError("operation_index must be nonnegative")
        if not math.isfinite(self.earliest_start) or self.earliest_start < 0:
            raise ValueError("earliest_start must be finite and nonnegative")
        if not math.isfinite(self.conflict_time) or self.conflict_time < 0:
            raise ValueError("conflict_time must be finite and nonnegative")
        if not self.delayed_crane_id:
            raise ValueError("delayed_crane_id must not be empty")


@dataclass(frozen=True, slots=True)
class TimingRepairResult:
    schedule: CandidateSchedule
    validation: ValidationResult
    constraints: tuple[TimingConstraint, ...]
    first_conflict: CraneConflict | None
    shifted_operation_indices: tuple[int, ...]


def repair_schedule_timing(
    instance: StaticSchedulingInstance,
    schedule: CandidateSchedule,
    timing_constraints: tuple[TimingConstraint, ...],
) -> TimingRepairResult:
    """Recompute earliest starts under crane/job precedence and constraints."""

    operations = schedule.operations
    normalized = normalize_timing_constraints(timing_constraints)
    for constraint in normalized:
        if constraint.operation_index >= len(operations):
            raise ValueError(
                f"constraint operation_index {constraint.operation_index} "
                "is outside the schedule"
            )
        operation = operations[constraint.operation_index]
        if operation.crane_id != constraint.delayed_crane_id:
            raise ValueError(
                f"constraint crane {constraint.delayed_crane_id!r} does not "
                f"match operation {constraint.operation_index}"
            )
        if (
            constraint.opposing_operation_index is not None
            and not 0
            <= constraint.opposing_operation_index
            < len(operations)
        ):
            raise ValueError("opposing_operation_index is outside the schedule")

    predecessors, successors = _precedence_graph(operations)
    for constraint in normalized:
        opposing = constraint.opposing_operation_index
        delayed = constraint.operation_index
        if opposing is not None and delayed not in successors[opposing]:
            successors[opposing].add(delayed)
            predecessors[delayed].add(opposing)
    indegree = [len(items) for items in predecessors]
    ready: list[tuple[float, float, int]] = []
    for index, degree in enumerate(indegree):
        if degree == 0:
            operation = operations[index]
            heapq.heappush(
                ready,
                (operation.start_time, operation.end_time, index),
            )
    constraint_starts: dict[int, float] = {}
    for constraint in normalized:
        constraint_starts[constraint.operation_index] = max(
            constraint_starts.get(constraint.operation_index, 0.0),
            constraint.earliest_start,
        )
    repaired: list[ScheduledOperation | None] = [None] * len(operations)
    end_times = [0.0] * len(operations)
    shifted: list[int] = []
    processed = 0

    while ready:
        _, _, index = heapq.heappop(ready)
        operation = operations[index]
        earliest = instance.initial_state.current_time
        if operation.job_id is not None:
            earliest = max(
                earliest,
                instance.jobs_by_id[operation.job_id].ready_time,
            )
        earliest = max(earliest, constraint_starts.get(index, earliest))
        if predecessors[index]:
            earliest = max(
                earliest,
                *(end_times[parent] for parent in predecessors[index]),
            )
        duration = operation.end_time - operation.start_time
        updated = replace(
            operation,
            start_time=earliest,
            end_time=earliest + duration,
        )
        repaired[index] = updated
        end_times[index] = updated.end_time
        if abs(updated.start_time - operation.start_time) > 1e-9:
            shifted.append(index)
        processed += 1
        for child in successors[index]:
            indegree[child] -= 1
            if indegree[child] == 0:
                child_operation = operations[child]
                heapq.heappush(
                    ready,
                    (
                        child_operation.start_time,
                        child_operation.end_time,
                        child,
                    ),
                )

    if processed != len(operations):
        raise ValueError("crane/job precedence graph contains a cycle")
    candidate = CandidateSchedule(
        schedule.instance_id,
        schedule.policy,
        tuple(operation for operation in repaired if operation is not None),
    )
    validation = validate_schedule(
        instance,
        constraints_for(instance, schedule.policy),
        candidate,
    )
    return TimingRepairResult(
        schedule=candidate,
        validation=validation,
        constraints=normalized,
        first_conflict=first_crane_conflict(instance, candidate),
        shifted_operation_indices=tuple(shifted),
    )


def normalize_timing_constraints(
    constraints: tuple[TimingConstraint, ...],
) -> tuple[TimingConstraint, ...]:
    """Keep the strongest lower-start constraint for each operation."""

    strongest: dict[tuple[int, int | None], TimingConstraint] = {}
    for constraint in constraints:
        key = (
            constraint.operation_index,
            constraint.opposing_operation_index,
        )
        current = strongest.get(key)
        if current is None or (
            constraint.earliest_start,
            constraint.conflict_time,
            constraint.delayed_crane_id,
        ) > (
            current.earliest_start,
            current.conflict_time,
            current.delayed_crane_id,
        ):
            strongest[key] = constraint
    return tuple(strongest[key] for key in sorted(
        strongest,
        key=lambda item: (item[0], -1 if item[1] is None else item[1]),
    ))


def timing_constraint_signature(
    constraints: tuple[TimingConstraint, ...],
) -> tuple[tuple[int, int | None, float], ...]:
    return tuple(
        (
            constraint.operation_index,
            constraint.opposing_operation_index,
            constraint.earliest_start,
        )
        for constraint in normalize_timing_constraints(constraints)
    )


def _precedence_graph(
    operations: tuple[ScheduledOperation, ...],
) -> tuple[list[set[int]], list[set[int]]]:
    predecessors: list[set[int]] = [set() for _ in operations]
    successors: list[set[int]] = [set() for _ in operations]
    order_key = lambda index: (
        operations[index].start_time,
        operations[index].end_time,
        index,
    )
    by_crane: dict[str, list[int]] = {}
    by_job: dict[str, list[int]] = {}
    for index, operation in enumerate(operations):
        by_crane.setdefault(operation.crane_id, []).append(index)
        if operation.job_id is not None:
            by_job.setdefault(operation.job_id, []).append(index)
    for indices in (*by_crane.values(), *by_job.values()):
        indices.sort(key=order_key)
        for previous, current in zip(indices, indices[1:]):
            if current not in successors[previous]:
                successors[previous].add(current)
                predecessors[current].add(previous)
    return predecessors, successors
