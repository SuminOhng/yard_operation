"""Bounded timing repair for fixed-route two-crane pipeline candidates."""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from ..model import Position, StaticSchedulingInstance
from ..schedule import CandidateSchedule, OperationType
from ..validator import ValidationResult


@dataclass(frozen=True, slots=True)
class PipelineTimingResult:
    schedule: CandidateSchedule
    validation: ValidationResult
    explored_nodes: int
    timing_constraint_count: int


def repair_pipeline_seed(
    instance: StaticSchedulingInstance,
    seed_schedule: CandidateSchedule,
    *,
    max_nodes: int = 2000,
) -> PipelineTimingResult:
    """Left-shift one fixed route and repair separation conflicts.

    This is a bounded feasibility heuristic. It does not enumerate job orders
    or route modes and does not provide an optimality certificate.
    """

    if max_nodes < 1:
        raise ValueError("max_nodes must be positive")
    # Local import prevents production planner initialization from importing
    # the reference-solver package recursively.
    from ..reference_solver.timing_repair import (
        TimingConstraint,
        TimingConstraintReason,
        repair_schedule_timing,
        timing_constraint_signature,
    )

    base_constraints = _transfer_capacity_constraints(
        instance,
        seed_schedule,
        TimingConstraint,
        TimingConstraintReason,
    ) + _interleaved_transfer_access_constraints(
        instance,
        seed_schedule,
        TimingConstraint,
        TimingConstraintReason,
    )
    initial = repair_schedule_timing(
        instance,
        seed_schedule,
        base_constraints,
    )
    counter = 0
    queue: list[tuple[float, int, int, object]] = [
        (_completion_time(initial.schedule), 0, counter, initial)
    ]
    seen = {timing_constraint_signature(initial.constraints)}
    explored = 0

    while queue and explored < max_nodes:
        _, depth, _, repair = heapq.heappop(queue)
        explored += 1
        if repair.validation.valid:
            return PipelineTimingResult(
                repair.schedule,
                repair.validation,
                explored,
                len(repair.constraints),
            )
        conflict = repair.first_conflict
        if conflict is None:
            continue
        pairs: list[tuple[int, int]] = []
        if (
            conflict.seaside_operation_index is not None
            and conflict.landside_operation_index is not None
        ):
            pairs.extend(
                (
                    (
                        conflict.seaside_operation_index,
                        conflict.landside_operation_index,
                    ),
                    (
                        conflict.landside_operation_index,
                        conflict.seaside_operation_index,
                    ),
                )
            )
        for delayed_index, opposing_index in pairs:
            delayed = repair.schedule.operations[delayed_index]
            opposing = repair.schedule.operations[opposing_index]
            constraint = TimingConstraint(
                operation_index=delayed_index,
                earliest_start=opposing.end_time,
                delayed_crane_id=delayed.crane_id,
                conflict_time=conflict.onset_time,
                opposing_operation_index=opposing_index,
                reason=TimingConstraintReason.CRANE_CONFLICT_REPAIR,
            )
            combined = repair.constraints + (constraint,)
            signature = timing_constraint_signature(combined)
            if signature in seen:
                continue
            seen.add(signature)
            try:
                child = repair_schedule_timing(
                    instance,
                    seed_schedule,
                    combined,
                )
            except ValueError:
                continue
            counter += 1
            heapq.heappush(
                queue,
                (
                    _completion_time(child.schedule),
                    depth + 1,
                    counter,
                    child,
                ),
            )

    raise ValueError(
        "pipeline timing repair did not find a valid schedule within "
        f"{max_nodes} nodes"
    )


def retreat_from_transfer_boundary(
    state,
    timing,
    sea_id: str,
    land_id: str,
    transfer_bay: int,
    separation: int,
    append_move,
) -> None:
    """Leave a shared bay for a safe staging bay, never an outside bay."""

    for crane_id, staging_bay in (
        (sea_id, transfer_bay - separation),
        (land_id, transfer_bay + separation),
    ):
        position = state.crane_positions[crane_id]
        if position.bay == transfer_bay:
            append_move(
                state,
                timing,
                crane_id,
                OperationType.MOVE_EMPTY,
                Position(staging_bay, position.row),
            )


