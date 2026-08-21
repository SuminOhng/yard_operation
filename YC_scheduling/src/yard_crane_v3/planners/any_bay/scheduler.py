"""Virtual stack-backed per-job ANY_BAY handover planner."""

from __future__ import annotations

from ...model import (
    CraneSide,
    Job,
    Position,
    Slot,
    StackKey,
    StaticSchedulingInstance,
    TransferSlotKind,
    TransferSlotSpec,
)
from ...policy import CooperationPolicy, constraints_for
from ...schedule import CandidateSchedule, OperationPurpose, OperationType
from ...timing import TimeModel
from ...validator import validate_schedule
from ..common import PlannerCandidateEvaluation, PlannerInfeasibleError
from ..handshake_area.scheduler import (
    _append_direct_job,
    _append_handling,
    _append_move,
    _finish_primary_job,
    _initial_state,
    _integer_separation,
    _prepare_pickup,
    _synchronize,
)
from ..pipeline import PipelineTimingResult, repair_pipeline_seed, retreat_from_transfer_boundary
from ..handshake_area import build_handshake_area_schedule
from ..no_sharing import JobRegion, classify_job


def build_any_bay_schedule(
    instance: StaticSchedulingInstance,
    policy: CooperationPolicy = CooperationPolicy.ANY_BAY,
) -> CandidateSchedule:
    """Return best public ANY_BAY schedule from H fallback and per-job search."""

    if policy is not CooperationPolicy.ANY_BAY:
        raise ValueError("the any-bay scheduler accepts ANY_BAY only")
    return _select_best_valid_schedule(
        evaluate_any_bay_candidates(instance),
        "any-bay planner found no valid schedule",
    )


def evaluate_any_bay_candidates(
    instance: StaticSchedulingInstance,
) -> tuple[PlannerCandidateEvaluation, ...]:
    candidates: list[PlannerCandidateEvaluation] = []
    try:
        handshake_schedule = build_handshake_area_schedule(instance)
        handshake_schedule = CandidateSchedule(
            instance.instance_id,
            CooperationPolicy.ANY_BAY,
            handshake_schedule.operations,
        )
        handshake_validation = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.ANY_BAY),
            handshake_schedule,
        )
        candidates.append(
            PlannerCandidateEvaluation(
                "HANDSHAKE_FALLBACK",
                handshake_schedule,
                handshake_validation,
            )
        )
    except (PlannerInfeasibleError, ValueError) as exc:
        candidates.append(
            PlannerCandidateEvaluation("HANDSHAKE_FALLBACK", None, None, str(exc))
        )
    candidates.extend(evaluate_per_job_transfer_test_candidates(instance))
    return tuple(candidates)


def build_per_job_transfer_test_schedule(
    instance: StaticSchedulingInstance,
    policy: CooperationPolicy = CooperationPolicy.ANY_BAY,
) -> CandidateSchedule:
    """Return best schedule from a small per-job transfer-point local search."""

    if policy is not CooperationPolicy.ANY_BAY:
        raise ValueError("the per-job-transfer-test scheduler accepts ANY_BAY only")

    candidates = tuple(
        item for item in evaluate_per_job_transfer_test_candidates(instance) if item.valid
    )
    return _select_best_valid_schedule(
        candidates,
        "per-job-transfer-test planner found no valid schedule",
    )


def _select_best_valid_schedule(
    evaluations: tuple[PlannerCandidateEvaluation, ...],
    infeasible_message: str,
) -> CandidateSchedule:
    candidates = tuple(item for item in evaluations if item.valid)
    if not candidates:
        raise PlannerInfeasibleError(infeasible_message)
    selected = min(candidates, key=_candidate_sort_key)
    if selected.schedule is None:
        raise AssertionError("valid candidate has no schedule")
    return selected.schedule


def _candidate_sort_key(
    evaluation: PlannerCandidateEvaluation,
) -> tuple[float | None, int | None, int, str]:
    return (
        evaluation.makespan,
        evaluation.handover_count,
        len(evaluation.schedule.operations) if evaluation.schedule else 0,
        evaluation.label,
    )


