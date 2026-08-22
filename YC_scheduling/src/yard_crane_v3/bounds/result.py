"""Stable result shape filled progressively by later bound phases."""

from __future__ import annotations

from dataclasses import dataclass

from ..policy import CooperationPolicy
from .request import BoundCalculationRequest


@dataclass(frozen=True, slots=True)
class BoundCalculationResult:
    instance_id: str
    policy: CooperationPolicy
    existing_job_ids: tuple[str, ...]
    new_job_ids: tuple[str, ...]
    decision_time: float
    baseline_makespan: float | None = None
    baseline_operation_horizon: float | None = None
    strict_append_upper_bound: float | None = None
    full_replan_upper_bound: float | None = None
    best_known_upper_bound: float | None = None
    existing_jobs_lower_bound: float | None = None
    new_jobs_earliest_completion: float | None = None
    workload_lower_bound: float | None = None
    combined_lower_bound: float | None = None
    absolute_gap: float | None = None
    relative_gap: float | None = None
    makespan_extension: float | None = None
    append_valid: bool | None = None
    upper_bound_validated: bool = False
    lower_bound_certified: bool = False
    bound_provenance: tuple[str, ...] = ()
    error: str | None = None

    @classmethod
    def pending(
        cls,
        request: BoundCalculationRequest,
    ) -> "BoundCalculationResult":
        """Create the identity-only result used before calculations exist."""

        return cls(
            instance_id=request.instance.instance_id,
            policy=request.policy,
            existing_job_ids=request.existing_job_ids,
            new_job_ids=request.new_job_ids,
            decision_time=request.decision_time,
        )

