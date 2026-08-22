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


class _IdleActionKind(str, Enum):
    PARK_ONLY = "PARK_ONLY"
    PREPOSITION = "PREPOSITION"
    LOCAL_JOB = "LOCAL_JOB"


@dataclass(slots=True)
class _PlanningState:
    stacks: dict[StackKey, list[str]]
    container_slots: dict[str, Slot | None]
    container_statuses: dict[str, ContainerStatus]
    crane_times: dict[str, float]
    crane_positions: dict[str, Position]
    operations: list[ScheduledOperation]


@dataclass(slots=True)
class _CrossTrial:
    state: _PlanningState
    worker: str
    idle_action_kind: _IdleActionKind
    makespan: float
    next_origin_distance: float
    completed_idle_job_id: str | None = None


@dataclass(frozen=True, slots=True)
class _IdleAction:
    kind: _IdleActionKind
    job: Job | None = None
    destination: Position | None = None


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
    a protected phase: the non-working crane parks outside the job corridor.
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
    local_bays = {
        JobRegion.SEA_LOCAL: range(
            instance.layout.first_work_bay,
            instance.layout.handshake_bay + 1,
        ),
        JobRegion.LAND_LOCAL: range(
            instance.layout.handshake_bay + separation,
            instance.layout.last_work_bay + 1,
        ),
    }

    for index, job in enumerate(cross):
        _append_cross_job(
            instance,
            state,
            timing,
            job,
            sea.id,
            land.id,
            local,
            local_bays,
            cross[index + 1 :],
            reserved_final_stacks,
        )
    for job in local[JobRegion.SEA_LOCAL]:
        if cross:
            _prepare_for_leftover_local_job(
                instance, state, timing, sea.id, land.id, job, sea.id
            )
        _append_job(
            instance, state, timing, sea.id, job,
            local_bays[JobRegion.SEA_LOCAL],
            reserved_final_stacks,
        )
    for job in local[JobRegion.LAND_LOCAL]:
        if cross:
            _prepare_for_leftover_local_job(
                instance, state, timing, land.id, sea.id, job, sea.id
            )
        _append_job(
            instance, state, timing, land.id, job,
            local_bays[JobRegion.LAND_LOCAL],
            reserved_final_stacks,
        )
    _normalize_relief_crane_positions(instance, state, timing, sea.id, land.id)

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


def _append_cross_job(
    instance: StaticSchedulingInstance,
    state: _PlanningState,
    timing: TimeModel,
    job: Job,
    sea_id: str,
    land_id: str,
    local_jobs: dict[JobRegion, list[Job]],
    local_bays: dict[JobRegion, range],
    remaining_cross_jobs: list[Job],
    reserved_final_stacks: set[StackKey],
) -> None:
    trials: list[_CrossTrial] = []
    for worker in (sea_id, land_id):
        other = land_id if worker == sea_id else sea_id
        for idle_action in _idle_actions_for_cross_job(
            instance,
            state,
            timing,
            other,
            sea_id,
            local_jobs,
            remaining_cross_jobs,
        ):
            trial_state = _clone_planning_state(state)
            try:
                _append_cross_trial(
                    instance,
                    trial_state,
                    timing,
                    worker,
                    other,
                    job,
                    idle_action,
                    sea_id,
                    local_bays,
                    reserved_final_stacks,
                )
            except PlannerInfeasibleError:
                continue
            if _has_crane_conflict(instance, trial_state):
                continue
            trials.append(
                _CrossTrial(
                    state=trial_state,
                    worker=worker,
                    idle_action_kind=idle_action.kind,
                    makespan=max(trial_state.crane_times.values()),
                    next_origin_distance=_next_origin_distance(
                        trial_state, other, local_jobs, remaining_cross_jobs
                    ),
                    completed_idle_job_id=(
                        idle_action.job.id
                        if idle_action.kind is _IdleActionKind.LOCAL_JOB
                        and idle_action.job is not None
                        else None
                    ),
                )
            )
    if not trials:
        raise PlannerInfeasibleError(
            f"job {job.id!r} has no feasible no-sharing direct worker"
        )
    chosen = min(
        trials,
        key=lambda trial: (
            0 if trial.idle_action_kind is _IdleActionKind.LOCAL_JOB else 1,
            trial.makespan,
            trial.next_origin_distance,
            trial.worker,
        ),
    )
    _replace_planning_state(state, chosen.state)
    if chosen.completed_idle_job_id is not None:
        _remove_local_job(local_jobs, chosen.completed_idle_job_id)


