"""Conservative direct-or-one-handover scheduler for the designated H bay."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ...model import (
    ContainerStatus,
    CraneSide,
    Job,
    Position,
    Slot,
    StackKey,
    StaticSchedulingInstance,
    TransferSlotSpec,
)
from ...policy import CooperationPolicy, constraints_for
from ...schedule import (
    CandidateSchedule,
    OperationPurpose,
    OperationType,
    ScheduledOperation,
)
from ...timing import TimeModel
from ...validator import validate_schedule
from ..common import (
    PlannerCandidateEvaluation,
    PlannerInfeasibleError,
    append_blocker_reshuffles,
)
from ..no_sharing import JobRegion, classify_job


@dataclass(slots=True)
class _HandshakePlanningState:
    stacks: dict[StackKey, list[str]]
    container_slots: dict[str, Slot | None]
    container_statuses: dict[str, ContainerStatus]
    crane_times: dict[str, float]
    crane_positions: dict[str, Position]
    operations: list[ScheduledOperation]


def build_handshake_area_schedule(
    instance: StaticSchedulingInstance,
    policy: CooperationPolicy = CooperationPolicy.HANDSHAKE_AREA,
) -> CandidateSchedule:
    """Return the best valid designated-H candidate found.

    Local jobs run directly. True cross-region jobs are split into donor and
    receiver legs with exactly one transfer-slot drop/pickup pair.
    """

    if policy is not CooperationPolicy.HANDSHAKE_AREA:
        raise ValueError(
            "the handshake-area scheduler accepts HANDSHAKE_AREA only"
        )

    evaluations = evaluate_handshake_area_candidates(instance)
    candidates = tuple(item for item in evaluations if item.valid)

    if not candidates:
        errors = tuple(
            f"{item.label}: {item.error}"
            for item in evaluations
            if item.error
        )
        detail = "; ".join(errors) if errors else "no candidate was generated"
        raise PlannerInfeasibleError(
            f"handshake-area planner found no valid schedule: {detail}"
        )
    selected = min(
        candidates,
        key=lambda item: (
            item.makespan,
            item.handover_count,
            len(item.schedule.operations),
            item.label,
        ),
    )
    if selected.schedule is None:
        raise AssertionError("valid candidate has no schedule")
    return selected.schedule


def evaluate_handshake_area_candidates(
    instance: StaticSchedulingInstance,
) -> tuple[PlannerCandidateEvaluation, ...]:
    """Evaluate conservative H and pipelined H candidates."""

    candidates: list[PlannerCandidateEvaluation] = []
    try:
        designated = _build_designated_h_schedule(instance)
        candidates.append(
            _evaluate_candidate(instance, "DESIGNATED_H", designated)
        )
    except (PlannerInfeasibleError, ValueError) as exc:
        candidates.append(
            PlannerCandidateEvaluation("DESIGNATED_H", None, None, str(exc))
        )

    try:
        from .pipeline import build_handshake_pipeline_schedule

        for order_strategy in ("original", "cross_first", "balanced_interleave"):
            ordered_jobs = _ordered_jobs(instance, order_strategy)
            for split_strategy in ("donor_leg", "receiver_leg"):
                for slot_heuristic in ("distance", "center", "rotating_distance"):
                    for pre_reshuffle_idle in (False, True):
                        suffix = (
                            ":idle_pre_reshuffle"
                            if pre_reshuffle_idle
                            else ""
                        )
                        label = (
                            "PIPELINE_H:"
                            f"{order_strategy}:{split_strategy}:"
                            f"{slot_heuristic}{suffix}"
                        )
                        try:
                            pipeline = build_handshake_pipeline_schedule(
                                instance,
                                jobs=ordered_jobs,
                                split_strategy=split_strategy,
                                slot_heuristic=slot_heuristic,
                                pre_reshuffle_idle=pre_reshuffle_idle,
                            )
                            candidates.append(
                                _evaluate_candidate(
                                    instance,
                                    label,
                                    pipeline.schedule,
                                )
                            )
                        except (PlannerInfeasibleError, ValueError) as exc:
                            candidates.append(
                                PlannerCandidateEvaluation(
                                    label,
                                    None,
                                    None,
                                    str(exc),
                                )
                            )
    except (PlannerInfeasibleError, ValueError) as exc:
        if not candidates:
            candidates.append(
                PlannerCandidateEvaluation("PIPELINE_H", None, None, str(exc))
            )
    return tuple(candidates)


def _ordered_jobs(
    instance: StaticSchedulingInstance,
    strategy: str,
) -> tuple[Job, ...]:
    if strategy == "original":
        return instance.jobs

    sea_local: list[Job] = []
    land_local: list[Job] = []
    cross: list[Job] = []
    for job in instance.jobs:
        region = classify_job(instance, job)
        if region is JobRegion.SEA_LOCAL:
            sea_local.append(job)
        elif region is JobRegion.LAND_LOCAL:
            land_local.append(job)
        else:
            cross.append(job)

    if strategy == "cross_first":
        return tuple(cross + sea_local + land_local)
    if strategy == "balanced_interleave":
        return _interleave_job_groups((sea_local, cross, land_local))
    raise PlannerInfeasibleError(f"unknown job order strategy {strategy!r}")


def _interleave_job_groups(groups: tuple[list[Job], ...]) -> tuple[Job, ...]:
    ordered: list[Job] = []
    remaining = True
    index = 0
    while remaining:
        remaining = False
        for group in groups:
            if index < len(group):
                ordered.append(group[index])
                remaining = True
        index += 1
    return tuple(ordered)


def _build_designated_h_schedule(
    instance: StaticSchedulingInstance,
) -> CandidateSchedule:
    """Build a conservative designated-H route with outer-bay returns."""

    timing = TimeModel(instance.motion)
    state = _initial_state(instance)
    cranes = {crane.side: crane for crane in instance.cranes}
    sea = cranes[CraneSide.SEASIDE]
    land = cranes[CraneSide.LANDSIDE]
    separation = _integer_separation(instance)
    reserved_final_stacks = {
        job.final_slot.stack_key
        for job in instance.jobs
        if job.final_slot is not None
    }
    transfer_slots = tuple(
        slot
        for slot in instance.yard.transfer_slots
        if slot.enabled and slot.position.bay == instance.layout.handshake_bay
    )
    if not transfer_slots:
        raise ValueError("designated H requires an enabled H slot")

    for job in instance.jobs:
        region = classify_job(instance, job)
        if region is JobRegion.SEA_LOCAL:
            _append_direct_job(
                instance,
                state,
                timing,
                sea.id,
                job,
                range(1, instance.layout.handshake_bay + 1),
                reserved_final_stacks,
            )
        elif region is JobRegion.LAND_LOCAL:
            _append_direct_job(
                instance,
                state,
                timing,
                land.id,
                job,
                range(
                    instance.layout.handshake_bay + separation,
                    instance.layout.last_work_bay + 1,
                ),
                reserved_final_stacks,
            )
        else:
            _append_handover_job(
                instance,
                state,
                timing,
                job,
                sea.id,
                land.id,
                transfer_slots,
                reserved_final_stacks,
            )
        _return_cranes_to_outer_bays(instance, state, timing)

    return CandidateSchedule(
        instance.instance_id,
        CooperationPolicy.HANDSHAKE_AREA,
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


def _evaluate_candidate(
    instance: StaticSchedulingInstance,
    label: str,
    schedule: CandidateSchedule,
) -> PlannerCandidateEvaluation:
    validation = validate_schedule(
        instance,
        constraints_for(instance, CooperationPolicy.HANDSHAKE_AREA),
        schedule,
    )
    if not validation.valid:
        details = "; ".join(
            f"{issue.code}: {issue.message}" for issue in validation.issues
        )
        return PlannerCandidateEvaluation(
            label,
            schedule,
            validation,
            f"{label} is invalid: {details}",
        )
    return PlannerCandidateEvaluation(label, schedule, validation)


def _append_direct_job(
    instance: StaticSchedulingInstance,
    state: _HandshakePlanningState,
    timing: TimeModel,
    crane_id: str,
    job: Job,
    reshuffle_bays: range,
    reserved_final_stacks: set[StackKey],
) -> None:
    state.crane_times[crane_id] = max(
        state.crane_times[crane_id], job.ready_time
    )
    _prepare_pickup(
        instance,
        state,
        timing,
        crane_id,
        job,
        reshuffle_bays,
        reserved_final_stacks,
    )
    _append_move(
        state,
        timing,
        crane_id,
        OperationType.MOVE_LOADED,
        job.destination,
        job_id=job.id,
    )
    _append_handling(
        state,
        crane_id,
        OperationType.FINAL_DROP,
        timing.drop_seconds(job.final_slot),
        job_id=job.id,
    )
    _finish_primary_job(state, job)


def _append_handover_job(
    instance: StaticSchedulingInstance,
    state: _HandshakePlanningState,
    timing: TimeModel,
    job: Job,
    sea_id: str,
    land_id: str,
    transfer_slots: tuple[TransferSlotSpec, ...],
    reserved_final_stacks: set[StackKey],
    *,
    synchronize_receiver: bool = True,
    split_strategy: str | None = None,
    slot_heuristic: str = "distance",
) -> None:
    separation = _integer_separation(instance)
    h_bay = instance.layout.handshake_bay
    if job.origin.bay <= h_bay and job.destination.bay >= h_bay + separation:
        donor_id, receiver_id = sea_id, land_id
        reshuffle_bays = range(1, h_bay + 1)
        donor_retreat_bay = h_bay - separation
        receiver_staging_bay = h_bay + separation
    elif (
        job.origin.bay >= h_bay + separation
        and job.destination.bay <= h_bay
    ):
        donor_id, receiver_id = land_id, sea_id
        reshuffle_bays = range(
            h_bay + separation,
            instance.layout.last_work_bay + 1,
        )
        donor_retreat_bay = h_bay + separation
        receiver_staging_bay = h_bay - separation
    else:
        raise PlannerInfeasibleError(
            f"job {job.id!r} does not connect the two protected regions"
        )

    if split_strategy is not None:
        if split_strategy == "donor_leg":
            synchronize_receiver = False
        elif split_strategy == "receiver_leg":
            synchronize_receiver = True
        else:
            raise PlannerInfeasibleError(
                f"unknown split strategy {split_strategy!r}"
            )
    transfer = _choose_transfer_slot(
        job,
        transfer_slots,
        timing,
        slot_heuristic=slot_heuristic,
        rows=instance.layout.rows,
        scheduled_operations=tuple(state.operations),
    )
    if not synchronize_receiver:
        _append_move(
            state,
            timing,
            receiver_id,
            OperationType.MOVE_EMPTY,
            Position(receiver_staging_bay, transfer.position.row),
        )
    state.crane_times[donor_id] = max(
        state.crane_times[donor_id], job.ready_time
    )
    _prepare_pickup(
        instance,
        state,
        timing,
        donor_id,
        job,
        reshuffle_bays,
        reserved_final_stacks,
    )
    handover_drop_seconds, handover_pickup_seconds = (
        _handover_handling_seconds(instance, state, timing, transfer)
    )
    _append_move(
        state,
        timing,
        donor_id,
        OperationType.MOVE_LOADED,
        transfer.position,
        job_id=job.id,
    )
    _append_handling(
        state,
        donor_id,
        OperationType.HANDOVER_DROP,
        handover_drop_seconds,
        job_id=job.id,
        transfer_slot_id=transfer.id,
        purpose=OperationPurpose.HANDOVER,
    )
    handover_complete_time = state.crane_times[donor_id]
    state.container_statuses[job.container_id] = (
        ContainerStatus.AT_TRANSFER_SLOT
    )

    _append_move(
        state,
        timing,
        donor_id,
        OperationType.MOVE_EMPTY,
        Position(donor_retreat_bay, transfer.position.row),
    )
    if synchronize_receiver:
        _synchronize(state)
    else:
        state.crane_times[receiver_id] = max(
            state.crane_times[receiver_id],
            handover_complete_time,
        )
    _append_move(
        state,
        timing,
        receiver_id,
        OperationType.MOVE_EMPTY,
        transfer.position,
    )
    _append_handling(
        state,
        receiver_id,
        OperationType.HANDOVER_PICKUP,
        handover_pickup_seconds,
        job_id=job.id,
        transfer_slot_id=transfer.id,
        purpose=OperationPurpose.HANDOVER,
    )
    state.container_statuses[job.container_id] = ContainerStatus.ON_CRANE
    if not synchronize_receiver:
        _append_move(
            state,
            timing,
            receiver_id,
            OperationType.MOVE_LOADED,
            Position(receiver_staging_bay, transfer.position.row),
            job_id=job.id,
        )
    _append_move(
        state,
        timing,
        receiver_id,
        OperationType.MOVE_LOADED,
        job.destination,
        job_id=job.id,
    )
    _append_handling(
        state,
        receiver_id,
        OperationType.FINAL_DROP,
        timing.drop_seconds(job.final_slot),
        job_id=job.id,
    )
    _finish_primary_job(state, job)


def _handover_handling_seconds(
    instance: StaticSchedulingInstance,
    state: _HandshakePlanningState,
    timing: TimeModel,
    transfer: TransferSlotSpec,
) -> tuple[float, float]:
    if not transfer.uses_stack_storage:
        return timing.drop_seconds(), timing.pickup_seconds()

    stack_key = StackKey(
        instance.layout.block_id,
        transfer.position.bay,
        transfer.position.row,
    )
    tier = len(state.stacks[stack_key]) + 1
    if tier > instance.yard.stacks_by_key[stack_key].capacity:
        raise PlannerInfeasibleError(
            f"stack-backed transfer point {transfer.id!r} has no free stack tier"
        )
    handover_slot = Slot(
        instance.layout.block_id,
        transfer.position.bay,
        transfer.position.row,
        tier,
    )
    return (
        timing.drop_seconds(handover_slot),
        timing.pickup_seconds(handover_slot),
    )


def _choose_transfer_slot(
    job: Job,
    transfer_slots: tuple[TransferSlotSpec, ...],
    timing: TimeModel,
    *,
    slot_heuristic: str = "distance",
    rows: int = 1,
    scheduled_operations: tuple[ScheduledOperation, ...] = (),
) -> TransferSlotSpec:
    """Choose an H row by strategy, then deterministic tie breaks."""

    if slot_heuristic not in ("distance", "center", "rotating_distance"):
        raise PlannerInfeasibleError(
            f"unknown slot heuristic {slot_heuristic!r}"
        )

    center_row = (rows + 1) / 2
    drop_counts = {
        slot.id: sum(
            1
            for operation in scheduled_operations
            if operation.operation_type is OperationType.HANDOVER_DROP
            and operation.transfer_slot_id == slot.id
        )
        for slot in transfer_slots
    }

    return min(
        transfer_slots,
        key=lambda slot: (
            drop_counts[slot.id] if slot_heuristic == "rotating_distance" else 0,
            (
                timing.travel_seconds(job.origin, slot.position)
                + timing.travel_seconds(slot.position, job.destination)
            )
            if slot_heuristic in ("distance", "rotating_distance")
            else abs(slot.position.row - center_row),
            abs(slot.position.row - job.origin.row)
            + abs(slot.position.row - job.destination.row),
            slot.position.row,
            slot.id,
        ),
    )


def _prepare_pickup(
    instance: StaticSchedulingInstance,
    state: _HandshakePlanningState,
    timing: TimeModel,
    crane_id: str,
    job: Job,
    reshuffle_bays: range,
    reserved_final_stacks: set[StackKey],
) -> None:
    if state.container_statuses[job.container_id] is ContainerStatus.IN_STACK:
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
        state,
        timing,
        crane_id,
        OperationType.MOVE_EMPTY,
        job.origin,
    )
    pickup_slot = state.container_slots[job.container_id]
    _append_handling(
        state,
        crane_id,
        OperationType.PICKUP,
        timing.pickup_seconds(pickup_slot),
        job_id=job.id,
    )
    if pickup_slot is not None:
        state.stacks[pickup_slot.stack_key].pop()
    state.container_slots[job.container_id] = None
    state.container_statuses[job.container_id] = ContainerStatus.ON_CRANE


def _finish_primary_job(
    state: _HandshakePlanningState,
    job: Job,
) -> None:
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


def _return_cranes_to_outer_bays(
    instance: StaticSchedulingInstance,
    state: _HandshakePlanningState,
    timing: TimeModel,
) -> None:
    cranes = {crane.side: crane for crane in instance.cranes}
    land = cranes[CraneSide.LANDSIDE]
    sea = cranes[CraneSide.SEASIDE]
    # Moving away from one another preserves the non-crossing invariant.
    _synchronize(state)
    _append_move(
        state,
        timing,
        land.id,
        OperationType.MOVE_EMPTY,
        Position(
            instance.layout.landside_parking_bay,
            state.crane_positions[land.id].row,
        ),
    )
    _synchronize(state)
    _append_move(
        state,
        timing,
        sea.id,
        OperationType.MOVE_EMPTY,
        Position(
            instance.layout.seaside_parking_bay,
            state.crane_positions[sea.id].row,
        ),
    )
    _synchronize(state)


def _append_move(
    state: _HandshakePlanningState,
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
    state: _HandshakePlanningState,
    crane_id: str,
    operation_type: OperationType,
    duration: float,
    *,
    job_id: str | None = None,
    transfer_slot_id: str | None = None,
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
            transfer_slot_id=transfer_slot_id,
            container_id=container_id,
            target_slot=target_slot,
            purpose=purpose,
        )
    )
    state.crane_times[crane_id] += duration


def _synchronize(state: _HandshakePlanningState) -> None:
    time = max(state.crane_times.values())
    for crane_id in state.crane_times:
        state.crane_times[crane_id] = time


def _initial_state(
    instance: StaticSchedulingInstance,
) -> _HandshakePlanningState:
    initial = instance.initial_state
    return _HandshakePlanningState(
        stacks={
            key: list(stack.containers)
            for key, stack in initial.stacks_by_key.items()
        },
        container_slots={
            container_id: container.current_slot
            for container_id, container in initial.containers_by_id.items()
        },
        container_statuses={
            container_id: container.status
            for container_id, container in initial.containers_by_id.items()
        },
        crane_times={
            crane_id: crane.available_time
            for crane_id, crane in initial.cranes_by_id.items()
        },
        crane_positions={
            crane_id: crane.position
            for crane_id, crane in initial.cranes_by_id.items()
        },
        operations=[],
    )


def _integer_separation(instance: StaticSchedulingInstance) -> int:
    return max(
        1, math.ceil(instance.physical_rules.minimum_crane_separation_bays)
    )
