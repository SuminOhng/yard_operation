"""Conservative leg-ready dispatcher extending the 2017 seed order."""

from __future__ import annotations

import copy
from dataclasses import dataclass

from ...model import ContainerStatus, CraneSide, Job, MoveDirection, Position, StackKey
from ...policy import CooperationPolicy
from ...schedule import CandidateSchedule, OperationPurpose, OperationType
from ...timing import TimeModel
from ..common import PlannerInfeasibleError
from ..handshake_area.scheduler import (
    _append_direct_job,
    _append_handling,
    _append_move,
    _finish_primary_job,
    _initial_state,
    _integer_separation,
    _prepare_pickup,
)
from ..no_sharing import JobRegion, classify_job
from .paper_timing import (
    BypassRecord,
    MovementPhase,
    MovementTableEntry,
    PaperTimingResult,
    RequestLeg,
    SchedulingProfile,
    WaitReason,
    repair_with_current_job_priority,
)
from .ordering import (
    Handshake2017CandidateEvaluation,
    HandshakeStorageRule,
    SchedulingHeuristic,
    _donor_side,
)


@dataclass(frozen=True, slots=True)
class _DynamicLeg:
    rank: int
    job: Job
    crane_id: str
    phase: MovementPhase


@dataclass(frozen=True, slots=True)
class _DynamicBuildResult:
    timing_result: PaperTimingResult
    bypass_records: tuple[BypassRecord, ...]


def evaluate_dynamic_dispatch_candidate(
    instance,
    baseline: Handshake2017CandidateEvaluation,
    heuristic: SchedulingHeuristic,
    storage_rule: HandshakeStorageRule,
    *,
    max_repair_nodes: int,
    lookahead: int,
) -> Handshake2017CandidateEvaluation:
    label = (
        "GHAREHGOZLI2017:DYNAMIC_LEG_DISPATCH:"
        f"{heuristic.value}:{storage_rule.value}"
    )
    if not baseline.valid or not baseline.job_order:
        return Handshake2017CandidateEvaluation(
            label,
            baseline.schedule,
            baseline.validation,
            baseline.error,
            profile=SchedulingProfile.DYNAMIC_LEG_DISPATCH,
            job_order=baseline.job_order,
            fallback_used=True,
        )

    jobs_by_id = instance.jobs_by_id
    jobs = tuple(jobs_by_id[job_id] for job_id in baseline.job_order)
    try:
        built = _build_dynamic_schedule(
            instance,
            jobs,
            storage_rule,
            max_repair_nodes=max_repair_nodes,
            lookahead=lookahead,
        )
        if heuristic is SchedulingHeuristic.TWO_OPT:
            jobs, built = _improve_dynamic_order(
                instance,
                jobs,
                storage_rule,
                built,
                max_repair_nodes=max_repair_nodes,
                lookahead=lookahead,
                max_passes=2,
            )
        timing = built.timing_result
        experimental_makespan = timing.validation.makespan
        improved = (
            timing.validation.valid
            and baseline.makespan is not None
            and experimental_makespan < baseline.makespan
        )
        if improved:
            return Handshake2017CandidateEvaluation(
                label=label,
                schedule=timing.schedule,
                validation=timing.validation,
                blocking_seconds=timing.blocking_seconds,
                conflict_repairs=timing.conflict_repairs,
                movement_table=timing.movement_table,
                wait_records=timing.wait_records,
                request_legs=timing.request_legs,
                profile=SchedulingProfile.DYNAMIC_LEG_DISPATCH,
                job_order=tuple(job.id for job in jobs),
                bypass_records=built.bypass_records,
                experimental_makespan=experimental_makespan,
                attempted_bypass_records=built.bypass_records,
            )
        return _fallback_candidate(
            label,
            baseline,
            experimental_makespan=experimental_makespan,
            attempted=built.bypass_records,
        )
    except (PlannerInfeasibleError, ValueError) as exc:
        return _fallback_candidate(
            label,
            baseline,
            error=str(exc),
        )


