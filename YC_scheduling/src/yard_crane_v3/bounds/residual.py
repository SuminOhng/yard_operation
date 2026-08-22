"""Build a valid continuation problem from a completed schedule replay."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Iterable

from ..model import (
    ContainerStatus,
    CraneSpec,
    StaticSchedulingInstance,
    YardState,
    validate_instance,
)
from .scenario import derive_job_subset_instance


class ResidualStateError(ValueError):
    """Raised when a replay state cannot safely start another static plan."""


def build_residual_instance(
    instance: StaticSchedulingInstance,
    pending_job_ids: Iterable[str],
    final_state: YardState,
    *,
    continuation_time: float,
    instance_id: str | None = None,
) -> StaticSchedulingInstance:
    """Create the pending-work problem at a completed schedule boundary.

    A completed inbound job remains physically stacked and can block later
    work.  It is therefore converted from the terminal ``COMPLETED`` marker
    to the reusable physical state ``IN_STACK``.  Outbound containers that
    left the yard remain ``COMPLETED``.
    """

    validate_instance(instance)
    if not math.isfinite(continuation_time):
        raise ResidualStateError("continuation_time must be finite")
    if continuation_time < final_state.current_time:
        raise ResidualStateError(
            "continuation_time must not precede the replay final state"
        )
    if any(crane.carrying_container is not None for crane in final_state.cranes):
        raise ResidualStateError("every crane must be empty at an append boundary")
    if any(slot.containers for slot in final_state.transfer_slots):
        raise ResidualStateError(
            "every transfer slot must be empty at an append boundary"
        )

    containers = tuple(
        replace(container, status=ContainerStatus.IN_STACK)
        if (
            container.status is ContainerStatus.COMPLETED
            and container.current_slot is not None
        )
        else container
        for container in final_state.containers
    )
    cranes = tuple(
        replace(
            crane,
            available_time=max(crane.available_time, continuation_time),
        )
        for crane in final_state.cranes
    )
    continuation_state = YardState(
        current_time=continuation_time,
        stacks=final_state.stacks,
        containers=containers,
        cranes=cranes,
        transfer_slots=final_state.transfer_slots,
    )
    positions = continuation_state.cranes_by_id
    crane_specs = tuple(
        CraneSpec(
            id=crane.id,
            side=crane.side,
            initial_position=positions[crane.id].position,
        )
        for crane in instance.cranes
    )
    subset = derive_job_subset_instance(
        instance,
        pending_job_ids,
        instance_id=(
            instance_id
            if instance_id is not None
            else f"{instance.instance_id}__RESIDUAL"
        ),
    )
    residual = replace(
        subset,
        cranes=crane_specs,
        initial_state=continuation_state,
    )
    validate_instance(residual)
    return residual
