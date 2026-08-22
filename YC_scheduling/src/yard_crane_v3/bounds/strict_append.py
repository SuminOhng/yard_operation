"""Validated strict-append upper-bound calculation."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..comparison.runner import DEFAULT_POLICY_PLANNERS
from ..model import StaticSchedulingInstance
from ..planners import Planner
from ..policy import constraints_for
from ..schedule import CandidateSchedule
from ..validator import ValidationResult, validate_schedule
from .request import BoundCalculationRequest
from .residual import build_residual_instance
from .result import BoundCalculationResult
from .scenario import BoundScenario, derive_bound_scenario


@dataclass(frozen=True, slots=True)
class StrictAppendCalculation:
    """Numeric result plus every artifact needed to audit that result."""

    request: BoundCalculationRequest
    result: BoundCalculationResult
    planner_name: str
    scenario: BoundScenario | None = None
    existing_schedule: CandidateSchedule | None = None
    existing_validation: ValidationResult | None = None
    residual_instance: StaticSchedulingInstance | None = None
    new_schedule: CandidateSchedule | None = None
    new_validation: ValidationResult | None = None
    combined_schedule: CandidateSchedule | None = None
    combined_validation: ValidationResult | None = None


def calculate_strict_append_upper_bound(
    request: BoundCalculationRequest,
    planner: Planner | None = None,
) -> StrictAppendCalculation:
    """Keep the existing plan and schedule new work strictly after it.

    The returned value is accepted as an upper bound only when the combined
    schedule replays successfully against the original full instance.
    Planner failures are preserved in ``result.error`` instead of being
    mistaken for a numeric bound.
    """

    selected_planner = (
        DEFAULT_POLICY_PLANNERS[request.policy]
        if planner is None
        else planner
    )
    planner_name = getattr(
        selected_planner, "__name__", type(selected_planner).__name__
    )
    pending = BoundCalculationResult.pending(request)
    scenario: BoundScenario | None = None
    existing_schedule: CandidateSchedule | None = None
    existing_validation: ValidationResult | None = None
    residual_instance: StaticSchedulingInstance | None = None
    new_schedule: CandidateSchedule | None = None
    new_validation: ValidationResult | None = None
    combined_schedule: CandidateSchedule | None = None
    combined_validation: ValidationResult | None = None

    try:
        scenario = derive_bound_scenario(request)
        existing_schedule = selected_planner(
            scenario.existing_instance, request.policy
        )
        existing_validation = validate_schedule(
            scenario.existing_instance,
            constraints_for(scenario.existing_instance, request.policy),
            existing_schedule,
        )
        if not existing_validation.valid:
            return _failed(
                request,
                pending,
                planner_name,
                "existing schedule failed physical validation",
                scenario=scenario,
                existing_schedule=existing_schedule,
                existing_validation=existing_validation,
            )

        operation_horizon = max(
            (
                operation.end_time
                for operation in existing_schedule.operations
            ),
            default=scenario.existing_instance.initial_state.current_time,
        )
        continuation_time = max(operation_horizon, request.decision_time)
        residual_instance = build_residual_instance(
            request.instance,
            request.new_job_ids,
            existing_validation.simulation.final_state,
            continuation_time=continuation_time,
            instance_id=f"{request.instance.instance_id}__BOUND_APPEND_NEW",
        )
        new_schedule = selected_planner(residual_instance, request.policy)
        new_validation = validate_schedule(
            residual_instance,
            constraints_for(residual_instance, request.policy),
            new_schedule,
        )
        if not new_validation.valid:
            return _failed(
                request,
                replace(
                    pending,
                    baseline_makespan=existing_validation.makespan,
                    baseline_operation_horizon=operation_horizon,
                ),
                planner_name,
                "appended new-job schedule failed physical validation",
                scenario=scenario,
                existing_schedule=existing_schedule,
                existing_validation=existing_validation,
                residual_instance=residual_instance,
                new_schedule=new_schedule,
                new_validation=new_validation,
            )

        combined_schedule = CandidateSchedule(
            request.instance.instance_id,
            request.policy,
            existing_schedule.operations + new_schedule.operations,
        )
        combined_validation = validate_schedule(
            request.instance,
            constraints_for(request.instance, request.policy),
            combined_schedule,
        )
        if not combined_validation.valid:
            return _failed(
                request,
                replace(
                    pending,
                    baseline_makespan=existing_validation.makespan,
                    baseline_operation_horizon=operation_horizon,
                ),
                planner_name,
                "combined append schedule failed full-instance validation",
                scenario=scenario,
                existing_schedule=existing_schedule,
                existing_validation=existing_validation,
                residual_instance=residual_instance,
                new_schedule=new_schedule,
                new_validation=new_validation,
                combined_schedule=combined_schedule,
                combined_validation=combined_validation,
            )

        upper_bound = combined_validation.makespan
        baseline = existing_validation.makespan
        if upper_bound is None or baseline is None:
            raise RuntimeError("valid schedules must report makespan values")
        result = replace(
            pending,
            baseline_makespan=baseline,
            baseline_operation_horizon=operation_horizon,
            strict_append_upper_bound=upper_bound,
            best_known_upper_bound=upper_bound,
            makespan_extension=upper_bound - baseline,
            append_valid=True,
            upper_bound_validated=True,
            bound_provenance=(
                "existing schedule validated on existing-job subset",
                "new jobs planned from validated residual physical state",
                "combined schedule validated on original full instance",
            ),
        )
        return StrictAppendCalculation(
            request=request,
            result=result,
            planner_name=planner_name,
            scenario=scenario,
            existing_schedule=existing_schedule,
            existing_validation=existing_validation,
            residual_instance=residual_instance,
            new_schedule=new_schedule,
            new_validation=new_validation,
            combined_schedule=combined_schedule,
            combined_validation=combined_validation,
        )
    except Exception as exc:
        return _failed(
            request,
            pending,
            planner_name,
            f"{type(exc).__name__}: {exc}",
            scenario=scenario,
            existing_schedule=existing_schedule,
            existing_validation=existing_validation,
            residual_instance=residual_instance,
            new_schedule=new_schedule,
            new_validation=new_validation,
            combined_schedule=combined_schedule,
            combined_validation=combined_validation,
        )


def _failed(
    request: BoundCalculationRequest,
    result: BoundCalculationResult,
    planner_name: str,
    error: str,
    **artifacts,
) -> StrictAppendCalculation:
    return StrictAppendCalculation(
        request=request,
        result=replace(
            result,
            append_valid=False,
            upper_bound_validated=False,
            error=error,
        ),
        planner_name=planner_name,
        **artifacts,
    )

