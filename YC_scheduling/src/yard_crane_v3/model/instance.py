"""Complete policy-neutral static problem and its invariants."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .equipment import CraneSide, CraneSpec, MotionParameters
from .geometry import Slot
from .job import Job, MoveDirection
from .state import ContainerStatus, YardState
from .yard import VIRTUAL_TRANSFER_ID_PREFIX, YardSpec


class DomainError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PhysicalRules:
    minimum_crane_separation_bays: float = 1.0
    maximum_handovers_per_job: int = 1


@dataclass(frozen=True, slots=True)
class StaticSchedulingInstance:
    schema_version: str
    instance_id: str
    yard: YardSpec
    motion: MotionParameters
    physical_rules: PhysicalRules
    cranes: tuple[CraneSpec, ...]
    jobs: tuple[Job, ...]
    initial_state: YardState

    @property
    def layout(self):
        return self.yard.layout

    @property
    def cranes_by_id(self) -> dict[str, CraneSpec]:
        return {crane.id: crane for crane in self.cranes}

    @property
    def jobs_by_id(self) -> dict[str, Job]:
        return {job.id: job for job in self.jobs}


def _slot_is_valid(instance: StaticSchedulingInstance, slot: Slot) -> bool:
    spec = instance.yard.stacks_by_key.get(slot.stack_key)
    return spec is not None and 1 <= slot.tier <= spec.capacity


def validate_instance(instance: StaticSchedulingInstance) -> None:
    errors: list[str] = []
    layout = instance.layout
    if instance.schema_version != "3.1.0":
        errors.append("schema_version must be '3.1.0'")
    if not instance.instance_id:
        errors.append("instance_id must not be empty")
    if not layout.block_id:
        errors.append("layout.block_id must not be empty")
    if layout.bays < 1 or layout.rows < 1 or layout.tiers < 1:
        errors.append("layout bays, rows, and tiers must be positive")
    if not 1 <= layout.handshake_bay <= layout.bays:
        errors.append("handshake_bay must be inside the yard")

    for name, value in (
        ("gantry_seconds_per_bay", instance.motion.gantry_seconds_per_bay),
        ("trolley_seconds_per_row", instance.motion.trolley_seconds_per_row),
        ("hoist_seconds_per_tier", instance.motion.hoist_seconds_per_tier),
        ("pickup_seconds", instance.motion.pickup_seconds),
        ("drop_seconds", instance.motion.drop_seconds),
    ):
        if not math.isfinite(value) or value <= 0:
            errors.append(f"motion.{name} must be finite and > 0")
    rules = instance.physical_rules
    if (
        not math.isfinite(rules.minimum_crane_separation_bays)
        or rules.minimum_crane_separation_bays < 0
    ):
        errors.append("minimum crane separation must be finite and >= 0")
    if rules.maximum_handovers_per_job < 0:
        errors.append("maximum handovers per job must be nonnegative")

    expected_stack_keys = {
        (layout.block_id, bay, row)
        for bay in layout.working_bays
        for row in range(1, layout.rows + 1)
    }
    actual_stack_keys = {
        (stack.key.block_id, stack.key.bay, stack.key.row)
        for stack in instance.yard.stacks
    }
    if actual_stack_keys != expected_stack_keys:
        errors.append("yard must define exactly one stack at every bay/row")
    if len(instance.yard.stacks_by_key) != len(instance.yard.stacks):
        errors.append("stack specifications must be unique")
    for stack in instance.yard.stacks:
        if stack.capacity < 1 or stack.capacity > layout.tiers:
            errors.append(f"stack {stack.key!r} has invalid capacity")

    transfer_ids = [slot.id for slot in instance.yard.transfer_slots]
    if len(set(transfer_ids)) != len(transfer_ids):
        errors.append("transfer slot IDs must be unique")
    for slot in instance.yard.transfer_slots:
        if not slot.id or slot.capacity < 1:
            errors.append(f"transfer slot {slot.id!r} is invalid")
        if slot.id.startswith(VIRTUAL_TRANSFER_ID_PREFIX):
            errors.append(
                f"transfer slot {slot.id!r} uses the reserved virtual ID prefix"
            )
        if not (
            layout.is_work_bay(slot.position.bay)
            and 1 <= slot.position.row <= layout.rows
        ):
            errors.append(f"transfer slot {slot.id!r} is outside the yard")
    if layout.handshake_bay not in instance.yard.enabled_transfer_bays:
        errors.append("handshake_bay must have an enabled transfer slot")

    if len(instance.cranes) != 2:
        errors.append("exactly two cranes are required")
    crane_ids = [crane.id for crane in instance.cranes]
    if len(set(crane_ids)) != len(crane_ids):
        errors.append("crane IDs must be unique")
    for side in CraneSide:
        if sum(crane.side is side for crane in instance.cranes) != 1:
            errors.append(f"exactly one {side.value} crane is required")
    for crane in instance.cranes:
        if not (
            layout.is_on_crane_rail(crane.initial_position.bay)
            and 1 <= crane.initial_position.row <= layout.rows
        ):
            errors.append(f"crane {crane.id!r} starts outside the layout")

    if not instance.jobs:
        errors.append("at least one job is required")
    if len(instance.jobs_by_id) != len(instance.jobs):
        errors.append("job IDs must be unique")
    container_job_ids = [job.container_id for job in instance.jobs]
    if len(set(container_job_ids)) != len(container_job_ids):
        errors.append("one container may belong to only one static job")
    for job in instance.jobs:
        if not job.id or not job.container_id:
            errors.append("job and container IDs must not be empty")
        if not (
            layout.is_on_crane_rail(job.origin.bay)
            and 1 <= job.origin.row <= layout.rows
            and layout.is_on_crane_rail(job.destination.bay)
            and 1 <= job.destination.row <= layout.rows
        ):
            errors.append(f"job {job.id!r} has an invalid endpoint")
        if not all(
            math.isfinite(value) and value >= 0
            for value in (job.release_time, job.agv_ready_time)
        ):
            errors.append(f"job {job.id!r} has an invalid ready time")
        if job.direction is MoveDirection.INBOUND:
            if job.final_slot is None or not _slot_is_valid(instance, job.final_slot):
                errors.append(f"inbound job {job.id!r} needs a valid final_slot")
            elif job.final_slot.position != job.destination:
                errors.append(
                    f"inbound job {job.id!r} destination must match final_slot"
                )

    state = instance.initial_state
    if not math.isfinite(state.current_time) or state.current_time < 0:
        errors.append("initial_state.current_time must be finite and >= 0")
    stack_states = state.stacks_by_key
    if set(stack_states) != set(instance.yard.stacks_by_key):
        errors.append("initial state must contain every physical stack exactly once")
    if len(stack_states) != len(state.stacks):
        errors.append("initial stack states must be unique")
    occupied: dict[str, Slot] = {}
    for stack_state in state.stacks:
        spec = instance.yard.stacks_by_key.get(stack_state.key)
        if spec is None:
            continue
        if stack_state.height > spec.capacity:
            errors.append(f"stack {stack_state.key!r} exceeds capacity")
        for tier, container_id in enumerate(stack_state.containers, start=1):
            if container_id in occupied:
                errors.append(f"container {container_id!r} occupies two stacks")
            occupied[container_id] = Slot(
                stack_state.key.block_id,
                stack_state.key.bay,
                stack_state.key.row,
                tier,
            )

    containers = state.containers_by_id
    if len(containers) != len(state.containers):
        errors.append("container states must be unique")
    if not set(container_job_ids).issubset(containers):
        errors.append("every scheduled container needs an initial state")
    if not set(occupied).issubset(containers):
        errors.append("every stacked container needs a container state")
    jobs_by_container = {job.container_id: job for job in instance.jobs}
    for container in state.containers:
        job = jobs_by_container.get(container.container_id)
        if job is not None and container.target_slot != job.final_slot:
            errors.append(
                f"container {container.container_id!r} target differs from stacking result"
            )
        if container.target_slot is not None and not _slot_is_valid(
            instance, container.target_slot
        ):
            errors.append(f"container {container.container_id!r} has invalid target")
        actual_slot = occupied.get(container.container_id)
        if container.status is ContainerStatus.IN_STACK:
            if container.current_slot is None or container.current_slot != actual_slot:
                errors.append(
                    f"container {container.container_id!r} stack location is inconsistent"
                )
        elif actual_slot is not None:
            errors.append(
                f"container {container.container_id!r} is stacked with status "
                f"{container.status.value}"
            )
        if container.status is ContainerStatus.ON_AGV and (
            container.current_slot is not None
            or container.carried_by is not None
            or container.transfer_slot_id is not None
        ):
            errors.append(f"ON_AGV container {container.container_id!r} has a yard holder")

    crane_states = state.cranes_by_id
    if set(crane_states) != set(crane_ids) or len(crane_states) != len(state.cranes):
        errors.append("initial crane states must match crane specifications")
    for crane in instance.cranes:
        crane_state = crane_states.get(crane.id)
        if crane_state is not None and crane_state.position != crane.initial_position:
            errors.append(f"crane {crane.id!r} state starts at the wrong position")
        if crane_state is not None and (
            not math.isfinite(crane_state.available_time)
            or crane_state.available_time < state.current_time
        ):
            errors.append(f"crane {crane.id!r} has invalid available_time")

    transfer_states = state.transfer_slots_by_id
    transfer_specs = instance.yard.transfer_slots_by_id
    if (
        set(transfer_states) != set(transfer_specs)
        or len(transfer_states) != len(state.transfer_slots)
    ):
        errors.append("initial transfer states must match transfer specifications")
    transferred: dict[str, str] = {}
    for slot_id, slot_state in transfer_states.items():
        spec = transfer_specs.get(slot_id)
        if spec is not None and len(slot_state.containers) > spec.capacity:
            errors.append(f"transfer slot {slot_id!r} exceeds capacity")
        for container_id in slot_state.containers:
            if container_id in transferred:
                errors.append(
                    f"container {container_id!r} occupies two transfer slots"
                )
            transferred[container_id] = slot_id
            container = containers.get(container_id)
            if (
                container is None
                or container.status is not ContainerStatus.AT_TRANSFER_SLOT
                or container.transfer_slot_id != slot_id
            ):
                errors.append(
                    f"container {container_id!r} transfer location is inconsistent"
                )

    carried: dict[str, str] = {}
    for crane_id, crane_state in crane_states.items():
        if crane_state.carrying_container is not None:
            container_id = crane_state.carrying_container
            if container_id in carried:
                errors.append(f"container {container_id!r} is carried twice")
            carried[container_id] = crane_id
    for container in state.containers:
        if container.status is ContainerStatus.ON_CRANE and (
            container.carried_by is None
            or carried.get(container.container_id) != container.carried_by
        ):
            errors.append(
                f"container {container.container_id!r} crane holder is inconsistent"
            )
        if container.status is ContainerStatus.AT_TRANSFER_SLOT and (
            container.transfer_slot_id is None
            or transferred.get(container.container_id)
            != container.transfer_slot_id
        ):
            errors.append(
                f"container {container.container_id!r} transfer holder is inconsistent"
            )

    if errors:
        raise DomainError(
            "Invalid static physical instance:\n"
            + "\n".join(f"- {error}" for error in errors)
        )
