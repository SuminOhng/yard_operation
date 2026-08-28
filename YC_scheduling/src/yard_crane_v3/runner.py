from __future__ import annotations

from dataclasses import dataclass
from .model import StaticSchedulingInstance, validate_instance
from .planners.common import Planner, build_serial_baseline
from .policy import (
    CooperationPolicy,
    constraints_for,
    validate_policy_lattice,
)
from .schedule import CandidateSchedule
from .validator import ValidationResult, validate_schedule


@dataclass(frozen=True, slots=True)
class PolicyOutcome:
    policy: CooperationPolicy
    planner: str
    schedule: CandidateSchedule
    validation: ValidationResult

    @property
    def feasible_upper_bound(self) -> float | None:
        return self.validation.makespan if self.validation.valid else None


def run_policy(instance: StaticSchedulingInstance, policy: CooperationPolicy, planner: Planner = build_serial_baseline) -> PolicyOutcome:
    validate_instance(instance)
    validate_policy_lattice(instance)
    schedule = planner(instance, policy)
    validation = validate_schedule(instance, constraints_for(instance, policy), schedule)
    return PolicyOutcome(policy, getattr(planner, "__name__", type(planner).__name__), schedule, validation)


def run_three_policy_baseline(instance: StaticSchedulingInstance) -> dict[CooperationPolicy, PolicyOutcome]:
    return {policy: run_policy(instance, policy) for policy in CooperationPolicy}
