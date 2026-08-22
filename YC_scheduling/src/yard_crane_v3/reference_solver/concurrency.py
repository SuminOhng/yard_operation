"""Derive independent crane sequences and left-shift fixed operations."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..model import StaticSchedulingInstance
from ..policy import CooperationPolicy, constraints_for
from ..schedule import CandidateSchedule, ScheduledOperation
from ..simulation import CraneConflict, detect_crane_conflicts
from ..validator import ValidationResult, validate_schedule


@dataclass(frozen=True, slots=True)
class CraneSequence:
    crane_id: str
    operation_indices: tuple[int, ...]
    job_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConcurrentCandidate:
    schedule: CandidateSchedule
    validation: ValidationResult
    crane_sequences: tuple[CraneSequence, ...]
    shifted_operation_count: int
    original_makespan: float
    conflicts: tuple[CraneConflict, ...]


def derive_crane_sequences(
    schedule: CandidateSchedule,
) -> tuple[CraneSequence, ...]:
    operations = _canonical_operations(schedule)
    crane_ids = sorted({operation.crane_id for operation in operations})
    sequences: list[CraneSequence] = []
    for crane_id in crane_ids:
        indices = tuple(
            index
            for index, operation in enumerate(operations)
            if operation.crane_id == crane_id
        )
        seen: set[str] = set()
        jobs: list[str] = []
        for index in indices:
            job_id = operations[index].job_id
            if job_id is not None and job_id not in seen:
                seen.add(job_id)
                jobs.append(job_id)
        sequences.append(CraneSequence(crane_id, indices, tuple(jobs)))
    return tuple(sequences)


def build_left_shifted_candidate(
    instance: StaticSchedulingInstance,
    policy: CooperationPolicy,
    schedule: CandidateSchedule,
) -> ConcurrentCandidate:
    """Move operations to their earliest precedence-feasible start times.

    The transformation preserves every per-crane operation order and every
    per-job operation order. The common validator remains the authority for
    crane separation, stack state, transfer capacity, and final completion.
    """

    operations = _canonical_operations(schedule)
    predecessors: list[set[int]] = [set() for _ in operations]
    sequences = derive_crane_sequences(schedule)
    for sequence in sequences:
        for previous, current in zip(
            sequence.operation_indices,
            sequence.operation_indices[1:],
        ):
            predecessors[current].add(previous)

    jobs: dict[str, list[int]] = {}
    for index, operation in enumerate(operations):
        if operation.job_id is not None:
            jobs.setdefault(operation.job_id, []).append(index)
    for indices in jobs.values():
        for previous, current in zip(indices, indices[1:]):
            predecessors[current].add(previous)

    shifted: list[ScheduledOperation] = []
    end_times: list[float] = []
    shifted_count = 0
    for index, operation in enumerate(operations):
        earliest = instance.initial_state.current_time
        if operation.job_id is not None:
            earliest = max(
                earliest,
                instance.jobs_by_id[operation.job_id].ready_time,
            )
        if predecessors[index]:
            earliest = max(
                earliest,
                *(end_times[pred] for pred in predecessors[index]),
            )
        duration = operation.end_time - operation.start_time
        updated = replace(
            operation,
            start_time=earliest,
            end_time=earliest + duration,
        )
        if abs(updated.start_time - operation.start_time) > 1e-9:
            shifted_count += 1
        shifted.append(updated)
        end_times.append(updated.end_time)

    candidate = CandidateSchedule(
        instance.instance_id,
        policy,
        tuple(
            sorted(
                shifted,
                key=lambda operation: (
                    operation.start_time,
                    operation.end_time,
                    operation.crane_id,
                    operation.operation_type.value,
                ),
            )
        ),
    )
    validation = validate_schedule(
        instance,
        constraints_for(instance, policy),
        candidate,
    )
    original_validation = validate_schedule(
        instance,
        constraints_for(instance, policy),
        schedule,
    )
    return ConcurrentCandidate(
        schedule=candidate,
        validation=validation,
        crane_sequences=sequences,
        shifted_operation_count=shifted_count,
        original_makespan=original_validation.makespan,
        conflicts=detect_crane_conflicts(instance, candidate),
    )


def _canonical_operations(
    schedule: CandidateSchedule,
) -> tuple[ScheduledOperation, ...]:
    return tuple(
        sorted(
            schedule.operations,
            key=lambda operation: (
                operation.start_time,
                operation.end_time,
                operation.crane_id,
                operation.operation_type.value,
            ),
        )
    )