def evaluate_per_job_transfer_test_candidates(
    instance: StaticSchedulingInstance,
    *,
    top_k_per_job: int = 2,
    max_passes: int = 1,
    max_repair_nodes: int = 800,
) -> tuple[PlannerCandidateEvaluation, ...]:
    """Greedy per-job transfer assignment with bounded one-change local search."""

    base = _best_all_bay_assignment(
        instance,
        max_repair_nodes=max_repair_nodes,
    )
    choices = dict(base[0])
    current = base[1]
    candidates = [_evaluate_pipeline_result(instance, "PER_JOB_TRANSFER:seed", current)]
    alternatives = _job_transfer_alternatives(
        instance,
        choices,
        top_k_per_job=top_k_per_job,
    )

    improved = True
    passes = 0
    while improved and passes < max_passes:
        improved = False
        passes += 1
        for job in instance.jobs:
            job_alternatives = alternatives.get(job.id, ())
            if not job_alternatives:
                continue
            best_choice = choices.get(job.id)
            best_result = current
            best_evaluation = _evaluate_pipeline_result(
                instance,
                f"PER_JOB_TRANSFER:pass{passes}:{job.id}:keep",
                current,
            )
            for transfer in job_alternatives:
                if best_choice is not None and transfer.id == best_choice.id:
                    continue
                trial_choices = dict(choices)
                trial_choices[job.id] = transfer
                try:
                    result = _build_choice_pipeline(
                        instance,
                        trial_choices,
                        max_repair_nodes=max_repair_nodes,
                    )
                    evaluation = _evaluate_pipeline_result(
                        instance,
                        f"PER_JOB_TRANSFER:pass{passes}:{job.id}:{transfer.id}",
                        result,
                    )
                except (PlannerInfeasibleError, ValueError) as exc:
                    evaluation = PlannerCandidateEvaluation(
                        f"PER_JOB_TRANSFER:pass{passes}:{job.id}:{transfer.id}",
                        None,
                        None,
                        str(exc),
                    )
                candidates.append(evaluation)
                if (
                    evaluation.valid
                    and best_evaluation.makespan is not None
                    and evaluation.makespan is not None
                    and (
                        evaluation.makespan,
                        evaluation.handover_count,
                        len(evaluation.schedule.operations) if evaluation.schedule else 0,
                        evaluation.label,
                    )
                    < (
                        best_evaluation.makespan,
                        best_evaluation.handover_count,
                        len(best_evaluation.schedule.operations)
                        if best_evaluation.schedule
                        else 0,
                        best_evaluation.label,
                    )
                ):
                    best_choice = transfer
                    best_result = result
                    best_evaluation = evaluation
            if best_choice is not choices.get(job.id):
                choices[job.id] = best_choice
                current = best_result
                improved = True
    candidates.append(_evaluate_pipeline_result(instance, "PER_JOB_TRANSFER:final", current))
    return tuple(candidates)


def _best_all_bay_assignment(
    instance: StaticSchedulingInstance,
    *,
    max_repair_nodes: int,
) -> tuple[dict[str, TransferSlotSpec], PipelineTimingResult, int]:
    best_choices: dict[str, TransferSlotSpec] | None = None
    best_result: PipelineTimingResult | None = None
    best_bay: int | None = None
    for bay in instance.layout.working_bays:
        slots = _transfer_points_at_bay(
            instance,
            bay,
            transfer_kind=TransferSlotKind.VIRTUAL_STACK,
        )
        if not slots:
            continue
        choices = {
            job.id: transfer
            for job in instance.jobs
            if (transfer := _best_corridor_transfer(job, slots)) is not None
        }
        try:
            result = _build_choice_pipeline(
                instance,
                choices,
                max_repair_nodes=max_repair_nodes,
            )
        except (PlannerInfeasibleError, ValueError):
            continue
        validation = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.ANY_BAY),
            result.schedule,
        )
        if not validation.valid:
            continue
        if best_result is None or (
            validation.makespan,
            validation.handover_count,
            len(result.schedule.operations),
            bay,
        ) < (
            best_result.validation.makespan,
            best_result.validation.handover_count,
            len(best_result.schedule.operations),
            best_bay,
        ):
            best_choices = choices
            best_result = result
            best_bay = bay
    if best_choices is None or best_result is None or best_bay is None:
        raise PlannerInfeasibleError("no valid all-bay seed for per-job transfer search")
    return best_choices, best_result, best_bay