def _transfer_capacity_constraints(
    instance,
    schedule,
    constraint_type,
    reason_type,
):
    operations = schedule.operations
    by_slot: dict[str, list[tuple[int, int]]] = {}
    drops: dict[tuple[str, str], int] = {}
    pickups: dict[tuple[str, str], int] = {}
    for index, operation in enumerate(operations):
        slot_id = operation.transfer_slot_id
        job_id = operation.job_id
        if slot_id is None or job_id is None:
            continue
        key = (slot_id, job_id)
        if operation.operation_type is OperationType.HANDOVER_DROP:
            drops[key] = index
        elif operation.operation_type is OperationType.HANDOVER_PICKUP:
            pickups[key] = index
    for key, drop_index in drops.items():
        pickup_index = pickups.get(key)
        if pickup_index is not None:
            by_slot.setdefault(key[0], []).append((drop_index, pickup_index))

    constraints = []
    for pairs in by_slot.values():
        pairs.sort(
            key=lambda pair: (
                operations[pair[0]].start_time,
                operations[pair[0]].end_time,
                pair[0],
            )
        )
        for (_, previous_pickup), (next_drop, _) in zip(
            pairs,
            pairs[1:],
        ):
            operation = operations[next_drop]
            constraints.append(
                constraint_type(
                    operation_index=next_drop,
                    earliest_start=instance.initial_state.current_time,
                    delayed_crane_id=operation.crane_id,
                    conflict_time=instance.initial_state.current_time,
                    opposing_operation_index=previous_pickup,
                    reason=reason_type.TRANSFER_CAPACITY_ORDER,
                )
            )
    return tuple(constraints)


@dataclass(frozen=True, slots=True)
class _TransferAccess:
    transfer_bay: int
    donor_entry_index: int
    donor_exit_index: int
    receiver_entry_index: int
    receiver_exit_index: int
    order_index: int


def _transfer_access_constraints(
    instance,
    schedule,
    constraint_type,
    reason_type,
):
    """Serialize only the short shared-bay access intervals.

    Donor preparation and receiver delivery remain concurrent.  At a transfer
    bay, however, the donor must retreat before the receiver enters, and the
    receiver must leave before the next donor enters.  This models a one-lane
    exchange point without returning either crane to an outside parking bay.
    """

    operations = schedule.operations
    by_crane: dict[str, list[int]] = {}
    for index, operation in enumerate(operations):
        by_crane.setdefault(operation.crane_id, []).append(index)
    positions = {
        index: position
        for indices in by_crane.values()
        for position, index in enumerate(indices)
    }
    pickups = {
        operation.job_id: index
        for index, operation in enumerate(operations)
        if operation.operation_type is OperationType.HANDOVER_PICKUP
        and operation.job_id is not None
    }
    accesses: list[_TransferAccess] = []
    for drop_index, drop in enumerate(operations):
        if (
            drop.operation_type is not OperationType.HANDOVER_DROP
            or drop.job_id is None
        ):
            continue
        pickup_index = pickups.get(drop.job_id)
        if pickup_index is None:
            continue
        transfer_bay = drop.end_position.bay
        accesses.append(
            _TransferAccess(
                transfer_bay=transfer_bay,
                donor_entry_index=_entry_operation_index(
                    operations,
                    by_crane,
                    positions,
                    drop_index,
                    transfer_bay,
                ),
                donor_exit_index=_exit_operation_index(
                    operations,
                    by_crane,
                    positions,
                    drop_index,
                    transfer_bay,
                ),
                receiver_entry_index=_entry_operation_index(
                    operations,
                    by_crane,
                    positions,
                    pickup_index,
                    transfer_bay,
                ),
                receiver_exit_index=_exit_operation_index(
                    operations,
                    by_crane,
                    positions,
                    pickup_index,
                    transfer_bay,
                ),
                order_index=drop_index,
            )
        )

    constraints = []
    for access in accesses:
        receiver_entry = operations[access.receiver_entry_index]
        constraints.append(
            constraint_type(
                operation_index=access.receiver_entry_index,
                earliest_start=instance.initial_state.current_time,
                delayed_crane_id=receiver_entry.crane_id,
                conflict_time=instance.initial_state.current_time,
                opposing_operation_index=access.donor_exit_index,
                reason=reason_type.TRANSFER_ACCESS_ORDER,
            )
        )
    by_bay: dict[int, list[_TransferAccess]] = {}
    for access in accesses:
        by_bay.setdefault(access.transfer_bay, []).append(access)
    for items in by_bay.values():
        items.sort(key=lambda item: item.order_index)
        for previous, current in zip(items, items[1:]):
            donor_entry = operations[current.donor_entry_index]
            constraints.append(
                constraint_type(
                    operation_index=current.donor_entry_index,
                    earliest_start=instance.initial_state.current_time,
                    delayed_crane_id=donor_entry.crane_id,
                    conflict_time=instance.initial_state.current_time,
                    opposing_operation_index=previous.receiver_exit_index,
                    reason=reason_type.TRANSFER_ACCESS_ORDER,
                )
            )
    return tuple(constraints)


