"""Single physical replay engine for primary, handover, and reshuffle work."""

from __future__ import annotations

import math
from collections import defaultdict

from ..model import (
    ContainerStatus,
    CraneSide,
    Position,
    Slot,
    StackKey,
    StaticSchedulingInstance,
    TransferSlotKind,
    TransferSlotSpec,
    validate_instance,
)
from ..policy import CooperationPolicy, PolicyConstraints
from ..schedule import (
    CandidateSchedule,
    OperationPurpose,
    OperationType,
    ScheduledOperation,
)
from ..timing import TimeModel
from .result import (
    OperationTrace,
    SimulationResult,
    SimulationViolation,
    StackDelta,
    StateDelta,
    TransferDelta,
)
from .conflicts import first_crane_conflict
from .working_state import WorkingState


TOL = 1e-9
HANDLING = {
    OperationType.PICKUP,
    OperationType.HANDOVER_DROP,
    OperationType.HANDOVER_PICKUP,
    OperationType.FINAL_DROP,
}


def replay_schedule(
    instance: StaticSchedulingInstance,
    constraints: PolicyConstraints,
    schedule: CandidateSchedule,
) -> SimulationResult:
    """Replay a complete schedule and return immutable state plus evidence."""

    validate_instance(instance)
    state = WorkingState(instance)
    violations: list[SimulationViolation] = []
    codes_by_operation: dict[int, list[str]] = defaultdict(list)
    accepted: dict[int, bool] = {}
    deltas: dict[int, StateDelta] = {}
    completed: set[str] = set()
    completion_times: list[float] = []

    def fail(
        code: str,
        message: str,
        time: float,
        index: int | None = None,
        operation: ScheduledOperation | None = None,
    ) -> None:
        violations.append(
            SimulationViolation(
                code=code,
                message=message,
                time=time,
                operation_index=index,
                crane_id=operation.crane_id if operation else None,
                job_id=operation.job_id if operation else None,
            )
        )
        if index is not None:
            codes_by_operation[index].append(code)

    if schedule.instance_id != instance.instance_id:
        fail("INSTANCE_MISMATCH", "schedule and instance IDs differ", 0.0)
    if schedule.policy is not constraints.policy:
        fail("POLICY_MISMATCH", "schedule and policy differ", 0.0)

    _validate_continuous_separation(instance, schedule, fail)
    events: list[tuple[float, int, int, str]] = []
    for index, operation in enumerate(schedule.operations):
        events.append((operation.start_time, 1, index, "START"))
        events.append((operation.end_time, 0, index, "END"))
    events.sort(key=lambda item: (item[0], item[1], item[2]))

    for event_time, _, index, phase in events:
        operation = schedule.operations[index]
        if not math.isfinite(event_time):
            if phase == "START":
                fail(
                    "INVALID_TIME",
                    "operation time must be finite",
                    state.current_time,
                    index,
                    operation,
                )
                accepted[index] = False
            continue
        state.current_time = max(state.current_time, event_time)
        if phase == "END":
            if accepted.get(index):
                deltas[index] = _finish_operation(
                    state,
                    instance,
                    constraints,
                    operation,
                    index,
                    completed,
                    completion_times,
                )
            continue

        count_before = len(violations)
        _validate_operation_start(
            state,
            instance,
            constraints,
            operation,
            index,
            fail,
        )
        accepted[index] = len(violations) == count_before
        if accepted[index]:
            _reserve_operation(
                state, instance, constraints, operation, index
            )

    for job_id in instance.jobs_by_id:
        if job_id not in completed:
            fail(
                "JOB_NOT_COMPLETED",
                f"job {job_id!r} does not reach FINAL_DROP",
                state.current_time,
            )

    traces = tuple(
        OperationTrace(
            operation_index=index,
            start_time=operation.start_time,
            end_time=operation.end_time,
            accepted=accepted.get(index, False),
            violation_codes=tuple(codes_by_operation.get(index, ())),
            state_delta=deltas.get(index),
        )
        for index, operation in enumerate(schedule.operations)
    )
    valid = not violations
    return SimulationResult(
        valid=valid,
        initial_state=instance.initial_state,
        final_state=state.freeze(),
        violations=tuple(violations),
        operation_traces=traces,
        completed_job_ids=frozenset(completed),
        makespan=max(completion_times) if valid and completion_times else None,
        handover_count=sum(state.handover_counts.values()),
    )