def _improve_dynamic_order(
    instance,
    jobs: tuple[Job, ...],
    storage_rule: HandshakeStorageRule,
    seed: _DynamicBuildResult,
    *,
    max_repair_nodes: int,
    lookahead: int,
    max_passes: int,
) -> tuple[tuple[Job, ...], _DynamicBuildResult]:
    current_jobs = jobs
    current = seed
    for _ in range(max_passes):
        waiting_job_ids = {
            record.request_block_id
            for record in current.timing_result.wait_records
        }
        if not waiting_job_ids:
            break
        best_jobs = current_jobs
        best = current
        best_key = (
            current.timing_result.validation.makespan,
            current.timing_result.blocking_seconds,
        )
        for left in range(len(current_jobs) - 1):
            for right in range(left + 1, len(current_jobs)):
                if (
                    current_jobs[left].id not in waiting_job_ids
                    and current_jobs[right].id not in waiting_job_ids
                ):
                    continue
                trial_jobs = list(current_jobs)
                trial_jobs[left], trial_jobs[right] = (
                    trial_jobs[right],
                    trial_jobs[left],
                )
                try:
                    trial = _build_dynamic_schedule(
                        instance,
                        tuple(trial_jobs),
                        storage_rule,
                        max_repair_nodes=max_repair_nodes,
                        lookahead=lookahead,
                    )
                except (PlannerInfeasibleError, ValueError):
                    continue
                if not trial.timing_result.validation.valid:
                    continue
                trial_key = (
                    trial.timing_result.validation.makespan,
                    trial.timing_result.blocking_seconds,
                )
                if trial_key < best_key:
                    best_jobs = tuple(trial_jobs)
                    best = trial
                    best_key = trial_key
        if best_jobs == current_jobs:
            break
        current_jobs = best_jobs
        current = best
    return current_jobs, current


def _fallback_candidate(
    label: str,
    baseline: Handshake2017CandidateEvaluation,
    *,
    experimental_makespan: float | None = None,
    attempted: tuple[BypassRecord, ...] = (),
    error: str | None = None,
) -> Handshake2017CandidateEvaluation:
    return Handshake2017CandidateEvaluation(
        label=label,
        schedule=baseline.schedule,
        validation=baseline.validation,
        error=error,
        blocking_seconds=baseline.blocking_seconds,
        conflict_repairs=baseline.conflict_repairs,
        movement_table=baseline.movement_table,
        wait_records=baseline.wait_records,
        request_legs=baseline.request_legs,
        profile=SchedulingProfile.DYNAMIC_LEG_DISPATCH,
        job_order=baseline.job_order,
        fallback_used=True,
        experimental_makespan=experimental_makespan,
        attempted_bypass_records=attempted,
    )


