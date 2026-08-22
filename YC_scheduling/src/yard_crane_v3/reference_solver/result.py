"""Typed exhaustive-reference result and its deliberately narrow certificate."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..policy import CooperationPolicy
from ..schedule import CandidateSchedule
from ..validator import ValidationResult
from .routes import RouteMode


class ReferenceOptimalityScope(str, Enum):
    """What the completed enumeration has actually proven."""

    JOB_ORDER_AND_CURRENT_PLANNER_CANDIDATES = (
        "JOB_ORDER_AND_CURRENT_PLANNER_CANDIDATES"
    )
    JOB_ORDER_AND_EXPLICIT_SERIAL_ROUTE_MODES = (
        "JOB_ORDER_AND_EXPLICIT_SERIAL_ROUTE_MODES"
    )
    JOB_ORDER_EXPLICIT_ROUTES_AND_POLICY_PLANNER = (
        "JOB_ORDER_EXPLICIT_ROUTES_AND_POLICY_PLANNER"
    )
    JOB_ORDER_ROUTES_POLICY_PLANNER_AND_LEFT_SHIFT = (
        "JOB_ORDER_ROUTES_POLICY_PLANNER_AND_LEFT_SHIFT"
    )


@dataclass(frozen=True, slots=True)
class ReferenceSearchResult:
    instance_id: str
    policy: CooperationPolicy
    job_count: int
    expected_permutation_count: int
    evaluated_permutation_count: int
    feasible_candidate_count: int
    infeasible_candidate_count: int
    best_job_order: tuple[str, ...]
    best_makespan: float
    best_schedule: CandidateSchedule
    best_validation: ValidationResult
    runtime_seconds: float
    failure_samples: tuple[str, ...]
    search_complete: bool = True
    optimal_within_scope: bool = True
    globally_optimal: bool = False
    optimality_scope: ReferenceOptimalityScope = (
        ReferenceOptimalityScope.JOB_ORDER_AND_CURRENT_PLANNER_CANDIDATES
    )


@dataclass(frozen=True, slots=True)
class ThreePolicyReferenceResult:
    instance_id: str
    records: tuple[ReferenceSearchResult, ...]

    @property
    def records_by_policy(
        self,
    ) -> dict[CooperationPolicy, ReferenceSearchResult]:
        return {record.policy: record for record in self.records}

    @property
    def nested_reference_bounds_hold(self) -> bool:
        records = self.records_by_policy
        tolerance = 1e-9
        return (
            records[CooperationPolicy.ANY_BAY].best_makespan
            <= records[CooperationPolicy.HANDSHAKE_AREA].best_makespan
            + tolerance
            and records[CooperationPolicy.HANDSHAKE_AREA].best_makespan
            <= records[CooperationPolicy.NO_SHARING].best_makespan
            + tolerance
        )


@dataclass(frozen=True, slots=True)
class RouteReferenceSearchResult:
    instance_id: str
    policy: CooperationPolicy
    job_count: int
    permutation_count: int
    planner_candidate_count: int
    explicit_route_candidate_count: int
    concurrent_candidate_count: int
    expected_candidate_count: int
    evaluated_candidate_count: int
    feasible_candidate_count: int
    infeasible_candidate_count: int
    best_job_order: tuple[str, ...]
    best_route_modes: tuple[RouteMode, ...]
    best_candidate_source: str
    best_crane_job_sequences: tuple[tuple[str, tuple[str, ...]], ...]
    best_makespan: float
    best_schedule: CandidateSchedule
    best_validation: ValidationResult
    runtime_seconds: float
    failure_samples: tuple[str, ...]
    search_complete: bool = True
    optimal_within_scope: bool = True
    globally_optimal: bool = False
    optimality_scope: ReferenceOptimalityScope = (
        ReferenceOptimalityScope.JOB_ORDER_ROUTES_POLICY_PLANNER_AND_LEFT_SHIFT
    )


@dataclass(frozen=True, slots=True)
class ThreePolicyRouteReferenceResult:
    instance_id: str
    records: tuple[RouteReferenceSearchResult, ...]

    @property
    def records_by_policy(
        self,
    ) -> dict[CooperationPolicy, RouteReferenceSearchResult]:
        return {record.policy: record for record in self.records}

    @property
    def nested_reference_bounds_hold(self) -> bool:
        records = self.records_by_policy
        tolerance = 1e-9
        return (
            records[CooperationPolicy.ANY_BAY].best_makespan
            <= records[CooperationPolicy.HANDSHAKE_AREA].best_makespan
            + tolerance
            and records[CooperationPolicy.HANDSHAKE_AREA].best_makespan
            <= records[CooperationPolicy.NO_SHARING].best_makespan
            + tolerance
        )
