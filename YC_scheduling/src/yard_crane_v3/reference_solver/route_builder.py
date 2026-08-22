"""Build one conservative serial schedule from explicit route decisions."""

from __future__ import annotations

from ..model import CraneSide, StackKey, StaticSchedulingInstance
from ..planners.any_bay.scheduler import (
    _append_any_handover_job,
    _direct_reshuffle_bays,
    _slot_can_split_job,
)
from ..planners.common import PlannerInfeasibleError
from ..planners.handshake_area.scheduler import (
    _append_direct_job,
    _initial_state,
    _return_cranes_to_outer_bays,
    _synchronize,
)
from ..policy import CooperationPolicy, constraints_for
from ..schedule import CandidateSchedule
from ..timing import TimeModel
from ..validator import validate_schedule
from .routes import RouteKind, RouteMode, allowed_route_modes


def build_explicit_route_schedule(
    instance: StaticSchedulingInstance,
    policy: CooperationPolicy,
    ordered_job_ids: tuple[str, ...],
    route_modes: tuple[RouteMode, ...],
) -> CandidateSchedule:
    """Execute one selected route per job in protected serial phases."""

    if len(ordered_job_ids) != len(instance.jobs):
        raise ValueError("ordered_job_ids must contain every job exactly once")
    if set(ordered_job_ids) != set(instance.jobs_by_id):
        raise ValueError("ordered_job_ids is not an exact job permutation")
    modes_by_job = {mode.job_id: mode for mode in route_modes}
    if len(modes_by_job) != len(route_modes) or set(modes_by_job) != set(ordered_job_ids):
        raise ValueError("route_modes must select exactly one mode per job")

    for job_id, selected in modes_by_job.items():
        allowed = allowed_route_modes(instance, policy, instance.jobs_by_id[job_id])
        if selected not in allowed:
            raise ValueError(
                f"route {selected.label} is forbidden for {job_id}/{policy.value}"
            )

    timing = TimeModel(instance.motion)
    state = _initial_state(instance)
    cranes = {crane.side: crane for crane in instance.cranes}
    sea = cranes[CraneSide.SEASIDE]
    land = cranes[CraneSide.LANDSIDE]
    transfer_points = constraints_for(instance, policy).transfer_points_by_id
    reserved_final_stacks: set[StackKey] = {
        job.final_slot.stack_key
        for job in instance.jobs
        if job.final_slot is not None
    }

    for job_id in ordered_job_ids:
        job = instance.jobs_by_id[job_id]
        mode = modes_by_job[job_id]
        _return_cranes_to_outer_bays(instance, state, timing)
        _synchronize(state)
        if mode.kind is RouteKind.DIRECT:
            crane_id = (
                sea.id
                if mode.direct_crane_side is CraneSide.SEASIDE
                else land.id
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
            transfer = transfer_points[mode.transfer_slot_id]
            if not _slot_can_split_job(instance, job, transfer):
                raise PlannerInfeasibleError(
                    f"slot {transfer.id!r} cannot split job {job.id!r}"
                )
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
        _return_cranes_to_outer_bays(instance, state, timing)

    schedule = CandidateSchedule(
        instance.instance_id,
        policy,
        tuple(state.operations),
    )
    validation = validate_schedule(instance, constraints_for(instance, policy), schedule)
    if not validation.valid:
        details = "; ".join(
            f"{issue.code}: {issue.message}" for issue in validation.issues
        )
        raise PlannerInfeasibleError(
            f"explicit route schedule failed validation: {details}"
        )
    return schedule
