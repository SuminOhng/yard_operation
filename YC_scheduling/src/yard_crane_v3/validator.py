"""Thin public facade over the single physical simulation engine."""

from __future__ import annotations

from dataclasses import dataclass

from .model import StaticSchedulingInstance
from .policy import PolicyConstraints
from .schedule import CandidateSchedule
from .simulation import SimulationResult, replay_schedule


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    valid: bool
    issues: tuple[ValidationIssue, ...]
    makespan: float | None
    handover_count: int
    simulation: SimulationResult


def validate_schedule(
    instance: StaticSchedulingInstance,
    constraints: PolicyConstraints,
    schedule: CandidateSchedule,
) -> ValidationResult:
    """Replay once; accept only the simulator-certified result."""

    simulation = replay_schedule(instance, constraints, schedule)
    return ValidationResult(
        valid=simulation.valid,
        issues=tuple(
            ValidationIssue(violation.code, violation.message)
            for violation in simulation.violations
        ),
        makespan=simulation.makespan,
        handover_count=simulation.handover_count,
        simulation=simulation,
    )
