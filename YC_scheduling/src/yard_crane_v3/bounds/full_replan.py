"""Validated all-job replanning upper-bound calculation."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..comparison.runner import DEFAULT_POLICY_PLANNERS
from ..model import StaticSchedulingInstance, validate_instance
from ..planners import Planner
from ..policy import constraints_for
from ..schedule import CandidateSchedule
from ..validator import ValidationResult, validate_schedule
from .request import BoundCalculationRequest
from .result import BoundCalculationResult


@dataclass(frozen=True, slots=True)
class FullReplanCalculation:
    """Full-replan result and the artifacts that certify it."""

    request: BoundCalculationRequest
    result: BoundCalculationResult
    planner_name: str
    replan_instance: StaticSchedulingInstance | None = None
    schedule: CandidateSchedule | None = None
    validation: ValidationResult | None = None


def build_full_replan_instance(
    request: BoundCalculationRequest,
) -> StaticSchedulingInstance:
    """Expose all jobs while preventing new work before its decision time."""

    new_ids = set(request.new_job_ids)
    jobs = tuple(
        replace(
            job,
            release_time=max(job.release_time, request.decision_time),
        )
        if job.id in new_ids
        else job
        for job in request.instance.jobs
    )
    instance = replace(
        request.instance,
        instance_id=f"{request.instance.instance_id}__BOUND_FULL_REPLAN",
        jobs=jobs,
    )
    validate_instance(instance)
    return instance


def calculate_full_replan_upper_bound(
    request: BoundCalculationRequest,
    planner: Planner | None = None,
) -> FullReplanCalculation:
    """Plan all jobs together and accept only a validated makespan."""

    selected_planner = (
        DEFAULT_POLICY_PLANNERS[request.policy]
        if planner is None
        else planner
    )
    planner_name = getattr(
        selected_planner, "__name__", type(selected_planner).__name__
    )
    pending = BoundCalculationResult.pending(request)
    replan_instance: StaticSchedulingInstance | None = None
    schedule: CandidateSchedule | None = None
    validation: ValidationResult | None = None
    try:
        replan_instance = build_full_replan_instance(request)
        schedule = selected_planner(replan_instance, request.policy)
        validation = validate_schedule(
            replan_instance,
            constraints_for(replan_instance, request.policy),
            schedule,
        )
        if not validation.valid or validation.makespan is None:
            return _failed(
                request,
                pending,
                planner_name,
                "full-replan schedule failed physical validation",
                replan_instance,
                schedule,
                validation,
            )
        result = replace(
            pending,
            full_replan_upper_bound=validation.makespan,
            best_known_upper_bound=validation.makespan,
            upper_bound_validated=True,
            bound_provenance=(
                "new-job release times constrained by decision_time",
                "all-job replan validated on common physical model",
            ),
        )
        return FullReplanCalculation(
            request,
            result,
            planner_name,
            replan_instance,
            schedule,
            validation,
        )
    except Exception as exc:
        return _failed(
            request,
            pending,
            planner_name,
            f"{type(exc).__name__}: {exc}",
            replan_instance,
            schedule,
            validation,
        )


def _failed(
    request: BoundCalculationRequest,
    result: BoundCalculationResult,
    planner_name: str,
    error: str,
    replan_instance: StaticSchedulingInstance | None,
    schedule: CandidateSchedule | None,
    validation: ValidationResult | None,
) -> FullReplanCalculation:
    return FullReplanCalculation(
        request=request,
        result=replace(
            result,
            upper_bound_validated=False,
            error=error,
        ),
        planner_name=planner_name,
        replan_instance=replan_instance,
        schedule=schedule,
        validation=validation,
    )