def _operation_container_id(
    instance: StaticSchedulingInstance,
    operation: ScheduledOperation,
) -> str | None:
    if operation.container_id is not None:
        return operation.container_id
    job = instance.jobs_by_id.get(operation.job_id)
    return job.container_id if job is not None else None


def _validate_operation_start(
    state: WorkingState,
    instance: StaticSchedulingInstance,
    constraints: PolicyConstraints,
    operation: ScheduledOperation,
    index: int,
    fail,
) -> None:
    start = operation.start_time
    duration = operation.end_time - operation.start_time
    cranes = instance.cranes_by_id
    jobs = instance.jobs_by_id
    transfers = constraints.transfer_points_by_id
    timing = TimeModel(instance.motion)
    if (
        not math.isfinite(start)
        or not math.isfinite(operation.end_time)
        or start < instance.initial_state.current_time
        or duration <= 0
    ):
        fail("INVALID_TIME", "operation interval is invalid", start, index, operation)
        return
    if operation.crane_id not in cranes:
        fail("UNKNOWN_CRANE", "operation names an unknown crane", start, index, operation)
        return
    if operation.crane_id not in constraints.active_crane_ids:
        fail("INACTIVE_CRANE", "operation uses an inactive crane", start, index, operation)
        return
    crane = state.cranes[operation.crane_id]
    if operation.crane_id in state.active_cranes:
        fail("CRANE_OVERLAP", "crane already has an active operation", start, index, operation)
    if crane.position != operation.start_position:
        fail("POSITION_DISCONTINUITY", "operation starts away from crane", start, index, operation)
    if start < crane.available_time - TOL:
        fail("CRANE_NOT_AVAILABLE", "crane is not available", start, index, operation)
    allow_relief = constraints.policy is CooperationPolicy.NO_SHARING
    if not _position_inside(
        instance, operation.start_position, allow_relief=allow_relief
    ) or not _position_inside(
        instance, operation.end_position, allow_relief=allow_relief
    ):
        fail("POSITION_OUT_OF_BOUNDS", "operation leaves the layout", start, index, operation)

    kind = operation.operation_type
    purpose = operation.purpose
    job = jobs.get(operation.job_id)
    container_id = _operation_container_id(instance, operation)
    container = state.containers.get(container_id) if container_id else None

    if purpose is OperationPurpose.RESHUFFLE:
        if kind not in {
            OperationType.PICKUP,
            OperationType.MOVE_LOADED,
            OperationType.FINAL_DROP,
        }:
            fail("RESHUFFLE_OPERATION", "invalid reshuffle operation type", start, index, operation)
        if operation.container_id is None or container is None:
            fail("RESHUFFLE_CONTAINER", "reshuffle needs an existing container_id", start, index, operation)
    elif kind in {
        OperationType.PICKUP,
        OperationType.MOVE_LOADED,
        OperationType.HANDOVER_DROP,
        OperationType.HANDOVER_PICKUP,
        OperationType.FINAL_DROP,
    }:
        if job is None:
            fail("UNKNOWN_JOB", "primary container operation needs a job", start, index, operation)
        elif operation.container_id is not None and operation.container_id != job.container_id:
            fail("JOB_CONTAINER_MISMATCH", "explicit container differs from job", start, index, operation)

    if kind in {OperationType.HANDOVER_DROP, OperationType.HANDOVER_PICKUP}:
        if purpose is not OperationPurpose.HANDOVER:
            fail("HANDOVER_PURPOSE", "handover operation needs HANDOVER purpose", start, index, operation)
    elif purpose is OperationPurpose.HANDOVER:
        fail("HANDOVER_OPERATION", "HANDOVER purpose needs a handover operation", start, index, operation)

    if operation.target_slot is not None and not (
        purpose is OperationPurpose.RESHUFFLE
        and kind is OperationType.FINAL_DROP
    ):
        fail("UNEXPECTED_TARGET_SLOT", "only reshuffle drop names target_slot", start, index, operation)
    if operation.transfer_slot_id is not None and kind not in {
        OperationType.HANDOVER_DROP,
        OperationType.HANDOVER_PICKUP,
    }:
        fail("UNEXPECTED_TRANSFER_SLOT", "operation cannot name transfer slot", start, index, operation)
    if kind in HANDLING and operation.start_position != operation.end_position:
        fail("HANDLING_MOVES_CRANE", "handling must be stationary", start, index, operation)
    if kind is OperationType.WAIT and operation.start_position != operation.end_position:
        fail("WAIT_MOVES_CRANE", "WAIT must be stationary", start, index, operation)

    expected = _expected_duration(
        state, instance, constraints, operation, job, container, timing
    )
    if expected is not None and not math.isclose(
        duration, expected, rel_tol=0.0, abs_tol=TOL
    ):
        fail("OPERATION_DURATION", "operation duration is physically incorrect", start, index, operation)

    if kind is OperationType.MOVE_EMPTY:
        if crane.carrying_container is not None:
            fail("EMPTY_MOVE_WHILE_LOADED", "crane carries a container", start, index, operation)
        return
    if kind is OperationType.WAIT:
        return
    if container is None:
        return
    if kind is OperationType.MOVE_LOADED:
        if crane.carrying_container != container_id:
            fail("LOADED_MOVE_MISMATCH", "crane does not carry this container", start, index, operation)
    elif kind is OperationType.PICKUP:
        _validate_pickup(
            state, instance, operation, index, crane, job, container, fail
        )
    elif kind is OperationType.FINAL_DROP:
        _validate_drop(
            state,
            instance,
            constraints,
            operation,
            index,
            crane,
            job,
            container,
            fail,
        )
    elif kind is OperationType.HANDOVER_DROP:
        transfer = _validate_handover_slot(
            operation, constraints, transfers, start, index, fail
        )
        if crane.carrying_container != container_id:
            fail("HANDOVER_DROP_MISMATCH", "crane does not carry this container", start, index, operation)
        if job is not None and state.handover_counts.get(job.id, 0) + 1 > constraints.maximum_handovers_per_job:
            fail("HANDOVER_LIMIT", "job exceeds maximum handovers", start, index, operation)
        slot_id = operation.transfer_slot_id
        if transfer is not None and slot_id is not None:
            used = len(state.ensure_transfer_point(slot_id))
            reserved = state.reserved_transfer_drops.get(slot_id, 0)
            if used + reserved >= transfer.capacity:
                fail("TRANSFER_CAPACITY", "transfer slot is full", start, index, operation)
            if transfer.kind is TransferSlotKind.VIRTUAL_STACK:
                target = _next_virtual_stack_slot(
                    state, instance, transfer.position
                )
                if target is None:
                    fail(
                        "STACK_CAPACITY",
                        "virtual transfer stack is full",
                        start,
                        index,
                        operation,
                    )
                else:
                    if target in state.reserved_final_slots:
                        fail(
                            "TARGET_SLOT_RESERVED",
                            "virtual transfer tier is reserved by a final drop",
                            start,
                            index,
                            operation,
                        )
                    if target in state.reserved_virtual_stack_slots:
                        fail(
                            "VIRTUAL_STACK_RESERVED",
                            "virtual transfer tier is already reserved",
                            start,
                            index,
                            operation,
                        )
                    stack = state.stacks[target.stack_key]
                    if stack and stack[-1] in state.reserved_containers:
                        fail(
                            "VIRTUAL_STACK_BUSY",
                            "virtual transfer stack has an active pickup",
                            start,
                            index,
                            operation,
                        )
    elif kind is OperationType.HANDOVER_PICKUP:
        transfer = _validate_handover_slot(
            operation, constraints, transfers, start, index, fail
        )
        if crane.carrying_container is not None:
            fail("HANDOVER_PICKUP_WHILE_LOADED", "receiving crane is loaded", start, index, operation)
        if container.status is not ContainerStatus.AT_TRANSFER_SLOT:
            fail("HANDOVER_NOT_DROPPED", "container is not at transfer slot", start, index, operation)
        elif container.transfer_slot_id != operation.transfer_slot_id:
            fail("HANDOVER_SLOT_MISMATCH", "container is at another transfer slot", start, index, operation)
        elif (
            transfer is not None
            and transfer.kind is TransferSlotKind.VIRTUAL_STACK
            and operation.transfer_slot_id is not None
        ):
            slot_id = operation.transfer_slot_id
            occupants = state.ensure_transfer_point(slot_id)
            if occupants != [container_id]:
                fail(
                    "HANDOVER_CONTAINER_MISMATCH",
                    "virtual transfer point holds another container",
                    start,
                    index,
                    operation,
                )
            current_slot = container.current_slot
            if (
                current_slot is None
                or current_slot.position != transfer.position
            ):
                fail(
                    "HANDOVER_STACK_LOCATION",
                    "virtual handover container has no matching stack tier",
                    start,
                    index,
                    operation,
                )
            else:
                stack = state.stacks[current_slot.stack_key]
                if not stack or stack[-1] != container_id:
                    fail(
                        "HANDOVER_NOT_TOP",
                        "virtual handover container is not stack top",
                        start,
                        index,
                        operation,
                    )
                if any(
                    reserved.stack_key == current_slot.stack_key
                    for reserved in state.reserved_final_slots
                ):
                    fail(
                        "VIRTUAL_STACK_BUSY",
                        "virtual transfer stack has an active drop",
                        start,
                        index,
                        operation,
                    )
            donor = state.virtual_handover_donors.get(slot_id)
            if donor is None:
                fail(
                    "HANDOVER_DONOR_UNKNOWN",
                    "virtual handover donor is missing",
                    start,
                    index,
                    operation,
                )
            elif donor == operation.crane_id:
                fail(
                    "HANDOVER_SAME_CRANE",
                    "virtual handover needs a different receiving crane",
                    start,
                    index,
                    operation,
                )


