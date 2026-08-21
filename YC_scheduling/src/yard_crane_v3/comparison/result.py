"""Typed results for one fair three-policy comparison run."""

from __future__ import annotations

from dataclasses import dataclass

from ..policy import CooperationPolicy
from ..schedule import CandidateSchedule
from ..validator import ValidationResult


@dataclass(frozen=True, slots=True)
class PolicyMetrics:
    valid: bool
    feasible_upper_bound: float | None
    runtime_seconds: float
    handover_count: int
    reshuffle_count: int
    operation_count: int
    used_crane_ids: tuple[str, ...]
    used_transfer_slot_ids: tuple[str, ...]
    completed_job_ids: tuple[str, ...]
    violation_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PolicyComparisonRecord:
    policy: CooperationPolicy
    planner: str
    metrics: PolicyMetrics
    schedule: CandidateSchedule | None
    validation: ValidationResult | None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ThreePolicyComparison:
    instance_id: str
    records: tuple[PolicyComparisonRecord, ...]

    @property
    def records_by_policy(
        self,
    ) -> dict[CooperationPolicy, PolicyComparisonRecord]:
        return {record.policy: record for record in self.records}

    @property
    def all_valid(self) -> bool:
        return len(self.records) == len(CooperationPolicy) and all(
            record.metrics.valid for record in self.records
        )

    @property
    def nested_upper_bounds_hold(self) -> bool | None:
        """Check ANY <= HANDSHAKE <= NO when every UB is available."""

        if not self.all_valid:
            return None
        records = self.records_by_policy
        no_bound = records[
            CooperationPolicy.NO_SHARING
        ].metrics.feasible_upper_bound
        handshake_bound = records[
            CooperationPolicy.HANDSHAKE_AREA
        ].metrics.feasible_upper_bound
        any_bound = records[
            CooperationPolicy.ANY_BAY
        ].metrics.feasible_upper_bound
        if no_bound is None or handshake_bound is None or any_bound is None:
            return None
        tolerance = 1e-9
        return (
            any_bound <= handshake_bound + tolerance
            and handshake_bound <= no_bound + tolerance
        )