def _job_transfer_alternatives(
    instance: StaticSchedulingInstance,
    current_choices: dict[str, TransferSlotSpec],
    *,
    top_k_per_job: int,
) -> dict[str, tuple[TransferSlotSpec, ...]]:
    points = tuple(
        point
        for point in constraints_for(instance, CooperationPolicy.ANY_BAY).transfer_points
        if point.enabled and point.kind is TransferSlotKind.VIRTUAL_STACK
    )
    alternatives: dict[str, tuple[TransferSlotSpec, ...]] = {}
    for job in instance.jobs:
        feasible = [point for point in points if _job_crosses_transfer_bay(job, point.position.bay)]
        if not feasible:
            continue
        midpoint = (job.origin.bay + job.destination.bay) / 2.0
        ranked = sorted(
            feasible,
            key=lambda point: (
                abs(point.position.bay - midpoint),
                abs(point.position.row - job.origin.row)
                + abs(point.position.row - job.destination.row),
                point.position.bay,
                point.position.row,
                point.id,
            ),
        )
        selected = {point.id: point for point in ranked[:top_k_per_job]}
        current = current_choices.get(job.id)
        if current is not None:
            selected[current.id] = current
        alternatives[job.id] = tuple(selected.values())
    return alternatives


def _build_choice_pipeline(
    instance: StaticSchedulingInstance,
    choices: dict[str, TransferSlotSpec],
    *,
    max_repair_nodes: int,
) -> PipelineTimingResult:
    points = constraints_for(instance, CooperationPolicy.ANY_BAY).transfer_points
    if not points:
        raise PlannerInfeasibleError("ANY_BAY has no transfer points")

    timing = TimeModel(instance.motion)
    state = _initial_state(instance)
    cranes = {crane.side: crane for crane in instance.cranes}
    sea = cranes[CraneSide.SEASIDE]
    land = cranes[CraneSide.LANDSIDE]
    separation = _integer_separation(instance)
    reference_slot = points[0]
    reserved_final_stacks = {
        job.final_slot.stack_key
        for job in instance.jobs
        if job.final_slot is not None
    }

    for job in instance.jobs:
        _synchronize(state)
        transfer = choices.get(job.id)
        if transfer is None:
            crane_id = _direct_crane_for_job(
                instance,
                state,
                timing,
                job,
                sea.id,
                land.id,
                reference_slot,
            )
            _append_direct_job(
                instance,
                state,
                timing,
                crane_id,
                job,
                _direct_reshuffle_bays(instance, crane_id, sea.id),
                reserved_final_stacks,
            )
        else:
            _append_any_handover_job(
                instance,
                state,
                timing,
                job,
                sea.id,
                land.id,
                transfer,
                reserved_final_stacks,
            )
            retreat_from_transfer_boundary(
                state,
                timing,
                sea.id,
                land.id,
                transfer.position.bay,
                separation,
                _append_move,
            )

    seed = CandidateSchedule(
        instance.instance_id,
        CooperationPolicy.ANY_BAY,
        tuple(state.operations),
    )
    return repair_pipeline_seed(instance, seed, max_nodes=max_repair_nodes)


def _transfer_points_at_bay(
    instance: StaticSchedulingInstance,
    bay: int,
    *,
    transfer_kind: TransferSlotKind | None,
) -> tuple[TransferSlotSpec, ...]:
    return tuple(
        sorted(
            (
                point
                for point in constraints_for(instance, CooperationPolicy.ANY_BAY).transfer_points
                if (transfer_kind is None or point.kind is transfer_kind)
                and point.enabled
                and point.position.bay == bay
            ),
            key=lambda point: (point.position.row, point.id),
        )
    )


def _best_corridor_transfer(
    job: Job,
    slots: tuple[TransferSlotSpec, ...],
) -> TransferSlotSpec | None:
    candidates = tuple(slot for slot in slots if _job_crosses_transfer_bay(job, slot.position.bay))
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda slot: (
            abs(slot.position.row - job.origin.row)
            + abs(slot.position.row - job.destination.row),
            slot.position.row,
            slot.id,
        ),
    )


def _job_crosses_transfer_bay(job: Job, bay: int) -> bool:
    if job.origin.bay == job.destination.bay:
        return False
    return min(job.origin.bay, job.destination.bay) <= bay <= max(
        job.origin.bay,
        job.destination.bay,
    )