def _build_dynamic_schedule(
    instance,
    jobs: tuple[Job, ...],
    storage_rule: HandshakeStorageRule,
    *,
    max_repair_nodes: int,
    lookahead: int,
) -> _DynamicBuildResult:
    timing = TimeModel(instance.motion)
    state = _initial_state(instance)
    cranes = {crane.side: crane for crane in instance.cranes}
    separation = _integer_separation(instance)
    reserved_final_stacks: set[StackKey] = {
        job.final_slot.stack_key for job in instance.jobs if job.final_slot is not None
    }
    legs = _make_legs(instance, jobs, cranes)
    pending = {
        crane.id: [leg for leg in legs if leg.crane_id == crane.id]
        for crane in instance.cranes
    }
    occupied = {
        slot_id: "__INITIAL__"
        for slot_id, slot in instance.initial_state.transfer_slots_by_id.items()
        if slot.containers
    }
    transfer_by_job = {}
    donor_drop_times: dict[str, float] = {}
    movement_table: list[MovementTableEntry] = []
    bypass_records: list[BypassRecord] = []

    while any(pending.values()):
        choice = _select_next_leg(
            instance,
            state,
            timing,
            pending,
            occupied,
            transfer_by_job,
            donor_drop_times,
            storage_rule,
            reserved_final_stacks,
            separation,
            lookahead,
        )
        if choice is None:
            remaining = ", ".join(
                f"{crane_id}:{queue[0].job.id}/{queue[0].phase.value}"
                for crane_id, queue in pending.items()
                if queue
            )
            raise PlannerInfeasibleError(
                f"dynamic leg dispatcher deadlocked with {remaining}"
            )
        crane_id, selected_index, leg, transfer, blocked = choice
        first_operation = len(state.operations)
        if leg.phase is MovementPhase.LOCAL:
            _execute_local(
                instance,
                state,
                timing,
                leg,
                reserved_final_stacks,
                separation,
            )
        elif leg.phase is MovementPhase.DONOR:
            if transfer is None:
                raise AssertionError("donor leg lacks transfer slot")
            _execute_donor(
                instance,
                state,
                timing,
                leg,
                transfer,
                reserved_final_stacks,
                separation,
            )
            transfer_by_job[leg.job.id] = transfer
            occupied[transfer.id] = leg.job.id
            donor_drop_times[leg.job.id] = next(
                operation.end_time
                for operation in reversed(state.operations[first_operation:])
                if operation.operation_type is OperationType.HANDOVER_DROP
            )
        else:
            transfer = transfer_by_job[leg.job.id]
            _execute_receiver(
                instance,
                state,
                timing,
                leg,
                transfer,
                donor_drop_times[leg.job.id],
                separation,
            )
            occupied.pop(transfer.id, None)

        for operation_index in range(first_operation, len(state.operations)):
            movement_table.append(
                MovementTableEntry(
                    operation_index=operation_index,
                    request_block_id=leg.job.id,
                    movement_table_rank=leg.rank,
                    phase=leg.phase,
                )
            )
        pending[crane_id].pop(selected_index)
        if blocked is not None:
            bypass_records.append(
                BypassRecord(
                    crane_id=crane_id,
                    blocked_request_block_id=blocked.job.id,
                    executed_request_block_id=leg.job.id,
                    wait_reason=WaitReason.HANDOVER_PRECEDENCE.value,
                    original_blocked_index=blocked.rank,
                    original_executed_index=leg.rank,
                )
            )

    request_legs = tuple(
        _request_leg(leg, transfer_by_job.get(leg.job.id))
        for leg in sorted(legs, key=lambda item: item.rank)
    )
    seed = CandidateSchedule(
        instance.instance_id,
        CooperationPolicy.HANDSHAKE_AREA,
        tuple(state.operations),
    )
    repaired = repair_with_current_job_priority(
        instance,
        seed,
        tuple(movement_table),
        request_legs,
        max_repairs=max_repair_nodes,
        interleaved_transfer_access=True,
    )
    return _DynamicBuildResult(repaired, tuple(bypass_records))


def _make_legs(instance, jobs, cranes) -> tuple[_DynamicLeg, ...]:
    legs: list[_DynamicLeg] = []
    for job in jobs:
        region = classify_job(instance, job)
        if region is JobRegion.SEA_LOCAL:
            legs.append(
                _DynamicLeg(
                    len(legs),
                    job,
                    cranes[CraneSide.SEASIDE].id,
                    MovementPhase.LOCAL,
                )
            )
        elif region is JobRegion.LAND_LOCAL:
            legs.append(
                _DynamicLeg(
                    len(legs),
                    job,
                    cranes[CraneSide.LANDSIDE].id,
                    MovementPhase.LOCAL,
                )
            )
        else:
            donor_side = _donor_side(instance, job)
            receiver_side = (
                CraneSide.LANDSIDE
                if donor_side is CraneSide.SEASIDE
                else CraneSide.SEASIDE
            )
            legs.append(
                _DynamicLeg(
                    len(legs), job, cranes[donor_side].id, MovementPhase.DONOR
                )
            )
            legs.append(
                _DynamicLeg(
                    len(legs),
                    job,
                    cranes[receiver_side].id,
                    MovementPhase.RECEIVER,
                )
            )
    return tuple(legs)