def _expected_duration(
    state,
    instance,
    constraints,
    operation,
    job,
    container,
    timing,
) -> float | None:
    kind = operation.operation_type
    if kind in {OperationType.MOVE_EMPTY, OperationType.MOVE_LOADED}:
        return timing.travel_seconds(operation.start_position, operation.end_position)
    if kind is OperationType.PICKUP:
        slot = (
            container.current_slot
            if container is not None and container.status is ContainerStatus.IN_STACK
            else None
        )
        return timing.pickup_seconds(slot)
    if kind in {
        OperationType.HANDOVER_PICKUP,
        OperationType.HANDOVER_DROP,
    }:
        transfer = constraints.transfer_points_by_id.get(
            operation.transfer_slot_id
        )
        slot = None
        if transfer is not None and transfer.kind is TransferSlotKind.VIRTUAL_STACK:
            if kind is OperationType.HANDOVER_PICKUP:
                slot = container.current_slot if container is not None else None
            else:
                slot = _next_virtual_stack_slot(
                    state, instance, transfer.position
                )
                if slot is None:
                    return None
        return (
            timing.pickup_seconds(slot)
            if kind is OperationType.HANDOVER_PICKUP
            else timing.drop_seconds(slot)
        )
    if kind is OperationType.FINAL_DROP:
        slot = (
            operation.target_slot
            if operation.purpose is OperationPurpose.RESHUFFLE
            else job.final_slot if job is not None else None
        )
        return timing.drop_seconds(slot)
    return None