def _append_cross_trial(
    instance: StaticSchedulingInstance,
    state: _PlanningState,
    timing: TimeModel,
    worker: str,
    other: str,
    job: Job,
    idle_action: _IdleAction,
    sea_id: str,
    local_bays: dict[JobRegion, range],
    reserved_final_stacks: set[StackKey],
) -> None:
    _align_cross_phase(state)
    safe_bays = _cross_reshuffle_bays(instance, worker, sea_id)
    if idle_action.kind is _IdleActionKind.PARK_ONLY:
        _park_other_for_cross_job(instance, state, timing, worker, other, job)
        _append_job(
            instance,
            state,
            timing,
            worker,
            job,
            safe_bays,
            reserved_final_stacks,
        )
        return

    phase_start = max(state.crane_times.values())
    state.crane_times[worker] = phase_start
    state.crane_times[other] = phase_start
    _append_job(
        instance,
        state,
        timing,
        worker,
        job,
        safe_bays,
        reserved_final_stacks,
    )
    if idle_action.kind is _IdleActionKind.PREPOSITION:
        if idle_action.destination is None:
            raise PlannerInfeasibleError("preposition action needs destination")
        _append_move(
            state,
            timing,
            other,
            OperationType.MOVE_EMPTY,
            idle_action.destination,
        )
    elif idle_action.kind is _IdleActionKind.LOCAL_JOB:
        if idle_action.job is None:
            raise PlannerInfeasibleError("local idle action needs a job")
        region = classify_job(instance, idle_action.job)
        if region not in local_bays:
            raise PlannerInfeasibleError("idle local action needs a local job")
        _append_job(
            instance,
            state,
            timing,
            other,
            idle_action.job,
            local_bays[region],
            reserved_final_stacks,
        )
        _park_other_for_cross_job(
            instance, state, timing, worker, other, job,
            wait_for_parking=False,
        )
    else:
        raise PlannerInfeasibleError(
            f"unsupported idle action {idle_action.kind.value}"
        )


def _align_cross_phase(state: _PlanningState) -> None:
    phase_start = max(state.crane_times.values())
    for crane_id in state.crane_times:
        state.crane_times[crane_id] = max(
            state.crane_times[crane_id], phase_start
        )


def _idle_actions_for_cross_job(
    instance: StaticSchedulingInstance,
    state: _PlanningState,
    timing: TimeModel,
    idle_crane_id: str,
    sea_id: str,
    local_jobs: dict[JobRegion, list[Job]],
    remaining_cross_jobs: list[Job],
) -> tuple[_IdleAction, ...]:
    actions: list[_IdleAction] = [_IdleAction(_IdleActionKind.PARK_ONLY)]
    idle_region = _local_region_for_crane(idle_crane_id, sea_id)
    for job in local_jobs[idle_region][:3]:
        actions.append(_IdleAction(_IdleActionKind.LOCAL_JOB, job=job))
    for target in _preposition_targets(
        instance, state, timing, idle_crane_id, sea_id, local_jobs,
        remaining_cross_jobs,
    ):
        actions.append(
            _IdleAction(_IdleActionKind.PREPOSITION, destination=target)
        )
    return tuple(actions)


def _preposition_targets(
    instance: StaticSchedulingInstance,
    state: _PlanningState,
    timing: TimeModel,
    idle_crane_id: str,
    sea_id: str,
    local_jobs: dict[JobRegion, list[Job]],
    remaining_cross_jobs: list[Job],
) -> tuple[Position, ...]:
    seen: set[Position] = set()
    targets: list[Position] = []
    idle_region = _local_region_for_crane(idle_crane_id, sea_id)
    candidates = [job.origin for job in local_jobs[idle_region][:2]]
    candidates.extend(job.origin for job in remaining_cross_jobs[:2])
    for target in candidates:
        if target in seen or target == state.crane_positions[idle_crane_id]:
            continue
        seen.add(target)
        targets.append(target)
    current = state.crane_positions[idle_crane_id]
    return tuple(
        sorted(
            targets,
            key=lambda target: timing.travel_seconds(current, target),
        )[:3]
    )


def _local_region_for_crane(crane_id: str, sea_id: str) -> JobRegion:
    if crane_id == sea_id:
        return JobRegion.SEA_LOCAL
    return JobRegion.LAND_LOCAL


def _remove_local_job(
    local_jobs: dict[JobRegion, list[Job]],
    job_id: str,
) -> None:
    for jobs in local_jobs.values():
        for index, job in enumerate(jobs):
            if job.id == job_id:
                del jobs[index]
                return


