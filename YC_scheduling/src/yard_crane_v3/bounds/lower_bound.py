"""Certified analytical lower bounds for the static bound calculator."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..model import Job
from ..policy import constraints_for
from ..timing import TimeModel
from .request import BoundCalculationRequest
from .result import BoundCalculationResult


TOL = 1e-9


@dataclass(frozen=True, slots=True)
class JobLowerBoundComponent:
    """Per-job optimistic quantities used by the analytical bound."""

    job_id: str
    is_new: bool
    availability_time: float
    mandatory_work_seconds: float
    earliest_completion: float


@dataclass(frozen=True, slots=True)
class LowerBoundCalculation:
    """Calculated lower bound plus its per-job proof components."""

    request: BoundCalculationRequest
    result: BoundCalculationResult
    job_components: tuple[JobLowerBoundComponent, ...]
    active_crane_count: int


def calculate_lower_bound(
    request: BoundCalculationRequest,
    upper_bound_result: BoundCalculationResult | None = None,
) -> LowerBoundCalculation:
    """Calculate a safe LB and optionally its gap to a validated UB.

    The workload bound counts mandatory pickup, direct loaded travel, and
    final drop work, but deliberately ignores empty travel, interference,
    stacking, handovers, and reshuffles. The earliest-completion component
    also ignores travel so that pre-positioning cannot invalidate the bound.
    """

    if upper_bound_result is not None and (
        upper_bound_result.instance_id != request.instance.instance_id
        or upper_bound_result.policy is not request.policy
        or upper_bound_result.existing_job_ids != request.existing_job_ids
        or upper_bound_result.new_job_ids != request.new_job_ids
        or upper_bound_result.decision_time != request.decision_time
    ):
        raise ValueError("upper-bound result belongs to another request")

    timing = TimeModel(request.instance.motion)
    new_ids = set(request.new_job_ids)
    components = tuple(
        _job_component(job, job.id in new_ids, request, timing)
        for job in request.instance.jobs
    )
    active_crane_count = len(
        constraints_for(request.instance, request.policy).active_crane_ids
    )
    if active_crane_count <= 0:
        raise ValueError("lower bound requires at least one active crane")

    initial_time = request.instance.initial_state.current_time
    existing_components = tuple(
        component for component in components if not component.is_new
    )
    new_components = tuple(
        component for component in components if component.is_new
    )
    existing_workload = initial_time + sum(
        component.mandatory_work_seconds
        for component in existing_components
    ) / active_crane_count
    existing_earliest = max(
        component.earliest_completion for component in existing_components
    )
    existing_candidates = [existing_workload, existing_earliest]
    if request.certified_existing_lower_bound is not None:
        existing_candidates.append(request.certified_existing_lower_bound)
    existing_lower_bound = max(existing_candidates)

    new_earliest_completion = max(
        component.earliest_completion for component in new_components
    )
    workload_lower_bound = initial_time + sum(
        component.mandatory_work_seconds for component in components
    ) / active_crane_count
    combined_lower_bound = max(
        existing_lower_bound,
        new_earliest_completion,
        workload_lower_bound,
    )

    base = (
        BoundCalculationResult.pending(request)
        if upper_bound_result is None
        else upper_bound_result
    )
    best_upper_bound = base.best_known_upper_bound
    if (
        best_upper_bound is not None
        and combined_lower_bound > best_upper_bound + TOL
    ):
        result = replace(
            base,
            existing_jobs_lower_bound=existing_lower_bound,
            new_jobs_earliest_completion=new_earliest_completion,
            workload_lower_bound=workload_lower_bound,
            combined_lower_bound=combined_lower_bound,
            absolute_gap=None,
            relative_gap=None,
            lower_bound_certified=False,
            error=(
                "lower-bound contradiction: combined lower bound exceeds "
                "the validated upper bound"
            ),
        )
        return LowerBoundCalculation(
            request, result, components, active_crane_count
        )

    absolute_gap = (
        best_upper_bound - combined_lower_bound
        if best_upper_bound is not None
        else None
    )
    relative_gap = (
        absolute_gap / best_upper_bound
        if absolute_gap is not None and best_upper_bound > 0
        else 0.0 if absolute_gap == 0 else None
    )
    existing_provenance = (
        "existing-job LB includes the supplied certified lower bound"
        if request.certified_existing_lower_bound is not None
        else "existing-job LB uses analytical relaxations only"
    )
    provenance = base.bound_provenance + (
        existing_provenance,
        "new-job earliest completion ignores travel and interference",
        "workload LB divides mandatory crane work by active crane count",
        "combined LB is the maximum of independently valid lower bounds",
    )
    result = replace(
        base,
        existing_jobs_lower_bound=existing_lower_bound,
        new_jobs_earliest_completion=new_earliest_completion,
        workload_lower_bound=workload_lower_bound,
        combined_lower_bound=combined_lower_bound,
        absolute_gap=absolute_gap,
        relative_gap=relative_gap,
        lower_bound_certified=True,
        bound_provenance=provenance,
    )
    return LowerBoundCalculation(
        request, result, components, active_crane_count
    )


def _job_component(
    job: Job,
    is_new: bool,
    request: BoundCalculationRequest,
    timing: TimeModel,
) -> JobLowerBoundComponent:
    availability = max(
        job.ready_time,
        request.decision_time
        if is_new
        else request.instance.initial_state.current_time,
    )
    minimum_handling = timing.pickup_seconds() + timing.drop_seconds()
    mandatory_work = minimum_handling + timing.travel_seconds(
        job.origin, job.destination
    )
    return JobLowerBoundComponent(
        job_id=job.id,
        is_new=is_new,
        availability_time=availability,
        mandatory_work_seconds=mandatory_work,
        earliest_completion=availability + minimum_handling,
    )