def _next_virtual_stack_slot(state, instance, position: Position) -> Slot | None:
    key = StackKey(instance.layout.block_id, position.bay, position.row)
    stack = state.stacks.get(key)
    spec = instance.yard.stacks_by_key.get(key)
    if stack is None or spec is None or len(stack) >= spec.capacity:
        return None
    return Slot(key.block_id, key.bay, key.row, len(stack) + 1)


def _validate_pickup(state, instance, operation, index, crane, job, container, fail) -> None:
    start = operation.start_time
    container_id = container.container_id
    if operation.purpose is OperationPurpose.PRIMARY_JOB:
        if start < job.ready_time - TOL:
            fail("JOB_NOT_READY", "job starts before ready time", start, index, operation)
        if operation.start_position != job.origin:
            fail("WRONG_PICKUP_POSITION", "pickup is not at job origin", start, index, operation)
    elif operation.purpose is OperationPurpose.RESHUFFLE:
        if container.status is not ContainerStatus.IN_STACK:
            fail("RESHUFFLE_SOURCE", "reshuffle container is not stacked", start, index, operation)
    if crane.carrying_container is not None:
        fail("PICKUP_WHILE_LOADED", "crane already carries a container", start, index, operation)
    if container_id in state.reserved_containers:
        fail("CONTAINER_RESERVED", "container is reserved", start, index, operation)
    if container.status is ContainerStatus.IN_STACK:
        slot = container.current_slot
        stack = state.stacks.get(slot.stack_key) if slot else None
        if slot is None or slot.position != operation.start_position or stack is None:
            fail("CONTAINER_LOCATION", "container stack location is inconsistent", start, index, operation)
        elif not stack or stack[-1] != container_id:
            blocker = stack[-1] if stack else None
            fail("BLOCKED_BY_CONTAINER", f"pickup is blocked by {blocker!r}", start, index, operation)
        elif any(
            reserved.stack_key == slot.stack_key
            for reserved in state.reserved_virtual_stack_slots
        ):
            fail(
                "VIRTUAL_STACK_BUSY",
                "stack has an active virtual handover drop",
                start,
                index,
                operation,
            )
    elif container.status is not ContainerStatus.ON_AGV:
        fail("CONTAINER_NOT_PICKABLE", f"container status is {container.status.value}", start, index, operation)