def _select_next_leg(
    instance,
    state,
    timing,
    pending,
    occupied,
    transfer_by_job,
    donor_drop_times,
    storage_rule,
    reserved_final_stacks,
    separation,
    lookahead,
):
    choices = []
    for crane_id, queue in pending.items():
        if not queue:
            continue
        first = queue[0]
        transfer = (
            _available_transfer(
                instance, timing, first.job, storage_rule, occupied
            )
            if first.phase is MovementPhase.DONOR
            else transfer_by_job.get(first.job.id)
        )
        if first.phase is MovementPhase.RECEIVER:
            drop_time = donor_drop_times.get(first.job.id)
            if drop_time is None:
                continue
            clock = state.crane_times[crane_id]
            if drop_time > clock + 1e-9:
                bypass = _find_safe_bypass(
                    instance,
                    state,
                    timing,
                    queue,
                    drop_time,
                    occupied,
                    transfer_by_job,
                    storage_rule,
                    reserved_final_stacks,
                    separation,
                    lookahead,
                )
                if bypass is not None:
                    index, leg, candidate_transfer = bypass
                    choices.append(
                        (
                            clock,
                            leg.rank,
                            crane_id,
                            index,
                            leg,
                            candidate_transfer,
                            first,
                        )
                    )
                    continue
            choices.append(
                (
                    max(clock, drop_time),
                    first.rank,
                    crane_id,
                    0,
                    first,
                    transfer,
                    None,
                )
            )
        elif first.phase is MovementPhase.DONOR and transfer is None:
            continue
        else:
            choices.append(
                (
                    max(state.crane_times[crane_id], first.job.ready_time),
                    first.rank,
                    crane_id,
                    0,
                    first,
                    transfer,
                    None,
                )
            )
    if not choices:
        return None
    _, _, crane_id, index, leg, transfer, blocked = min(choices)
    return crane_id, index, leg, transfer, blocked


def _find_safe_bypass(
    instance,
    state,
    timing,
    queue,
    deadline,
    occupied,
    transfer_by_job,
    storage_rule,
    reserved_final_stacks,
    separation,
    lookahead,
):
    for index in range(1, min(len(queue), lookahead + 1)):
        leg = queue[index]
        if leg.phase is MovementPhase.RECEIVER:
            continue
        transfer = (
            _available_transfer(
                instance, timing, leg.job, storage_rule, occupied
            )
            if leg.phase is MovementPhase.DONOR
            else None
        )
        if leg.phase is MovementPhase.DONOR and transfer is None:
            continue
        trial = copy.deepcopy(state)
        if leg.phase is MovementPhase.LOCAL:
            _execute_local(
                instance,
                trial,
                timing,
                leg,
                reserved_final_stacks,
                separation,
            )
        else:
            _execute_donor(
                instance,
                trial,
                timing,
                leg,
                transfer,
                reserved_final_stacks,
                separation,
            )
        blocked = queue[0]
        staging = _staging_position(
            instance,
            blocked.crane_id,
            transfer_by_job[blocked.job.id],
            separation,
        )
        _append_move(
            trial,
            timing,
            blocked.crane_id,
            OperationType.MOVE_EMPTY,
            staging,
        )
        if trial.crane_times[blocked.crane_id] <= deadline + 1e-9:
            return index, leg, transfer
    return None


def _available_transfer(instance, timing, job, storage_rule, occupied):
    slots = tuple(
        slot
        for slot in instance.yard.transfer_slots
        if slot.enabled
        and slot.position.bay == instance.layout.handshake_bay
        and slot.id not in occupied
    )
    if not slots:
        return None
    if storage_rule is HandshakeStorageRule.NEAR_IO:
        anchor = (
            job.origin
            if job.direction is MoveDirection.INBOUND
            else job.destination
        )
    else:
        anchor = (
            job.destination
            if job.direction is MoveDirection.INBOUND
            else job.origin
        )
    center = (instance.layout.rows + 1) / 2
    return min(
        slots,
        key=lambda slot: (
            timing.travel_seconds(anchor, slot.position),
            abs(slot.position.row - center),
            slot.position.row,
            slot.id,
        ),
    )


def _execute_local(instance, state, timing, leg, reserved_final_stacks, separation):
    side = instance.cranes_by_id[leg.crane_id].side
    allowed = (
        range(1, instance.layout.handshake_bay + 1)
        if side is CraneSide.SEASIDE
        else range(
            instance.layout.handshake_bay + separation,
            instance.layout.last_work_bay + 1,
        )
    )
    _append_direct_job(
        instance,
        state,
        timing,
        leg.crane_id,
        leg.job,
        allowed,
        reserved_final_stacks,
    )


