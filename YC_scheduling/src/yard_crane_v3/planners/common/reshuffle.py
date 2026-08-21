"""Policy-independent blocker reshuffling before a stack pickup."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from ...model import (
    ContainerStatus,
    Position,
    Slot,
    StackKey,
    StaticSchedulingInstance,
)
from ...schedule import OperationPurpose, OperationType, ScheduledOperation
from ...timing import TimeModel
from .contract import PlannerInfeasibleError


class ReshufflePlanningState(Protocol):
    """Mutable planner state required by the common reshuffle routine."""

    stacks: dict[StackKey, list[str]]
    container_slots: dict[str, Slot | None]
    container_statuses: dict[str, ContainerStatus]
    crane_times: dict[str, float]
    crane_positions: dict[str, Position]
    operations: list[ScheduledOperation]


def append_blocker_reshuffles(
    instance: StaticSchedulingInstance,
    state: ReshufflePlanningState,
    timing: TimeModel,
    crane_id: str,
    requested_container: str,
    allowed_bays: Iterable[int],
    reserved_final_stacks: set[StackKey],
) -> None:
    """Move every blocker above ``requested_container`` to a safe stack."""

    source_slot = state.container_slots[requested_container]
    if source_slot is None:
        raise PlannerInfeasibleError(
            f"container {requested_container!r} has no stack location"
        )
    source_stack = state.stacks[source_slot.stack_key]
    if requested_container not in source_stack:
        raise PlannerInfeasibleError(
            f"container {requested_container!r} is absent from its stack"
        )

    while source_stack[-1] != requested_container:
        blocker = source_stack[-1]
        blocker_slot = state.container_slots[blocker]
        if blocker_slot is None:
            raise PlannerInfeasibleError(
                f"blocker {blocker!r} has no stack location"
            )
        target = find_reshuffle_target(
            instance,
            state,
            timing,
            blocker_slot.stack_key,
            allowed_bays,
            reserved_final_stacks,
        )
        _append_reshuffle(
            state,
            timing,
            crane_id,
            blocker,
            blocker_slot,
            target,
        )


def find_reshuffle_target(
    instance: StaticSchedulingInstance,
    state: ReshufflePlanningState,
    timing: TimeModel,
    source: StackKey,
    allowed_bays: Iterable[int],
    reserved_final_stacks: set[StackKey],
) -> Slot:
    """Choose the nearest available stack, then prefer lower stack height."""

    allowed = set(allowed_bays)
    candidates: list[tuple[float, int, int, int, StackKey]] = []
    for key, stack in state.stacks.items():
        capacity = instance.yard.stacks_by_key[key].capacity
        if (
            key == source
            or key in reserved_final_stacks
            or key.bay not in allowed
            or len(stack) >= capacity
        ):
            continue
        candidates.append(
            (
                timing.travel_seconds(source.position, key.position),
                len(stack),
                key.bay,
                key.row,
                key,
            )
        )
    if not candidates:
        raise PlannerInfeasibleError(
            f"no safe reshuffle stack is available for {source!r}"
        )
    key = min(candidates)[-1]
    return Slot(key.block_id, key.bay, key.row, len(state.stacks[key]) + 1)


def _append_reshuffle(
    state: ReshufflePlanningState,
    timing: TimeModel,
    crane_id: str,
    container_id: str,
    source: Slot,
    target: Slot,
) -> None:
    _append_move(
        state,
        timing,
        crane_id,
        OperationType.MOVE_EMPTY,
        source.position,
    )
    _append_handling(
        state,
        crane_id,
        OperationType.PICKUP,
        timing.pickup_seconds(source),
        container_id=container_id,
    )
    state.stacks[source.stack_key].pop()
    _append_move(
        state,
        timing,
        crane_id,
        OperationType.MOVE_LOADED,
        target.position,
        container_id=container_id,
        purpose=OperationPurpose.RESHUFFLE,
    )
    _append_handling(
        state,
        crane_id,
        OperationType.FINAL_DROP,
        timing.drop_seconds(target),
        container_id=container_id,
        target_slot=target,
    )
    state.stacks[target.stack_key].append(container_id)
    state.container_slots[container_id] = target
    state.container_statuses[container_id] = ContainerStatus.IN_STACK


def _append_move(
    state: ReshufflePlanningState,
    timing: TimeModel,
    crane_id: str,
    operation_type: OperationType,
    destination: Position,
    *,
    container_id: str | None = None,
    purpose: OperationPurpose = OperationPurpose.PRIMARY_JOB,
) -> None:
    origin = state.crane_positions[crane_id]
    duration = timing.travel_seconds(origin, destination)
    if duration <= 0:
        return
    start = state.crane_times[crane_id]
    state.operations.append(
        ScheduledOperation(
            crane_id,
            operation_type,
            start,
            start + duration,
            origin,
            destination,
            container_id=container_id,
            purpose=purpose,
        )
    )
    state.crane_times[crane_id] += duration
    state.crane_positions[crane_id] = destination


def _append_handling(
    state: ReshufflePlanningState,
    crane_id: str,
    operation_type: OperationType,
    duration: float,
    *,
    container_id: str,
    target_slot: Slot | None = None,
) -> None:
    start = state.crane_times[crane_id]
    position = state.crane_positions[crane_id]
    state.operations.append(
        ScheduledOperation(
            crane_id,
            operation_type,
            start,
            start + duration,
            position,
            position,
            container_id=container_id,
            target_slot=target_slot,
            purpose=OperationPurpose.RESHUFFLE,
        )
    )
    state.crane_times[crane_id] += duration