def _validate_drop(state, instance, constraints, operation, index, crane, job, container, fail) -> None:
    start = operation.start_time
    if crane.carrying_container != container.container_id:
        fail("FINAL_DROP_MISMATCH", "crane does not carry this container", start, index, operation)
    if operation.purpose is OperationPurpose.RESHUFFLE:
        target = operation.target_slot
        if target is None or target.stack_key not in instance.yard.stacks_by_key:
            fail("RESHUFFLE_TARGET", "reshuffle needs a valid target_slot", start, index, operation)
            return
        if operation.start_position != target.position:
            fail("RESHUFFLE_POSITION", "reshuffle drop is not at target_slot", start, index, operation)
    else:
        if operation.start_position != job.destination:
            fail("WRONG_FINAL_POSITION", "drop is not at job destination", start, index, operation)
        target = job.final_slot
        if state.handover_counts.get(job.id, 0) == 0 and not constraints.direct_transport_allowed:
            fail("DIRECT_TRANSPORT_FORBIDDEN", "policy forbids direct transport", start, index, operation)
    if target is None:
        return
    stack = state.stacks[target.stack_key]
    capacity = instance.yard.stacks_by_key[target.stack_key].capacity
    if len(stack) >= capacity:
        fail("STACK_CAPACITY", "target stack is full", start, index, operation)
    if len(stack) != target.tier - 1:
        fail("TARGET_TIER_NOT_NEXT", "target tier is not next free tier", start, index, operation)
    if stack and stack[-1] in state.reserved_containers:
        fail(
            "STACK_BUSY",
            "target stack has an active pickup",
            start,
            index,
            operation,
        )
    if target in state.reserved_final_slots:
        fail("TARGET_SLOT_RESERVED", "target slot is reserved", start, index, operation)
    if target in state.reserved_virtual_stack_slots:
        fail(
            "VIRTUAL_STACK_RESERVED",
            "target tier is reserved by a virtual handover",
            start,
            index,
            operation,
        )


def _validate_handover_slot(
    operation, constraints, transfers, time, index, fail
) -> TransferSlotSpec | None:
    slot_id = operation.transfer_slot_id
    if slot_id is None:
        fail("TRANSFER_SLOT_REQUIRED", "handover needs transfer_slot_id", time, index, operation)
        return None
    if slot_id not in transfers:
        fail(
            "TRANSFER_POINT_FORBIDDEN",
            "policy forbids this transfer point",
            time,
            index,
            operation,
        )
        return None
    spec = transfers[slot_id]
    if not spec.enabled:
        fail("TRANSFER_SLOT_DISABLED", "transfer slot is disabled", time, index, operation)
        return None
    if spec.position != operation.start_position:
        fail("TRANSFER_POSITION", "operation is away from transfer slot", time, index, operation)
        return None
    if spec.id not in constraints.allowed_handover_point_ids:
        fail(
            "TRANSFER_POINT_FORBIDDEN",
            "policy forbids this transfer point",
            time,
            index,
            operation,
        )
        return None
    return spec