def _execute_donor(
    instance,
    state,
    timing,
    leg,
    transfer,
    reserved_final_stacks,
    separation,
):
    side = instance.cranes_by_id[leg.crane_id].side
    h_bay = instance.layout.handshake_bay
    allowed = (
        range(1, h_bay + 1)
        if side is CraneSide.SEASIDE
        else range(h_bay + separation, instance.layout.last_work_bay + 1)
    )
    state.crane_times[leg.crane_id] = max(
        state.crane_times[leg.crane_id], leg.job.ready_time
    )
    _prepare_pickup(
        instance,
        state,
        timing,
        leg.crane_id,
        leg.job,
        allowed,
        reserved_final_stacks,
    )
    _append_move(
        state,
        timing,
        leg.crane_id,
        OperationType.MOVE_LOADED,
        transfer.position,
        job_id=leg.job.id,
    )
    _append_handling(
        state,
        leg.crane_id,
        OperationType.HANDOVER_DROP,
        timing.drop_seconds(),
        job_id=leg.job.id,
        transfer_slot_id=transfer.id,
        purpose=OperationPurpose.HANDOVER,
    )
    state.container_statuses[leg.job.container_id] = (
        ContainerStatus.AT_TRANSFER_SLOT
    )
    retreat_bay = (
        h_bay - separation
        if side is CraneSide.SEASIDE
        else h_bay + separation
    )
    _append_move(
        state,
        timing,
        leg.crane_id,
        OperationType.MOVE_EMPTY,
        Position(retreat_bay, transfer.position.row),
    )


def _execute_receiver(instance, state, timing, leg, transfer, drop_time, separation):
    staging = _staging_position(instance, leg.crane_id, transfer, separation)
    _append_move(state, timing, leg.crane_id, OperationType.MOVE_EMPTY, staging)
    state.crane_times[leg.crane_id] = max(
        state.crane_times[leg.crane_id], drop_time
    )
    _append_move(
        state,
        timing,
        leg.crane_id,
        OperationType.MOVE_EMPTY,
        transfer.position,
    )
    _append_handling(
        state,
        leg.crane_id,
        OperationType.HANDOVER_PICKUP,
        timing.pickup_seconds(),
        job_id=leg.job.id,
        transfer_slot_id=transfer.id,
        purpose=OperationPurpose.HANDOVER,
    )
    state.container_statuses[leg.job.container_id] = ContainerStatus.ON_CRANE
    _append_move(
        state,
        timing,
        leg.crane_id,
        OperationType.MOVE_LOADED,
        staging,
        job_id=leg.job.id,
    )
    _append_move(
        state,
        timing,
        leg.crane_id,
        OperationType.MOVE_LOADED,
        leg.job.destination,
        job_id=leg.job.id,
    )
    _append_handling(
        state,
        leg.crane_id,
        OperationType.FINAL_DROP,
        timing.drop_seconds(leg.job.final_slot),
        job_id=leg.job.id,
    )
    _finish_primary_job(state, leg.job)


def _staging_position(instance, crane_id, transfer, separation):
    side = instance.cranes_by_id[crane_id].side
    bay = (
        instance.layout.handshake_bay - separation
        if side is CraneSide.SEASIDE
        else instance.layout.handshake_bay + separation
    )
    return Position(bay, transfer.position.row)


def _request_leg(leg, transfer):
    if leg.phase is MovementPhase.LOCAL:
        origin, destination = leg.job.origin, leg.job.destination
    elif leg.phase is MovementPhase.DONOR:
        origin, destination = leg.job.origin, transfer.position
    else:
        origin, destination = transfer.position, leg.job.destination
    return RequestLeg(
        movement_table_rank=leg.rank,
        request_block_id=leg.job.id,
        job_id=leg.job.id,
        crane_id=leg.crane_id,
        phase=leg.phase,
        origin_bay=origin.bay,
        destination_bay=destination.bay,
    )
