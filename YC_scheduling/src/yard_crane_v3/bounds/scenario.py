"""Derive immutable existing-work and newly revealed-work subproblems."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from ..model import StaticSchedulingInstance, validate_instance
from .request import BoundCalculationRequest


class JobSubsetError(ValueError):
    """Raised when a requested nonempty job subset cannot be derived."""


@dataclass(frozen=True, slots=True)
class BoundScenario:
    request: BoundCalculationRequest
    existing_instance: StaticSchedulingInstance
    new_instance: StaticSchedulingInstance


def derive_job_subset_instance(
    instance: StaticSchedulingInstance,
    job_ids: Iterable[str],
    *,
    instance_id: str | None = None,
) -> StaticSchedulingInstance:
    """Keep physical state unchanged and select jobs in canonical order."""

    validate_instance(instance)
    requested = tuple(job_ids)
    if not requested:
        raise JobSubsetError("job subset must not be empty")
    if len(set(requested)) != len(requested):
        raise JobSubsetError("job subset IDs must be unique")
    unknown = set(requested) - set(instance.jobs_by_id)
    if unknown:
        raise JobSubsetError(
            "unknown jobs: " + ", ".join(sorted(unknown))
        )
    selected_ids = set(requested)
    selected_jobs = tuple(
        job for job in instance.jobs if job.id in selected_ids
    )
    subset = replace(
        instance,
        instance_id=(
            instance_id
            if instance_id is not None
            else f"{instance.instance_id}__JOB_SUBSET"
        ),
        jobs=selected_jobs,
    )
    validate_instance(subset)
    return subset


def derive_bound_scenario(
    request: BoundCalculationRequest,
) -> BoundScenario:
    """Build the two immutable subproblems required by later phases."""

    base_id = request.instance.instance_id
    existing = derive_job_subset_instance(
        request.instance,
        request.existing_job_ids,
        instance_id=f"{base_id}__BOUND_EXISTING",
    )
    new = derive_job_subset_instance(
        request.instance,
        request.new_job_ids,
        instance_id=f"{base_id}__BOUND_NEW",
    )
    return BoundScenario(request, existing, new)