def _reserve_operation(state, instance, constraints, operation, index) -> None:
    state.active_cranes[operation.crane_id] = index
    container_id = _operation_container_id(instance, operation)
    if operation.operation_type in HANDLING and container_id is not None:
        state.reserved_containers[container_id] = index
    target = _drop_target(instance, operation)
    if operation.operation_type is OperationType.FINAL_DROP and target is not None:
        state.reserved_final_slots[target] = index
    if operation.operation_type is OperationType.HANDOVER_DROP:
        slot_id = operation.transfer_slot_id
        state.ensure_transfer_point(slot_id)
        state.reserved_transfer_drops[slot_id] = state.reserved_transfer_drops.get(slot_id, 0) + 1
        transfer = constraints.transfer_points_by_id[slot_id]
        if transfer.kind is TransferSlotKind.VIRTUAL_STACK:
            target = _next_virtual_stack_slot(
                state, instance, transfer.position
            )
            if target is not None:
                state.reserved_virtual_stack_slots[target] = index


def _drop_target(instance, operation) -> Slot | None:
    if operation.purpose is OperationPurpose.RESHUFFLE:
        return operation.target_slot
    job = instance.jobs_by_id.get(operation.job_id)
    return job.final_slot if job is not None else None


def _finish_operation(
    state,
    instance,
    constraints,
    operation,
    index,
    completed,
    completion_times,
) -> StateDelta:
    crane_before = state.cranes[operation.crane_id]
    container_id = _operation_container_id(instance, operation)
    container_before = state.containers.get(container_id) if container_id else None
    relevant_stack_keys = set()
    if container_before is not None and container_before.current_slot is not None:
        relevant_stack_keys.add(container_before.current_slot.stack_key)
    target = _drop_target(instance, operation)
    if target is not None:
        relevant_stack_keys.add(target.stack_key)
    transfer = constraints.transfer_points_by_id.get(
        operation.transfer_slot_id
    )
    virtual_target = _reserved_virtual_slot(state, index)
    if virtual_target is not None:
        relevant_stack_keys.add(virtual_target.stack_key)
    stack_before = {
        key: tuple(state.stacks[key]) for key in relevant_stack_keys
    }
    transfer_before = {
        slot_id: tuple(state.transfer_slots[slot_id])
        for slot_id in ([operation.transfer_slot_id] if operation.transfer_slot_id else [])
    }
    kind = operation.operation_type
    crane_id = operation.crane_id
    job = instance.jobs_by_id.get(operation.job_id)

    if kind is OperationType.PICKUP and container_id is not None:
        container = state.containers[container_id]
        if container.status is ContainerStatus.IN_STACK:
            state.stacks[container.current_slot.stack_key].pop()
        state.update_container(
            container_id,
            status=ContainerStatus.ON_CRANE,
            current_slot=None,
            carried_by=crane_id,
            transfer_slot_id=None,
        )
        state.update_crane(crane_id, carrying_container=container_id)
    elif kind is OperationType.HANDOVER_DROP and container_id is not None:
        slot_id = operation.transfer_slot_id
        state.transfer_slots[slot_id].append(container_id)
        current_slot = None
        if (
            transfer is not None
            and transfer.kind is TransferSlotKind.VIRTUAL_STACK
        ):
            current_slot = virtual_target
            state.stacks[current_slot.stack_key].append(container_id)
            state.virtual_handover_donors[slot_id] = crane_id
        state.update_container(
            container_id,
            status=ContainerStatus.AT_TRANSFER_SLOT,
            current_slot=current_slot,
            carried_by=None,
            transfer_slot_id=slot_id,
        )
        state.update_crane(crane_id, carrying_container=None)
        state.reserved_transfer_drops[slot_id] -= 1
        if virtual_target is not None:
            state.reserved_virtual_stack_slots.pop(virtual_target, None)
        state.handover_counts[job.id] = state.handover_counts.get(job.id, 0) + 1
    elif kind is OperationType.HANDOVER_PICKUP and container_id is not None:
        slot_id = operation.transfer_slot_id
        if (
            transfer is not None
            and transfer.kind is TransferSlotKind.VIRTUAL_STACK
        ):
            state.stacks[container_before.current_slot.stack_key].pop()
            state.virtual_handover_donors.pop(slot_id, None)
        state.transfer_slots[slot_id].remove(container_id)
        state.update_container(
            container_id,
            status=ContainerStatus.ON_CRANE,
            current_slot=None,
            carried_by=crane_id,
            transfer_slot_id=None,
        )
        state.update_crane(crane_id, carrying_container=container_id)
    elif kind is OperationType.FINAL_DROP and container_id is not None:
        if target is not None:
            state.stacks[target.stack_key].append(container_id)
        if operation.purpose is OperationPurpose.RESHUFFLE:
            state.update_container(
                container_id,
                status=ContainerStatus.IN_STACK,
                current_slot=target,
                carried_by=None,
                transfer_slot_id=None,
            )
        else:
            resting_status = (
                ContainerStatus.IN_STACK
                if target is not None
                else ContainerStatus.COMPLETED
            )
            state.update_container(
                container_id,
                status=resting_status,
                current_slot=target,
                target_slot=target,
                carried_by=None,
                transfer_slot_id=None,
            )
            completed.add(job.id)
            completion_times.append(operation.end_time)
        state.update_crane(crane_id, carrying_container=None)

    state.update_crane(
        crane_id,
        position=operation.end_position,
        available_time=operation.end_time,
    )
    state.active_cranes.pop(crane_id, None)
    if container_id is not None:
        state.reserved_containers.pop(container_id, None)
    if kind is OperationType.FINAL_DROP and target is not None:
        state.reserved_final_slots.pop(target, None)

    crane_after = state.cranes[crane_id]
    container_after = state.containers.get(container_id) if container_id else None
    stack_changes = tuple(
        StackDelta(key, before, tuple(state.stacks[key]))
        for key, before in stack_before.items()
        if before != tuple(state.stacks[key])
    )
    transfer_changes = tuple(
        TransferDelta(slot_id, before, tuple(state.transfer_slots[slot_id]))
        for slot_id, before in transfer_before.items()
        if before != tuple(state.transfer_slots[slot_id])
    )
    return StateDelta(
        crane_id=crane_id,
        crane_position_before=crane_before.position,
        crane_position_after=crane_after.position,
        crane_load_before=crane_before.carrying_container,
        crane_load_after=crane_after.carrying_container,
        container_id=container_id,
        container_status_before=(container_before.status if container_before else None),
        container_status_after=(container_after.status if container_after else None),
        container_slot_before=(container_before.current_slot if container_before else None),
        container_slot_after=(container_after.current_slot if container_after else None),
        stack_changes=stack_changes,
        transfer_changes=transfer_changes,
    )


def _reserved_virtual_slot(state, operation_index: int) -> Slot | None:
    return next(
        (
            slot
            for slot, reserved_index in state.reserved_virtual_stack_slots.items()
            if reserved_index == operation_index
        ),
        None,
    )


def _position_inside(
    instance,
    position: Position,
    *,
    allow_relief: bool = False,
) -> bool:
    relief_bays = {
        instance.layout.seaside_parking_bay - 1,
        instance.layout.landside_parking_bay + 1,
    }
    return (
        (
            instance.layout.is_on_crane_rail(position.bay)
            or (allow_relief and position.bay in relief_bays)
        )
        and 1 <= position.row <= instance.layout.rows
    )


def _validate_continuous_separation(instance, schedule, fail) -> None:
    conflict = first_crane_conflict(instance, schedule)
    if conflict is not None:
        fail(
            "CRANE_SEPARATION",
            (
                "cranes violate continuous separation at "
                f"t={conflict.onset_time:g}"
            ),
            conflict.onset_time,
        )
