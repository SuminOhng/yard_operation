"""Shared planner boundary and errors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ...model import StaticSchedulingInstance
from ...policy import CooperationPolicy
from ...schedule import CandidateSchedule
from ...validator import ValidationResult


Planner = Callable[
    [StaticSchedulingInstance, CooperationPolicy], CandidateSchedule
]


class PlannerInfeasibleError(RuntimeError):
    """Raised when a conservative planner cannot construct a valid schedule."""


@dataclass(frozen=True, slots=True)
class PlannerCandidateEvaluation:
    """Auditable outcome for one planner route candidate."""

    label: str
    schedule: CandidateSchedule | None
    validation: ValidationResult | None
    error: str | None = None

    @property
    def valid(self) -> bool:
        return self.validation is not None and self.validation.valid

    @property
    def makespan(self) -> float | None:
        return self.validation.makespan if self.validation is not None else None

    @property
    def handover_count(self) -> int:
        return (
            self.validation.handover_count
            if self.validation is not None
            else 0
        )
