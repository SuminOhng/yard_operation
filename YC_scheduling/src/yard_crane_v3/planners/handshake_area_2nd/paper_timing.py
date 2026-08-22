"""Deterministic movement-table timing used by the 2017 benchmark."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ...model import StaticSchedulingInstance
from ...schedule import CandidateSchedule
from ...validator import ValidationResult
from ...reference_solver.timing_repair import (
    TimingConstraint,
    TimingConstraintReason,
    repair_schedule_timing,
    timing_constraint_signature,
)
from ..pipeline import (
    _interleaved_transfer_access_constraints,
    _transfer_access_constraints,
    _transfer_capacity_constraints,
)


@dataclass(frozen=True, slots=True)
class PaperTimingResult:
    schedule: CandidateSchedule
    validation: ValidationResult
    blocking_seconds: float
    conflict_repairs: int
    movement_table: tuple["MovementTableEntry", ...]
    wait_records: tuple["WaitRecord", ...]
    request_legs: tuple["RequestLeg", ...]


class MovementPhase(str, Enum):
    LOCAL = "LOCAL"
    DONOR = "DONOR"
    RECEIVER = "RECEIVER"


class SchedulingProfile(str, Enum):
    PAPER_2017 = "PAPER_2017"
    CURRENT_YARD = "CURRENT_YARD"
    DYNAMIC_LEG_DISPATCH = "DYNAMIC_LEG_DISPATCH"


@dataclass(frozen=True, slots=True)
class BypassRecord:
    crane_id: str
    blocked_request_block_id: str
    executed_request_block_id: str
    wait_reason: str
    original_blocked_index: int
    original_executed_index: int


@dataclass(frozen=True, slots=True)
class RequestLeg:
    movement_table_rank: int
    request_block_id: str
    job_id: str
    crane_id: str
    phase: MovementPhase
    origin_bay: int
    destination_bay: int


class WaitReason(str, Enum):
    HANDOVER_PRECEDENCE = "HANDOVER_PRECEDENCE"
    CRANE_INTERFERENCE = "CRANE_INTERFERENCE"


@dataclass(frozen=True, slots=True)
class MovementTableEntry:
    operation_index: int
    request_block_id: str
    movement_table_rank: int
    phase: MovementPhase


@dataclass(frozen=True, slots=True)
class WaitRecord:
    operation_index: int
    crane_id: str
    request_block_id: str
    reason: WaitReason
    start_time: float
    end_time: float
    opposing_operation_index: int | None

    @property
    def seconds(self) -> float:
        return self.end_time - self.start_time


def repair_with_current_job_priority(
    instance: StaticSchedulingInstance,
    seed_schedule: CandidateSchedule,
    movement_table: tuple[MovementTableEntry, ...],
    request_legs: tuple[RequestLeg, ...] = (),
    *,
    max_repairs: int = 2000,
    interleaved_transfer_access: bool = False,
) -> PaperTimingResult:
    """Delay the request lower in the full movement table at every conflict."""

    if max_repairs < 1:
        raise ValueError("max_repairs must be positive")

    access_builder = (
        _interleaved_transfer_access_constraints
        if interleaved_transfer_access
        else _transfer_access_constraints
    )
    base_constraints = _transfer_capacity_constraints(
        instance,
        seed_schedule,
        TimingConstraint,
        TimingConstraintReason,
    ) + access_builder(
        instance,
        seed_schedule,
        TimingConstraint,
        TimingConstraintReason,
    )
    constraints = base_constraints
    seen = {timing_constraint_signature(constraints)}
    _validate_movement_table(seed_schedule, movement_table)
    priority_keys = tuple(_movement_priority_key(entry) for entry in movement_table)
    leg_end_indices = _leg_end_indices(seed_schedule, movement_table)
    repair = repair_schedule_timing(instance, seed_schedule, constraints)
    repairs = 0

    while not repair.validation.valid and repairs < max_repairs:
        conflict = repair.first_conflict
        if (
            conflict is None
            or conflict.seaside_operation_index is None
            or conflict.landside_operation_index is None
        ):
            break
        sea_index = conflict.seaside_operation_index
        land_index = conflict.landside_operation_index
        if priority_keys[sea_index] <= priority_keys[land_index]:
            opposing_index, delayed_index = sea_index, land_index
        else:
            opposing_index, delayed_index = land_index, sea_index

        priority_rank = movement_table[opposing_index].movement_table_rank
        opposing_index = leg_end_indices[priority_rank]
        opposing = repair.schedule.operations[opposing_index]
        delayed = repair.schedule.operations[delayed_index]
        constraint = TimingConstraint(
            operation_index=delayed_index,
            earliest_start=opposing.end_time,
            delayed_crane_id=delayed.crane_id,
            conflict_time=conflict.onset_time,
            opposing_operation_index=opposing_index,
            reason=TimingConstraintReason.CRANE_CONFLICT_REPAIR,
        )
        constraints += (constraint,)
        signature = timing_constraint_signature(constraints)
        if signature in seen:
            raise ValueError("current-job priority timing repair made no progress")
        seen.add(signature)
        try:
            repair = repair_schedule_timing(instance, seed_schedule, constraints)
        except ValueError as exc:
            raise ValueError(
                "current-job priority creates an infeasible precedence cycle"
            ) from exc
        repairs += 1

    if not repair.validation.valid:
        details = "; ".join(
            f"{issue.code}: {issue.message}" for issue in repair.validation.issues
        )
        raise ValueError(
            "current-job priority did not produce a valid schedule"
            + (f": {details}" if details else "")
        )

    wait_records = record_waits(
        instance,
        repair.schedule,
        movement_table,
        repair.constraints,
    )
    return PaperTimingResult(
        schedule=repair.schedule,
        validation=repair.validation,
        blocking_seconds=calculate_blocking_seconds(wait_records),
        conflict_repairs=repairs,
        movement_table=movement_table,
        wait_records=wait_records,
        request_legs=request_legs,
    )


def record_waits(
    instance: StaticSchedulingInstance,
    schedule: CandidateSchedule,
    movement_table: tuple[MovementTableEntry, ...],
    constraints: tuple[TimingConstraint, ...],
) -> tuple[WaitRecord, ...]:
    """Record blocking caused by handover precedence or crane interference."""

    _validate_movement_table(schedule, movement_table)
    constraints_by_operation: dict[int, list[TimingConstraint]] = {}
    for constraint in constraints:
        constraints_by_operation.setdefault(constraint.operation_index, []).append(
            constraint
        )
    by_crane: dict[str, list[int]] = {}
    for index, operation in enumerate(schedule.operations):
        by_crane.setdefault(operation.crane_id, []).append(index)

    records: list[WaitRecord] = []
    for crane_id, indices in by_crane.items():
        indices.sort(
            key=lambda index: (
                schedule.operations[index].start_time,
                schedule.operations[index].end_time,
                index,
            )
        )
        previous_end = instance.initial_state.cranes_by_id[crane_id].available_time
        for index in indices:
            operation = schedule.operations[index]
            earliest = previous_end
            if operation.job_id is not None:
                earliest = max(
                    earliest,
                    instance.jobs_by_id[operation.job_id].ready_time,
                )
            gap = operation.start_time - earliest
            causes = constraints_by_operation.get(index, ())
            if gap > 1e-9 and causes:
                interference = tuple(
                    constraint
                    for constraint in causes
                    if constraint.reason is TimingConstraintReason.CRANE_CONFLICT_REPAIR
                )
                relevant = interference or tuple(causes)
                selected = max(
                    relevant,
                    key=lambda constraint: (
                        constraint.earliest_start,
                        -1
                        if constraint.opposing_operation_index is None
                        else schedule.operations[
                            constraint.opposing_operation_index
                        ].end_time,
                    ),
                )
                reason = (
                    WaitReason.CRANE_INTERFERENCE
                    if interference
                    else WaitReason.HANDOVER_PRECEDENCE
                )
                records.append(
                    WaitRecord(
                        operation_index=index,
                        crane_id=crane_id,
                        request_block_id=movement_table[index].request_block_id,
                        reason=reason,
                        start_time=earliest,
                        end_time=operation.start_time,
                        opposing_operation_index=selected.opposing_operation_index,
                    )
                )
            previous_end = operation.end_time
    records.sort(
        key=lambda record: (
            movement_table[record.operation_index].movement_table_rank,
            record.operation_index,
        )
    )
    return tuple(records)


def calculate_blocking_seconds(wait_records: tuple[WaitRecord, ...]) -> float:
    """Return paper blocking time from explicitly classified waits."""

    return sum(record.seconds for record in wait_records)


def _movement_priority_key(entry: MovementTableEntry) -> tuple[int, int, int]:
    phase_rank = 0 if entry.phase is MovementPhase.DONOR else 1
    return entry.movement_table_rank, phase_rank, entry.operation_index


def _leg_end_indices(
    schedule: CandidateSchedule,
    movement_table: tuple[MovementTableEntry, ...],
) -> dict[int, int]:
    by_rank: dict[int, list[int]] = {}
    for entry in movement_table:
        by_rank.setdefault(entry.movement_table_rank, []).append(entry.operation_index)
    return {
        rank: max(
            indices,
            key=lambda index: (
                schedule.operations[index].end_time,
                schedule.operations[index].start_time,
                index,
            ),
        )
        for rank, indices in by_rank.items()
    }


def _validate_movement_table(
    schedule: CandidateSchedule,
    movement_table: tuple[MovementTableEntry, ...],
) -> None:
    if len(movement_table) != len(schedule.operations):
        raise ValueError("movement table must cover every scheduled operation")
    if tuple(entry.operation_index for entry in movement_table) != tuple(
        range(len(schedule.operations))
    ):
        raise ValueError("movement table entries must follow operation index order")
