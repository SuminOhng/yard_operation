"""Two-crane scheduler that forbids every container handover."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from ...model import (
    ContainerStatus,
    CraneSide,
    Job,
    Position,
    Slot,
    StackKey,
    StaticSchedulingInstance,
)
from ...policy import CooperationPolicy, constraints_for
from ...schedule import (
    CandidateSchedule,
    OperationPurpose,
    OperationType,
    ScheduledOperation,
)
from ...simulation import first_crane_conflict
from ...timing import TimeModel
from ...validator import validate_schedule
from ..common import PlannerInfeasibleError, append_blocker_reshuffles


class JobRegion(str, Enum):
    SEA_LOCAL = "SEA_LOCAL"
    LAND_LOCAL = "LAND_LOCAL"
    CROSS_REGION = "CROSS_REGION"


@dataclass(slots=True)
class _PlanningState:
    stacks: dict[StackKey, list[str]]
    container_slots: dict[str, Slot | None]
    container_statuses: dict[str, ContainerStatus]
    crane_times: dict[str, float]
    crane_positions: dict[str, Position]
    operations: list[ScheduledOperation]


@dataclass(slots=True)
class _PreReshuffleTrial:
    state: _PlanningState
    blocker_count: int
    makespan: float


def classify_job(
    instance: StaticSchedulingInstance,
    job: Job,
) -> JobRegion:
    """Classify a job into disjoint safe work zones or the cross-zone phase."""

    separation = max(
        1, math.ceil(instance.physical_rules.minimum_crane_separation_bays)
    )
    sea_limit = instance.layout.handshake_bay
    land_limit = sea_limit + separation
    bays = (job.origin.bay, job.destination.bay)
    if max(bays) <= sea_limit:
        return JobRegion.SEA_LOCAL
    if min(bays) >= land_limit:
        return JobRegion.LAND_LOCAL
    return JobRegion.CROSS_REGION


def build_no_sharing_schedule(
    instance: StaticSchedulingInstance,
    policy: CooperationPolicy = CooperationPolicy.NO_SHARING,
) -> CandidateSchedule:
    """Build a conservative schedule using both cranes without handovers.

    Local jobs run concurrently in separated zones.  Cross-region jobs run in
    a protected phase: the non-working crane parks at its outside access bay.
    Blocking containers are moved to the nearest safe, non-reserved stack.
    """

    if policy is not CooperationPolicy.NO_SHARING:
        raise ValueError("the no-sharing scheduler accepts NO_SHARING only")

    timing = TimeModel(instance.motion)
    state = _initial_planning_state(instance)
    cranes = {crane.side: crane for crane in instance.cranes}
    sea = cranes[CraneSide.SEASIDE]
    land = cranes[CraneSide.LANDSIDE]
    reserved_final_stacks = {
        job.final_slot.stack_key
        for job in instance.jobs
        if job.final_slot is not None
    }

    local: dict[JobRegion, list[Job]] = {
        JobRegion.SEA_LOCAL: [],
        JobRegion.LAND_LOCAL: [],
    }
    cross: list[Job] = []
    for job in instance.jobs:
        region = classify_job(instance, job)
        if region is JobRegion.CROSS_REGION:
            cross.append(job)
        else:
            local[region].append(job)

    separation = max(
        1, math.ceil(instance.physical_rules.minimum_crane_separation_bays)
    )
    sea_local_bays = range(
        instance.layout.first_work_bay,
        instance.layout.handshake_bay + 1,
    )
    land_local_bays = range(
        instance.layout.handshake_bay + separation,
        instance.layout.last_work_bay + 1,
    )
    for job in local[JobRegion.SEA_LOCAL]:
        _append_job(
            instance, state, timing, sea.id, job, sea_local_bays,
            reserved_final_stacks,
        )
    if local[JobRegion.SEA_LOCAL] and not local[JobRegion.LAND_LOCAL]:
        _append_early_landside_pre_reshuffles(
            instance,
            state,
            timing,
            land.id,
            cross,
            land_local_bays,
            reserved_final_stacks,
        )
    for job in local[JobRegion.LAND_LOCAL]:
        _append_job(
            instance, state, timing, land.id, job, land_local_bays,
            reserved_final_stacks,
        )

    for index, job in enumerate(cross):
        worker = _cross_worker(instance, state, timing, job, sea.id, land.id)
        other = land.id if worker == sea.id else sea.id
        safe_bays = _cross_reshuffle_bays(instance, worker, sea.id)
        if worker == sea.id and other == land.id:
            _append_cross_job_with_landside_pre_reshuffle(
                instance,
                state,
                timing,
                job,
                sea.id,
                land.id,
                safe_bays,
                land_local_bays,
                cross[index + 1 :],
                reserved_final_stacks,
            )
        else:
            _park_for_cross_job(instance, state, timing, worker, other)
            _append_job(
                instance, state, timing, worker, job, safe_bays,
                reserved_final_stacks,
            )

    schedule = CandidateSchedule(
        instance.instance_id,
        CooperationPolicy.NO_SHARING,
        tuple(
            sorted(
                state.operations,
                key=lambda operation: (
                    operation.start_time,
                    operation.end_time,
                    operation.crane_id,
                ),
            )
        ),
    )
    validation = validate_schedule(
        instance,
        constraints_for(instance, CooperationPolicy.NO_SHARING),
        schedule,
    )
    if not validation.valid:
        details = "; ".join(
            f"{issue.code}: {issue.message}" for issue in validation.issues
        )
        raise PlannerInfeasibleError(
            f"no-sharing planner produced an invalid schedule: {details}"
        )
    return schedule


def _initial_planning_state(
    instance: StaticSchedulingInstance,
) -> _PlanningState:
    initial = instance.initial_state
    return _PlanningState(
        stacks={key: list(stack.containers) for key, stack in initial.stacks_by_key.items()},
        container_slots={
            container_id: container.current_slot
            for container_id, container in initial.containers_by_id.items()
        },
        container_statuses={
            container_id: container.status
            for container_id, container in initial.containers_by_id.items()
        },
        crane_times={
            crane_id: state.available_time
            for crane_id, state in initial.cranes_by_id.items()
        },
        crane_positions={
            crane_id: state.position
            for crane_id, state in initial.cranes_by_id.items()
        },
        operations=[],
    )


def _append_job(
    instance: StaticSchedulingInstance,
    state: _PlanningState,
    timing: TimeModel,
    crane_id: str,
    job: Job,
    reshuffle_bays: range,
    reserved_final_stacks: set[StackKey],
) -> None:
    state.crane_times[crane_id] = max(
        state.crane_times[crane_id], job.ready_time
    )
    container_status = state.container_statuses[job.container_id]
    if container_status is ContainerStatus.IN_STACK:
        append_blocker_reshuffles(
            instance,
            state,
            timing,
            crane_id,
            job.container_id,
            reshuffle_bays,
            reserved_final_stacks,
        )

    _append_move(
        state, timing, crane_id, OperationType.MOVE_EMPTY, job.origin,
        job_id=None,
    )
    pickup_slot = state.container_slots[job.container_id]
    pickup_duration = timing.pickup_seconds(pickup_slot)
    _append_handling(
        state,
        crane_id,
        OperationType.PICKUP,
        pickup_duration,
        job_id=job.id,
    )
    if pickup_slot is not None:
        state.stacks[pickup_slot.stack_key].pop()
    state.container_slots[job.container_id] = None
    state.container_statuses[job.container_id] = ContainerStatus.ON_CRANE

    _append_move(
        state, timing, crane_id, OperationType.MOVE_LOADED,
        job.destination, job_id=job.id,
    )
    _append_handling(
        state,
        crane_id,
        OperationType.FINAL_DROP,
        timing.drop_seconds(job.final_slot),
        job_id=job.id,
    )
    if job.final_slot is not None:
        stack = state.stacks[job.final_slot.stack_key]
        if len(stack) + 1 != job.final_slot.tier:
            raise PlannerInfeasibleError(
                f"job {job.id!r} target tier is not the next free tier"
            )
        stack.append(job.container_id)
        state.container_slots[job.container_id] = job.final_slot
    state.container_statuses[job.container_id] = (
        ContainerStatus.IN_STACK
        if job.final_slot is not None
        else ContainerStatus.COMPLETED
    )


def _append_cross_job_with_landside_pre_reshuffle(
    instance: StaticSchedulingInstance,
    state: _PlanningState,
    timing: TimeModel,
    job: Job,
    sea_id: str,
    land_id: str,
    sea_worker_reshuffle_bays: range,
    land_reshuffle_bays: range,
    remaining_cross_jobs: list[Job],
    reserved_final_stacks: set[StackKey],
) -> None:
    baseline = _clone_planning_state(state)
    _park_for_cross_job(instance, baseline, timing, sea_id, land_id)
    _append_job(
        instance,
        baseline,
        timing,
        sea_id,
        job,
        sea_worker_reshuffle_bays,
        reserved_final_stacks,
    )
    baseline_makespan = max(baseline.crane_times.values())
    best = _PreReshuffleTrial(baseline, blocker_count=0, makespan=baseline_makespan)

    for future_job in _landside_pre_reshuffle_candidates(
        state, job, remaining_cross_jobs, land_reshuffle_bays
    ):
        candidate = _clone_planning_state(state)
        phase_start = max(candidate.crane_times.values())
        candidate.crane_times[sea_id] = phase_start
        candidate.crane_times[land_id] = phase_start
        try:
            _append_job(
                instance,
                candidate,
                timing,
                sea_id,
                job,
                sea_worker_reshuffle_bays,
                reserved_final_stacks,
            )
            blocker_count = _blocker_count(state, future_job.container_id)
            append_blocker_reshuffles(
                instance,
                candidate,
                timing,
                land_id,
                future_job.container_id,
                land_reshuffle_bays,
                reserved_final_stacks,
            )
        except PlannerInfeasibleError:
            continue
        makespan = max(candidate.crane_times.values())
        if makespan > baseline_makespan + 1e-9:
            continue
        if _has_crane_conflict(instance, candidate):
            continue
        trial = _PreReshuffleTrial(candidate, blocker_count, makespan)
        if (trial.blocker_count, -trial.makespan) > (
            best.blocker_count,
            -best.makespan,
        ):
            best = trial

    _replace_planning_state(state, best.state)


def _landside_pre_reshuffle_candidates(
    state: _PlanningState,
    current_job: Job | None,
    remaining_cross_jobs: list[Job],
    land_reshuffle_bays: range,
) -> tuple[Job, ...]:
    allowed_bays = set(land_reshuffle_bays)
    current_slot = (
        state.container_slots.get(current_job.container_id)
        if current_job is not None
        else None
    )
    jobs: list[Job] = []
    for job in remaining_cross_jobs:
        source_slot = state.container_slots.get(job.container_id)
        if (
            state.container_statuses.get(job.container_id)
            is not ContainerStatus.IN_STACK
            or source_slot is None
            or source_slot.bay not in allowed_bays
            or (
                current_slot is not None
                and source_slot.stack_key == current_slot.stack_key
            )
            or _blocker_count(state, job.container_id) <= 0
        ):
            continue
        jobs.append(job)
        if len(jobs) >= 3:
            break
    return tuple(jobs)


def _append_early_landside_pre_reshuffles(
    instance: StaticSchedulingInstance,
    state: _PlanningState,
    timing: TimeModel,
    land_id: str,
    future_jobs: list[Job],
    land_reshuffle_bays: range,
    reserved_final_stacks: set[StackKey],
) -> None:
    for future_job in _landside_pre_reshuffle_candidates(
        state, future_jobs[0] if future_jobs else None,
        future_jobs,
        land_reshuffle_bays,
    ):
        if _blocker_count(state, future_job.container_id) <= 0:
            continue
        candidate = _clone_planning_state(state)
        try:
            append_blocker_reshuffles(
                instance,
                candidate,
                timing,
                land_id,
                future_job.container_id,
                land_reshuffle_bays,
                reserved_final_stacks,
            )
        except PlannerInfeasibleError:
            continue
        if _has_crane_conflict(instance, candidate):
            continue
        _replace_planning_state(state, candidate)


def _blocker_count(state: _PlanningState, container_id: str) -> int:
    source_slot = state.container_slots.get(container_id)
    if source_slot is None:
        return 0
    source_stack = state.stacks.get(source_slot.stack_key)
    if not source_stack or container_id not in source_stack:
        return 0
    return len(source_stack) - source_stack.index(container_id) - 1


def _has_crane_conflict(
    instance: StaticSchedulingInstance,
    state: _PlanningState,
) -> bool:
    schedule = CandidateSchedule(
        instance.instance_id,
        CooperationPolicy.NO_SHARING,
        tuple(
            sorted(
                state.operations,
                key=lambda operation: (
                    operation.start_time,
                    operation.end_time,
                    operation.crane_id,
                ),
            )
        ),
    )
    return first_crane_conflict(instance, schedule) is not None


def _clone_planning_state(state: _PlanningState) -> _PlanningState:
    return _PlanningState(
        stacks={key: list(stack) for key, stack in state.stacks.items()},
        container_slots=dict(state.container_slots),
        container_statuses=dict(state.container_statuses),
        crane_times=dict(state.crane_times),
        crane_positions=dict(state.crane_positions),
        operations=list(state.operations),
    )


def _replace_planning_state(
    state: _PlanningState,
    replacement: _PlanningState,
) -> None:
    state.stacks = replacement.stacks
    state.container_slots = replacement.container_slots
    state.container_statuses = replacement.container_statuses
    state.crane_times = replacement.crane_times
    state.crane_positions = replacement.crane_positions
    state.operations = replacement.operations


def _append_move(
    state: _PlanningState,
    timing: TimeModel,
    crane_id: str,
    operation_type: OperationType,
    destination: Position,
    *,
    job_id: str | None = None,
    container_id: str | None = None,
    purpose: OperationPurpose = OperationPurpose.PRIMARY_JOB,
) -> None:
    origin = state.crane_positions[crane_id]
    duration = timing.travel_seconds(origin, destination)
    if duration <= 0:
        return
    start = state.crane_times[crane_id]
    state.operations.append(
        ScheduledOperation(
            crane_id,
            operation_type,
            start,
            start + duration,
            origin,
            destination,
            job_id=job_id,
            container_id=container_id,
            purpose=purpose,
        )
    )
    state.crane_times[crane_id] += duration
    state.crane_positions[crane_id] = destination


def _append_handling(
    state: _PlanningState,
    crane_id: str,
    operation_type: OperationType,
    duration: float,
    *,
    job_id: str | None = None,
    container_id: str | None = None,
    target_slot: Slot | None = None,
    purpose: OperationPurpose = OperationPurpose.PRIMARY_JOB,
) -> None:
    start = state.crane_times[crane_id]
    position = state.crane_positions[crane_id]
    state.operations.append(
        ScheduledOperation(
            crane_id,
            operation_type,
            start,
            start + duration,
            position,
            position,
            job_id=job_id,
            container_id=container_id,
            target_slot=target_slot,
            purpose=purpose,
        )
    )
    state.crane_times[crane_id] += duration


def _cross_worker(
    instance: StaticSchedulingInstance,
    state: _PlanningState,
    timing: TimeModel,
    job: Job,
    sea_id: str,
    land_id: str,
) -> str:
    sea_gate = instance.layout.seaside_parking_bay
    land_gate = instance.layout.landside_parking_bay
    endpoints = {job.origin.bay, job.destination.bay}
    if sea_gate in endpoints and land_gate in endpoints:
        raise PlannerInfeasibleError(
            f"job {job.id!r} spans both outside gates and needs cooperation"
        )
    if sea_gate in endpoints:
        return sea_id
    if land_gate in endpoints:
        return land_id
    sea_cost = timing.travel_seconds(state.crane_positions[sea_id], job.origin)
    land_cost = timing.travel_seconds(state.crane_positions[land_id], job.origin)
    return sea_id if sea_cost <= land_cost else land_id


def _park_for_cross_job(
    instance: StaticSchedulingInstance,
    state: _PlanningState,
    timing: TimeModel,
    worker: str,
    other: str,
) -> None:
    phase_start = max(state.crane_times.values())
    for crane_id in state.crane_times:
        state.crane_times[crane_id] = max(
            state.crane_times[crane_id], phase_start
        )
    other_spec = instance.cranes_by_id[other]
    parking_bay = (
        instance.layout.seaside_parking_bay
        if other_spec.side is CraneSide.SEASIDE
        else instance.layout.landside_parking_bay
    )
    _append_move(
        state,
        timing,
        other,
        OperationType.MOVE_EMPTY,
        Position(parking_bay, state.crane_positions[other].row),
    )
    # The worker waits until the other crane has reached the protected bay.
    state.crane_times[worker] = max(
        state.crane_times[worker], state.crane_times[other]
    )


def _cross_reshuffle_bays(
    instance: StaticSchedulingInstance,
    worker: str,
    sea_id: str,
) -> range:
    separation = max(
        1, math.ceil(instance.physical_rules.minimum_crane_separation_bays)
    )
    if worker == sea_id:
        return range(
            instance.layout.first_work_bay,
            instance.layout.landside_parking_bay + 1 - separation,
        )
    return range(separation, instance.layout.last_work_bay + 1)
