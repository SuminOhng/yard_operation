"""Adapted 2017 FCFS, nearest-neighbor, and 2-opt handshake heuristics."""

from __future__ import annotations

import random

from ...model import (
    CraneSide,
    Job,
    StackKey,
    StaticSchedulingInstance,
)
from ...policy import CooperationPolicy
from ...schedule import CandidateSchedule
from ...timing import TimeModel
from ..common import PlannerInfeasibleError
from ..handshake_area.scheduler import (
    _append_direct_job,
    _append_handover_job,
    _append_move,
    _initial_state,
    _integer_separation,
)
from ..no_sharing import JobRegion, classify_job
from ..pipeline import retreat_from_transfer_boundary
from .ordering import (
    Handshake2017CandidateEvaluation,
    HandshakeStorageRule,
    SchedulingHeuristic,
    _choose_transfer_slot,
    _donor_side,
    _fcfs_order,
    _nearest_neighbor_order,
)
from .paper_timing import (
    MovementPhase,
    MovementTableEntry,
    RequestLeg,
    SchedulingProfile,
    repair_with_current_job_priority,
)


def build_handshake_area_2nd_schedule(
    instance: StaticSchedulingInstance,
    policy: CooperationPolicy = CooperationPolicy.HANDSHAKE_AREA,
    *,
    two_opt_iterations: int = 1000,
    random_seed: int = 2017,
    max_repair_nodes: int = 2000,
    profile: SchedulingProfile = SchedulingProfile.CURRENT_YARD,
    max_bypass_depth: int = 3,
) -> CandidateSchedule:
    """Return the best valid 2017-style handshake candidate."""

    if policy is not CooperationPolicy.HANDSHAKE_AREA:
        raise ValueError("the second handshake scheduler accepts HANDSHAKE_AREA only")

    evaluations = evaluate_handshake_area_2nd_candidates(
        instance,
        two_opt_iterations=two_opt_iterations,
        random_seed=random_seed,
        max_repair_nodes=max_repair_nodes,
        profile=profile,
        max_bypass_depth=max_bypass_depth,
    )
    valid = tuple(item for item in evaluations if item.valid)
    if not valid:
        details = "; ".join(
            f"{item.label}: {item.error}" for item in evaluations if item.error
        )
        raise PlannerInfeasibleError(
            "2017 handshake heuristic found no valid schedule"
            + (f": {details}" if details else "")
        )
    selected = min(
        valid,
        key=lambda item: (
            item.makespan,
            item.handover_count,
            len(item.schedule.operations) if item.schedule is not None else 0,
            item.label,
        ),
    )
    if selected.schedule is None:
        raise AssertionError("valid candidate has no schedule")
    return selected.schedule