def _slot_can_split_job(
    instance: StaticSchedulingInstance,
    job: Job,
    slot: TransferSlotSpec,
) -> bool:
    if not slot.enabled or not _job_crosses_transfer_bay(job, slot.position.bay):
        return False
    separation = _integer_separation(instance)
    bay = slot.position.bay
    return (
        instance.layout.is_work_bay(bay)
        and bay - separation >= instance.layout.seaside_parking_bay
        and bay + separation <= instance.layout.landside_parking_bay
    )


def _append_any_handover_job(
    instance: StaticSchedulingInstance,
    state,
    timing: TimeModel,
    job: Job,
    sea_id: str,
    land_id: str,
    transfer: TransferSlotSpec,
    reserved_final_stacks: set[StackKey],
) -> None:
    separation = _integer_separation(instance)
    transfer_bay = transfer.position.bay
    if job.origin.bay < job.destination.bay:
        donor_id, receiver_id = sea_id, land_id
        donor_retreat_bay = (
            min(transfer_bay, job.destination.bay) - separation
        )
    elif job.origin.bay > job.destination.bay:
        donor_id, receiver_id = land_id, sea_id
        donor_retreat_bay = (
            max(transfer_bay, job.destination.bay) + separation
        )
    else:
        raise PlannerInfeasibleError(
            f"job {job.id!r} has no bay movement to split"
        )
    reshuffle_bays = range(
        instance.layout.first_work_bay,
        instance.layout.last_work_bay + 1,
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
        _handover_handling_seconds(
            instance,
            state,
            timing,
            transfer,
        )
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
    _append_move(
        state,
        timing,
        donor_id,
        OperationType.MOVE_EMPTY,
        Position(donor_retreat_bay, transfer.position.row),
    )
    _synchronize(state)
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
    state,
    timing: TimeModel,
    transfer: TransferSlotSpec,
) -> tuple[float, float]:
    if transfer.kind is TransferSlotKind.FIXED_BUFFER:
        return timing.drop_seconds(), timing.pickup_seconds()

    stack_key = StackKey(
        instance.layout.block_id,
        transfer.position.bay,
        transfer.position.row,
    )
    stack = state.stacks[stack_key]
    height = len(stack)
    tier = height + 1
    capacity = instance.yard.stacks_by_key[stack_key].capacity
    if tier > capacity:
        raise PlannerInfeasibleError(
            f"virtual transfer point {transfer.id!r} has no free stack tier"
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


def _direct_crane_for_job(
    instance: StaticSchedulingInstance,
    state,
    timing: TimeModel,
    job: Job,
    sea_id: str,
    land_id: str,
    reference_slot: TransferSlotSpec | None,
) -> str:
    if reference_slot is not None:
        if max(job.origin.bay, job.destination.bay) <= reference_slot.position.bay:
            return sea_id
        if min(job.origin.bay, job.destination.bay) >= reference_slot.position.bay:
            return land_id
    region = classify_job(instance, job)
    if region is JobRegion.SEA_LOCAL:
        return sea_id
    if region is JobRegion.LAND_LOCAL:
        return land_id
    endpoints = {job.origin.bay, job.destination.bay}
    if 0 in endpoints:
        return sea_id
    if instance.layout.landside_parking_bay in endpoints:
        return land_id
    sea_cost = timing.travel_seconds(state.crane_positions[sea_id], job.origin)
    land_cost = timing.travel_seconds(
        state.crane_positions[land_id], job.origin
    )
    return sea_id if sea_cost <= land_cost else land_id


def _direct_reshuffle_bays(
    instance: StaticSchedulingInstance,
    crane_id: str,
    sea_id: str,
) -> range:
    separation = _integer_separation(instance)
    if crane_id == sea_id:
        return range(1, instance.layout.bays + 2 - separation)
    return range(separation, instance.layout.last_work_bay + 1)


def _evaluate_pipeline_result(
    instance: StaticSchedulingInstance,
    label: str,
    result: PipelineTimingResult,
) -> PlannerCandidateEvaluation:
    validation = validate_schedule(
        instance,
        constraints_for(instance, CooperationPolicy.ANY_BAY),
        result.schedule,
    )
    if not validation.valid:
        details = "; ".join(
            f"{issue.code}: {issue.message}" for issue in validation.issues
        )
        return PlannerCandidateEvaluation(
            label,
            result.schedule,
            validation,
            f"{label} is invalid: {details}",
        )
    return PlannerCandidateEvaluation(label, result.schedule, validation)