def _next_origin_distance(
    state: _PlanningState,
    crane_id: str,
    local_jobs: dict[JobRegion, list[Job]],
    remaining_cross_jobs: list[Job],
) -> float:
    position = state.crane_positions[crane_id]
    origins = [
        job.origin
        for jobs in local_jobs.values()
        for job in jobs
    ]
    origins.extend(job.origin for job in remaining_cross_jobs)
    if not origins:
        return 0.0
    return min(
        abs(position.bay - origin.bay) + abs(position.row - origin.row)
        for origin in origins
    )


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


def _normalize_relief_crane_positions(
    instance: StaticSchedulingInstance,
    state: _PlanningState,
    timing: TimeModel,
    sea_id: str,
    land_id: str,
) -> None:
    separation = max(
        1, math.ceil(instance.physical_rules.minimum_crane_separation_bays)
    )
    sea_parking = instance.layout.seaside_parking_bay
    land_parking = instance.layout.landside_parking_bay
    sea_position = state.crane_positions[sea_id]
    land_position = state.crane_positions[land_id]
    if sea_position.bay < sea_parking:
        minimum_land_bay = sea_parking + separation
        if land_position.bay < minimum_land_bay:
            _append_move(
                state,
                timing,
                land_id,
                OperationType.MOVE_EMPTY,
                Position(minimum_land_bay, land_position.row),
            )
        state.crane_times[sea_id] = max(
            state.crane_times[sea_id], state.crane_times[land_id]
        )
        _append_move(
            state,
            timing,
            sea_id,
            OperationType.MOVE_EMPTY,
            Position(sea_parking, sea_position.row),
        )
    sea_position = state.crane_positions[sea_id]
    land_position = state.crane_positions[land_id]
    if land_position.bay > land_parking:
        maximum_sea_bay = land_parking - separation
        if sea_position.bay > maximum_sea_bay:
            _append_move(
                state,
                timing,
                sea_id,
                OperationType.MOVE_EMPTY,
                Position(maximum_sea_bay, sea_position.row),
            )
        state.crane_times[land_id] = max(
            state.crane_times[land_id], state.crane_times[sea_id]
        )
        _append_move(
            state,
            timing,
            land_id,
            OperationType.MOVE_EMPTY,
            Position(land_parking, land_position.row),
        )


def _prepare_for_leftover_local_job(
    instance: StaticSchedulingInstance,
    state: _PlanningState,
    timing: TimeModel,
    worker: str,
    other: str,
    job: Job,
    sea_id: str,
) -> None:
    separation = max(
        1, math.ceil(instance.physical_rules.minimum_crane_separation_bays)
    )
    if worker == sea_id:
        required_other_bay = instance.layout.handshake_bay + separation
        other_position = state.crane_positions[other]
        if other_position.bay < required_other_bay:
            _append_move(
                state,
                timing,
                other,
                OperationType.MOVE_EMPTY,
                Position(required_other_bay, other_position.row),
            )
    else:
        required_other_bay = instance.layout.handshake_bay
        other_position = state.crane_positions[other]
        if other_position.bay > required_other_bay:
            _append_move(
                state,
                timing,
                other,
                OperationType.MOVE_EMPTY,
                Position(required_other_bay, other_position.row),
            )
    state.crane_times[worker] = max(
        state.crane_times[worker],
        state.crane_times[other],
        job.ready_time,
    )


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


def _park_other_for_cross_job(
    instance: StaticSchedulingInstance,
    state: _PlanningState,
    timing: TimeModel,
    worker: str,
    other: str,
    job: Job,
    *,
    wait_for_parking: bool = True,
) -> None:
    parking_bay = _parking_bay_for_cross_job(instance, other, job)
    if parking_bay is None:
        raise PlannerInfeasibleError(
            f"crane {other!r} cannot park safely for job {job.id!r}"
        )
    _append_move(
        state,
        timing,
        other,
        OperationType.MOVE_EMPTY,
        Position(parking_bay, state.crane_positions[other].row),
    )
    if wait_for_parking:
        state.crane_times[worker] = max(
            state.crane_times[worker], state.crane_times[other]
        )


def _parking_bay_for_cross_job(
    instance: StaticSchedulingInstance,
    other: str,
    job: Job,
) -> int | None:
    other_spec = instance.cranes_by_id[other]
    separation = max(
        1, math.ceil(instance.physical_rules.minimum_crane_separation_bays)
    )
    endpoints = {job.origin.bay, job.destination.bay}
    if other_spec.side is CraneSide.SEASIDE:
        parking_bay = instance.layout.seaside_parking_bay
        if parking_bay not in endpoints:
            return parking_bay
        if separation == 1:
            return parking_bay - 1
        return None
    parking_bay = instance.layout.landside_parking_bay
    if parking_bay not in endpoints:
        return parking_bay
    if separation == 1:
        return parking_bay + 1
    return None


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
