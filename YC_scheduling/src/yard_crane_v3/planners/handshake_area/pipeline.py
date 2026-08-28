"""Pipeline candidate for the designated handshake bay."""

from __future__ import annotations

from ...model import (
    ContainerStatus,
    CraneSide,
    Job,
    StackKey,
    StaticSchedulingInstance,
)
from ...policy import CooperationPolicy
from ...schedule import CandidateSchedule
from ...timing import TimeModel
from ..common import PlannerInfeasibleError, append_blocker_reshuffles
from ..pipeline import (
    PipelineTimingResult,
    repair_pipeline_seed,
    retreat_from_transfer_boundary,
)
from .scheduler import (
    _append_direct_job,
    _append_handover_job,
    _append_move,
    _initial_state,
    _integer_separation,
)
from ..no_sharing import JobRegion, classify_job


def build_handshake_pipeline_schedule(
    instance: StaticSchedulingInstance,
    *,
    max_repair_nodes: int = 2000,
    split_strategy: str = "donor_leg",
    slot_heuristic: str = "distance",
    jobs: tuple[Job, ...] | None = None,
    pre_reshuffle_idle: bool = False,
) -> PipelineTimingResult:
    """Overlap fixed donor/receiver sequences without outer-bay returns."""

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
        raise ValueError("handshake pipeline requires an enabled H slot")

    for job in jobs or instance.jobs:
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
            if pre_reshuffle_idle:
                _append_idle_receiver_reshuffle(
                    instance,
                    state,
                    timing,
                    job,
                    sea.id,
                    land.id,
                    separation,
                    tuple(jobs or instance.jobs),
                    reserved_final_stacks,
                )
            _append_handover_job(
                instance,
                state,
                timing,
                job,
                sea.id,
                land.id,
                transfer_slots,
                reserved_final_stacks,
                synchronize_receiver=False,
                split_strategy=split_strategy,
                slot_heuristic=slot_heuristic,
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

    seed = CandidateSchedule(
        instance.instance_id,
        CooperationPolicy.HANDSHAKE_AREA,
        tuple(state.operations),
    )
    return repair_pipeline_seed(
        instance,
        seed,
        max_nodes=max_repair_nodes,
    )


def _append_idle_receiver_reshuffle(
    instance: StaticSchedulingInstance,
    state,
    timing: TimeModel,
    active_job: Job,
    sea_id: str,
    land_id: str,
    separation: int,
    jobs: tuple[Job, ...],
    reserved_final_stacks: set[StackKey],
) -> None:
    role = _handover_role(instance, active_job, sea_id, land_id, separation)
    if role is None:
        return
    donor_id, receiver_id, receiver_bays = role
    candidate = _future_blocked_job_for_crane(
        state,
        jobs,
        receiver_bays,
        active_job.id,
    )
    if candidate is None:
        return
    before = len(state.operations)
    try:
        append_blocker_reshuffles(
            instance,
            state,
            timing,
            receiver_id,
            candidate.container_id,
            receiver_bays,
            reserved_final_stacks,
        )
    except PlannerInfeasibleError:
        return
    if len(state.operations) == before:
        return
    state.crane_times[donor_id] = max(
        state.crane_times[donor_id],
        state.crane_times[receiver_id],
    )


def _handover_role(
    instance: StaticSchedulingInstance,
    job: Job,
    sea_id: str,
    land_id: str,
    separation: int,
) -> tuple[str, str, range] | None:
    h_bay = instance.layout.handshake_bay
    if job.origin.bay <= h_bay and job.destination.bay >= h_bay + separation:
        return (
            sea_id,
            land_id,
            range(h_bay + separation, instance.layout.last_work_bay + 1),
        )
    if job.origin.bay >= h_bay + separation and job.destination.bay <= h_bay:
        return (land_id, sea_id, range(1, h_bay + 1))
    return None


def _future_blocked_job_for_crane(
    state,
    jobs: tuple[Job, ...],
    allowed_bays: range,
    active_job_id: str,
) -> Job | None:
    allowed = set(allowed_bays)
    active_seen = False
    for job in jobs:
        if job.id == active_job_id:
            active_seen = True
            continue
        if not active_seen:
            continue
        source_slot = state.container_slots.get(job.container_id)
        if (
            state.container_statuses.get(job.container_id)
            is not ContainerStatus.IN_STACK
            or source_slot is None
            or source_slot.bay not in allowed
            or not _has_blocker(state, job.container_id)
        ):
            continue
        return job
    return None


def _has_blocker(state, container_id: str) -> bool:
    source_slot = state.container_slots.get(container_id)
    if source_slot is None:
        return False
    stack = state.stacks.get(source_slot.stack_key)
    return bool(stack and container_id in stack and stack[-1] != container_id)
