"""Pipeline candidate for the designated handshake bay."""

from __future__ import annotations

from ...model import CraneSide, Job, StaticSchedulingInstance
from ...policy import CooperationPolicy
from ...schedule import CandidateSchedule
from ...timing import TimeModel
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