def evaluate_handshake_area_2nd_candidates(
    instance: StaticSchedulingInstance,
    *,
    two_opt_iterations: int = 1000,
    random_seed: int = 2017,
    max_repair_nodes: int = 2000,
    profile: SchedulingProfile = SchedulingProfile.CURRENT_YARD,
    max_bypass_depth: int = 3,
) -> tuple[Handshake2017CandidateEvaluation, ...]:
    """Evaluate FCFS, NN, and 2-opt for both handshake storage rules."""

    if two_opt_iterations < 0:
        raise ValueError("two_opt_iterations must be nonnegative")
    if max_repair_nodes < 1:
        raise ValueError("max_repair_nodes must be positive")
    if max_bypass_depth < 0:
        raise ValueError("max_bypass_depth must be nonnegative")

    if profile is SchedulingProfile.DYNAMIC_LEG_DISPATCH:
        baseline = evaluate_handshake_area_2nd_candidates(
            instance,
            two_opt_iterations=two_opt_iterations,
            random_seed=random_seed,
            max_repair_nodes=max_repair_nodes,
            profile=SchedulingProfile.PAPER_2017,
        )
        from .dynamic_dispatch import evaluate_dynamic_dispatch_candidate

        return tuple(
            evaluate_dynamic_dispatch_candidate(
                instance,
                candidate,
                tuple(SchedulingHeuristic)[index % 3],
                tuple(HandshakeStorageRule)[index // 3],
                max_repair_nodes=max_repair_nodes,
                lookahead=max_bypass_depth,
            )
            for index, candidate in enumerate(baseline)
        )

    timing = TimeModel(instance.motion)
    evaluations: list[Handshake2017CandidateEvaluation] = []
    fcfs_order = _fcfs_order(instance, profile)

    for storage_rule in HandshakeStorageRule:
        fcfs = _evaluate_order(
            instance,
            SchedulingHeuristic.FCFS,
            storage_rule,
            fcfs_order,
            max_repair_nodes=max_repair_nodes,
            profile=profile,
        )
        evaluations.append(fcfs)

        nn_order = _nearest_neighbor_order(instance, timing, storage_rule, profile)
        evaluations.append(
            _evaluate_order(
                instance,
                SchedulingHeuristic.NN,
                storage_rule,
                nn_order,
                max_repair_nodes=max_repair_nodes,
                profile=profile,
            )
        )

        evaluations.append(
            _two_opt(
                instance,
                storage_rule,
                fcfs_order,
                initial=fcfs,
                iterations=two_opt_iterations,
                random_seed=random_seed,
                max_repair_nodes=max_repair_nodes,
                profile=profile,
            )
        )

    return tuple(evaluations)


def _evaluate_order(
    instance: StaticSchedulingInstance,
    heuristic: SchedulingHeuristic,
    storage_rule: HandshakeStorageRule,
    jobs: tuple[Job, ...],
    *,
    max_repair_nodes: int,
    profile: SchedulingProfile,
) -> Handshake2017CandidateEvaluation:
    profile_label = (
        ""
        if profile is SchedulingProfile.CURRENT_YARD
        else f":{profile.value}"
    )
    label = (
        f"GHAREHGOZLI2017{profile_label}:{heuristic.value}:{storage_rule.value}"
    )
    try:
        timing_result = _build_schedule(
            instance,
            jobs,
            storage_rule,
            max_repair_nodes=max_repair_nodes,
            profile=profile,
        )
        schedule = timing_result.schedule
        validation = timing_result.validation
        if not validation.valid:
            details = "; ".join(
                f"{issue.code}: {issue.message}" for issue in validation.issues
            )
            return Handshake2017CandidateEvaluation(
                label,
                schedule,
                validation,
                details,
                profile=profile,
                job_order=tuple(job.id for job in jobs),
            )
        return Handshake2017CandidateEvaluation(
            label,
            schedule,
            validation,
            blocking_seconds=timing_result.blocking_seconds,
            conflict_repairs=timing_result.conflict_repairs,
            movement_table=timing_result.movement_table,
            wait_records=timing_result.wait_records,
            request_legs=timing_result.request_legs,
            profile=profile,
            job_order=tuple(job.id for job in jobs),
        )
    except (PlannerInfeasibleError, ValueError) as exc:
        return Handshake2017CandidateEvaluation(
            label,
            None,
            None,
            str(exc),
            profile=profile,
            job_order=tuple(job.id for job in jobs),
        )


def _build_schedule(
    instance: StaticSchedulingInstance,
    jobs: tuple[Job, ...],
    storage_rule: HandshakeStorageRule,
    *,
    max_repair_nodes: int,
    profile: SchedulingProfile,
):
    timing = TimeModel(instance.motion)
    state = _initial_state(instance)
    cranes = {crane.side: crane for crane in instance.cranes}
    sea = cranes[CraneSide.SEASIDE]
    land = cranes[CraneSide.LANDSIDE]
    separation = _integer_separation(instance)
    reserved_final_stacks: set[StackKey] = {
        job.final_slot.stack_key for job in instance.jobs if job.final_slot is not None
    }
    movement_table: list[MovementTableEntry] = []
    request_legs: list[RequestLeg] = []

    for job in jobs:
        first_operation = len(state.operations)
        region = classify_job(instance, job)
        transfer = None
        if region is JobRegion.SEA_LOCAL:
            leg_specs = ((sea.id, MovementPhase.LOCAL, job.origin, job.destination),)
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
            leg_specs = ((land.id, MovementPhase.LOCAL, job.origin, job.destination),)
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
            transfer = _choose_transfer_slot(
                instance,
                timing,
                job,
                storage_rule,
                profile,
            )
            donor_side = _donor_side(instance, job)
            donor_id = cranes[donor_side].id
            receiver_side = (
                CraneSide.LANDSIDE
                if donor_side is CraneSide.SEASIDE
                else CraneSide.SEASIDE
            )
            receiver_id = cranes[receiver_side].id
            leg_specs = (
                (donor_id, MovementPhase.DONOR, job.origin, transfer.position),
                (
                    receiver_id,
                    MovementPhase.RECEIVER,
                    transfer.position,
                    job.destination,
                ),
            )
            _append_handover_job(
                instance,
                state,
                timing,
                job,
                sea.id,
                land.id,
                (transfer,),
                reserved_final_stacks,
                synchronize_receiver=False,
            )
        retreat_from_transfer_boundary(
            state,
            timing,
            sea.id,
            land.id,
            instance.layout.handshake_bay,
            separation,
            _append_move,
        )
        leg_by_phase: dict[MovementPhase, RequestLeg] = {}
        for crane_id, phase, origin, destination in leg_specs:
            leg = RequestLeg(
                movement_table_rank=len(request_legs),
                request_block_id=job.id,
                job_id=job.id,
                crane_id=crane_id,
                phase=phase,
                origin_bay=origin.bay,
                destination_bay=destination.bay,
            )
            request_legs.append(leg)
            leg_by_phase[phase] = leg
        for operation_index in range(first_operation, len(state.operations)):
            operation = state.operations[operation_index]
            if region is not JobRegion.CROSS_REGION:
                phase = MovementPhase.LOCAL
            elif operation.crane_id == donor_id:
                phase = MovementPhase.DONOR
            else:
                phase = MovementPhase.RECEIVER
            leg = leg_by_phase[phase]
            movement_table.append(
                MovementTableEntry(
                    operation_index=operation_index,
                    request_block_id=job.id,
                    movement_table_rank=leg.movement_table_rank,
                    phase=phase,
                )
            )

    seed = CandidateSchedule(
        instance.instance_id,
        CooperationPolicy.HANDSHAKE_AREA,
        tuple(state.operations),
    )
    timing_result = repair_with_current_job_priority(
        instance,
        seed,
        tuple(movement_table),
        tuple(request_legs),
        max_repairs=max_repair_nodes,
    )
    return timing_result


def _two_opt(
    instance: StaticSchedulingInstance,
    storage_rule: HandshakeStorageRule,
    initial_order: tuple[Job, ...],
    *,
    initial: Handshake2017CandidateEvaluation,
    iterations: int,
    random_seed: int,
    max_repair_nodes: int,
    profile: SchedulingProfile,
) -> Handshake2017CandidateEvaluation:
    profile_label = (
        ""
        if profile is SchedulingProfile.CURRENT_YARD
        else f":{profile.value}"
    )
    label = (
        f"GHAREHGOZLI2017{profile_label}:"
        f"{SchedulingHeuristic.TWO_OPT.value}:{storage_rule.value}"
    )
    if not initial.valid or initial.schedule is None:
        return Handshake2017CandidateEvaluation(
            label,
            None,
            None,
            "FCFS initial solution is invalid",
            profile=profile,
            job_order=tuple(job.id for job in initial_order),
        )

    best_order = initial_order
    best_schedule = initial.schedule
    best_validation = initial.validation
    best_makespan = initial.makespan
    best_blocking = initial.blocking_seconds
    best_repairs = initial.conflict_repairs
    best_movement_table = initial.movement_table
    best_wait_records = initial.wait_records
    best_request_legs = initial.request_legs
    if best_validation is None or best_makespan is None:
        raise AssertionError("valid FCFS candidate lacks validation")

    rng = random.Random(random_seed)
    for _ in range(iterations):
        if len(best_order) < 2:
            break
        left, right = rng.sample(range(len(best_order)), 2)
        candidate_order = list(best_order)
        candidate_order[left], candidate_order[right] = (
            candidate_order[right],
            candidate_order[left],
        )
        candidate = _evaluate_order(
            instance,
            SchedulingHeuristic.TWO_OPT,
            storage_rule,
            tuple(candidate_order),
            max_repair_nodes=max_repair_nodes,
            profile=profile,
        )
        if (
            candidate.valid
            and candidate.makespan is not None
            and candidate.makespan < best_makespan
        ):
            best_order = tuple(candidate_order)
            best_schedule = candidate.schedule
            best_validation = candidate.validation
            best_makespan = candidate.makespan
            best_blocking = candidate.blocking_seconds
            best_repairs = candidate.conflict_repairs
            best_movement_table = candidate.movement_table
            best_wait_records = candidate.wait_records
            best_request_legs = candidate.request_legs

    return Handshake2017CandidateEvaluation(
        label,
        best_schedule,
        best_validation,
        blocking_seconds=best_blocking,
        conflict_repairs=best_repairs,
        movement_table=best_movement_table,
        wait_records=best_wait_records,
        request_legs=best_request_legs,
        profile=profile,
        job_order=tuple(job.id for job in best_order),
    )