def _interleaved_transfer_access_constraints(
    instance,
    schedule,
    constraint_type,
    reason_type,
):
    """Serialize individual H visits while allowing multiple staged requests."""

    operations = schedule.operations
    by_crane: dict[str, list[int]] = {}
    for index, operation in enumerate(operations):
        by_crane.setdefault(operation.crane_id, []).append(index)
    positions = {
        index: position
        for indices in by_crane.values()
        for position, index in enumerate(indices)
    }
    pickups = {
        operation.job_id: index
        for index, operation in enumerate(operations)
        if operation.operation_type is OperationType.HANDOVER_PICKUP
        and operation.job_id is not None
    }
    accesses: list[_TransferAccess] = []
    for drop_index, drop in enumerate(operations):
        if drop.operation_type is not OperationType.HANDOVER_DROP or drop.job_id is None:
            continue
        pickup_index = pickups.get(drop.job_id)
        if pickup_index is None:
            continue
        transfer_bay = drop.end_position.bay
        accesses.append(
            _TransferAccess(
                transfer_bay=transfer_bay,
                donor_entry_index=_entry_operation_index(
                    operations, by_crane, positions, drop_index, transfer_bay
                ),
                donor_exit_index=_exit_operation_index(
                    operations, by_crane, positions, drop_index, transfer_bay
                ),
                receiver_entry_index=_entry_operation_index(
                    operations, by_crane, positions, pickup_index, transfer_bay
                ),
                receiver_exit_index=_exit_operation_index(
                    operations, by_crane, positions, pickup_index, transfer_bay
                ),
                order_index=drop_index,
            )
        )

    constraints = []
    events_by_bay: dict[int, list[tuple[int, int]]] = {}
    for access in accesses:
        receiver_entry = operations[access.receiver_entry_index]
        constraints.append(
            constraint_type(
                operation_index=access.receiver_entry_index,
                earliest_start=instance.initial_state.current_time,
                delayed_crane_id=receiver_entry.crane_id,
                conflict_time=instance.initial_state.current_time,
                opposing_operation_index=access.donor_exit_index,
                reason=reason_type.TRANSFER_ACCESS_ORDER,
            )
        )
        events_by_bay.setdefault(access.transfer_bay, []).extend(
            (
                (access.donor_entry_index, access.donor_exit_index),
                (access.receiver_entry_index, access.receiver_exit_index),
            )
        )

    for events in events_by_bay.values():
        events.sort(
            key=lambda event: (
                operations[event[0]].start_time,
                operations[event[0]].end_time,
                event[0],
            )
        )
        for (_, previous_exit), (current_entry, _) in zip(events, events[1:]):
            if current_entry == previous_exit:
                continue
            operation = operations[current_entry]
            constraints.append(
                constraint_type(
                    operation_index=current_entry,
                    earliest_start=instance.initial_state.current_time,
                    delayed_crane_id=operation.crane_id,
                    conflict_time=instance.initial_state.current_time,
                    opposing_operation_index=previous_exit,
                    reason=reason_type.TRANSFER_ACCESS_ORDER,
                )
            )
    return tuple(constraints)


def _entry_operation_index(
    operations,
    by_crane,
    positions,
    anchor_index: int,
    transfer_bay: int,
) -> int:
    indices = by_crane[operations[anchor_index].crane_id]
    anchor_position = positions[anchor_index]
    for position in range(anchor_position - 1, -1, -1):
        index = indices[position]
        operation = operations[index]
        if (
            operation.end_position.bay == transfer_bay
            and operation.start_position.bay != transfer_bay
        ):
            return index
        if operation.end_position.bay != transfer_bay:
            return indices[position + 1]
    return indices[0]


def _exit_operation_index(
    operations,
    by_crane,
    positions,
    anchor_index: int,
    transfer_bay: int,
) -> int:
    indices = by_crane[operations[anchor_index].crane_id]
    anchor_position = positions[anchor_index]
    for position in range(anchor_position + 1, len(indices)):
        index = indices[position]
        operation = operations[index]
        if (
            operation.start_position.bay == transfer_bay
            and operation.end_position.bay != transfer_bay
        ):
            return index
        if operation.start_position.bay != transfer_bay:
            return indices[position - 1]
    raise ValueError(
        f"crane does not leave transfer bay {transfer_bay} after operation "
        f"{anchor_index}"
    )


def _completion_time(schedule: CandidateSchedule) -> float:
    final_drop_times = [
        operation.end_time
        for operation in schedule.operations
        if operation.operation_type is OperationType.FINAL_DROP
    ]
    return max(final_drop_times, default=0.0)
