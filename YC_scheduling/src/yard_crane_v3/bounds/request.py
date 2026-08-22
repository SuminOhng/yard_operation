"""Validated request contract for one future bound calculation."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..model import StaticSchedulingInstance, validate_instance
from ..policy import CooperationPolicy


class BoundRequestError(ValueError):
    """Raised when existing and newly revealed work is not well defined."""


@dataclass(frozen=True, slots=True)
class BoundCalculationRequest:
    instance: StaticSchedulingInstance
    policy: CooperationPolicy
    existing_job_ids: tuple[str, ...]
    new_job_ids: tuple[str, ...]
    decision_time: float
    certified_existing_lower_bound: float | None = None

    def __post_init__(self) -> None:
        existing = tuple(self.existing_job_ids)
        new = tuple(self.new_job_ids)
        object.__setattr__(self, "existing_job_ids", existing)
        object.__setattr__(self, "new_job_ids", new)
        validate_instance(self.instance)

        errors: list[str] = []
        if not isinstance(self.policy, CooperationPolicy):
            errors.append("policy must be a CooperationPolicy")
        if (
            not math.isfinite(self.decision_time)
            or self.decision_time < self.instance.initial_state.current_time
        ):
            errors.append(
                "decision_time must be finite and not precede initial state"
            )
        if not existing:
            errors.append("at least one existing job is required")
        if not new:
            errors.append("at least one new job is required")
        if len(set(existing)) != len(existing):
            errors.append("existing_job_ids must be unique")
        if len(set(new)) != len(new):
            errors.append("new_job_ids must be unique")

        overlap = set(existing) & set(new)
        if overlap:
            errors.append(
                "existing and new jobs overlap: "
                + ", ".join(sorted(overlap))
            )
        instance_ids = set(self.instance.jobs_by_id)
        requested_ids = set(existing) | set(new)
        unknown = requested_ids - instance_ids
        if unknown:
            errors.append("unknown jobs: " + ", ".join(sorted(unknown)))
        unclassified = instance_ids - requested_ids
        if unclassified:
            errors.append(
                "every instance job must be classified; missing: "
                + ", ".join(sorted(unclassified))
            )

        lower_bound = self.certified_existing_lower_bound
        if lower_bound is not None and (
            not math.isfinite(lower_bound)
            or lower_bound < self.instance.initial_state.current_time
        ):
            errors.append(
                "certified_existing_lower_bound must be finite and not "
                "precede initial state"
            )
        if errors:
            raise BoundRequestError(
                "Invalid bound calculation request:\n"
                + "\n".join(f"- {error}" for error in errors)
            )

    @property
    def all_job_ids(self) -> tuple[str, ...]:
        """Return classified IDs in the original instance job order."""

        classified = set(self.existing_job_ids) | set(self.new_job_ids)
        return tuple(
            job.id for job in self.instance.jobs if job.id in classified
        )

