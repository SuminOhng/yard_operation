"""Event-driven action scenario export for external crane simulators."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .model import Position, Slot
from .schedule import CandidateSchedule, OperationType, ScheduledOperation


ACTION_SCENARIO_SCHEMA_VERSION = "1.0.0"


def action_scenario_dict(schedule: CandidateSchedule) -> dict[str, object]:
    """Export per-crane actions plus event dependencies.

    The schedule's times are retained as hints only.  Consumers should gate
    execution on dependencies and locks, not on the estimated timestamps.
    """

    operation_ids = {
        index: _operation_id(index)
        for index, _ in enumerate(schedule.operations)
    }
    dependencies = _dependencies(schedule.operations, operation_ids)
    return {
        "schema_version": ACTION_SCENARIO_SCHEMA_VERSION,
        "instance_id": schedule.instance_id,
        "policy": schedule.policy.value,
        "time_semantics": "ESTIMATED_HINTS_ONLY",
        "execution_model": "EVENT_DEPENDENCY_GRAPH",
        "cranes": {
            crane_id: [
                operation_ids[index]
                for index in indices
            ]
            for crane_id, indices in _indices_by_crane(schedule.operations).items()
        },
        "actions": [
            _action_dict(index, operation, operation_ids[index])
            for index, operation in enumerate(schedule.operations)
        ],
        "dependencies": dependencies,
        "resource_locks": _resource_locks(schedule.operations, operation_ids),
    }


def write_action_scenario(
    schedule: CandidateSchedule,
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    text = json.dumps(
        action_scenario_dict(schedule),
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"
    _write_text_atomic(path, text)
    return path


def _action_dict(
    index: int,
    operation: ScheduledOperation,
    action_id: str,
) -> dict[str, object]:
    return {
        "action_id": action_id,
        "operation_index": index,
        "crane_id": operation.crane_id,
        "action_type": operation.operation_type.value,
        "purpose": operation.purpose.value,
        "job_id": operation.job_id,
        "container_id": operation.container_id,
        "transfer_slot_id": operation.transfer_slot_id,
        "from": _position_dict(operation.start_position),
        "to": _position_dict(operation.end_position),
        "target_slot": _slot_dict(operation.target_slot),
        "estimated_start_time": operation.start_time,
        "estimated_end_time": operation.end_time,
        "estimated_duration": operation.end_time - operation.start_time,
    }


def _dependencies(
    operations: tuple[ScheduledOperation, ...],
    operation_ids: dict[int, str],
) -> list[dict[str, object]]:
    dependencies: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str | None]] = set()

    def add(
        before: int,
        after: int,
        dependency_type: str,
        resource_id: str | None = None,
    ) -> None:
        if before == after:
            return
        key = (
            operation_ids[before],
            operation_ids[after],
            dependency_type,
            resource_id,
        )
        if key in seen:
            return
        seen.add(key)
        dependencies.append(
            {
                "before": operation_ids[before],
                "after": operation_ids[after],
                "type": dependency_type,
                "resource_id": resource_id,
            }
        )

    for indices in _indices_by_crane(operations).values():
        for previous, current in zip(indices, indices[1:]):
            add(previous, current, "CRANE_SEQUENCE")

    by_job: dict[str, list[int]] = {}
    for index, operation in enumerate(operations):
        if operation.job_id is not None:
            by_job.setdefault(operation.job_id, []).append(index)
    for indices in by_job.values():
        indices.sort(key=lambda index: _operation_order_key(operations[index], index))
        for previous, current in zip(indices, indices[1:]):
            add(previous, current, "JOB_SEQUENCE")

    handovers = _handover_pairs(operations)
    for (slot_id, _), (drop_index, pickup_index) in handovers.items():
        add(
            drop_index,
            pickup_index,
            "TRANSFER_SLOT_HAS_CONTAINER",
            slot_id,
        )
        donor_exit = _next_same_crane_operation(operations, drop_index)
        receiver_entry = _previous_same_crane_operation(operations, pickup_index)
        if donor_exit is not None and receiver_entry is not None:
            add(
                donor_exit,
                receiver_entry,
                "HANDOVER_BAY_CLEAR",
                f"bay:{operations[drop_index].end_position.bay}",
            )

    by_slot: dict[str, list[tuple[int, int]]] = {}
    for (slot_id, _), pair in handovers.items():
        by_slot.setdefault(slot_id, []).append(pair)
    for slot_id, pairs in by_slot.items():
        pairs.sort(key=lambda pair: _operation_order_key(operations[pair[0]], pair[0]))
        for (_, previous_pickup), (next_drop, _) in zip(pairs, pairs[1:]):
            add(
                previous_pickup,
                next_drop,
                "TRANSFER_SLOT_CAPACITY",
                slot_id,
            )

    return dependencies


def _resource_locks(
    operations: tuple[ScheduledOperation, ...],
    operation_ids: dict[int, str],
) -> list[dict[str, object]]:
    transfer_bays = sorted(
        {
            operation.end_position.bay
            for operation in operations
            if operation.operation_type
            in {OperationType.HANDOVER_DROP, OperationType.HANDOVER_PICKUP}
        }
    )
    locks: list[dict[str, object]] = []
    for index, operation in enumerate(operations):
        for bay in transfer_bays:
            if _operation_touches_bay(operation, bay):
                locks.append(
                    {
                        "action_id": operation_ids[index],
                        "resource_id": f"bay:{bay}",
                        "mode": "EXCLUSIVE",
                        "reason": "TRANSFER_BAY_ACCESS",
                    }
                )
        if operation.transfer_slot_id is not None:
            locks.append(
                {
                    "action_id": operation_ids[index],
                    "resource_id": f"transfer_slot:{operation.transfer_slot_id}",
                    "mode": "EXCLUSIVE",
                    "reason": "TRANSFER_SLOT_ACCESS",
                }
            )
    return locks


def _handover_pairs(
    operations: tuple[ScheduledOperation, ...],
) -> dict[tuple[str, str], tuple[int, int]]:
    drops: dict[tuple[str, str], int] = {}
    pickups: dict[tuple[str, str], int] = {}
    for index, operation in enumerate(operations):
        if operation.transfer_slot_id is None or operation.job_id is None:
            continue
        key = (operation.transfer_slot_id, operation.job_id)
        if operation.operation_type is OperationType.HANDOVER_DROP:
            drops[key] = index
        elif operation.operation_type is OperationType.HANDOVER_PICKUP:
            pickups[key] = index
    return {
        key: (drop_index, pickups[key])
        for key, drop_index in drops.items()
        if key in pickups
    }


def _indices_by_crane(
    operations: tuple[ScheduledOperation, ...],
) -> dict[str, list[int]]:
    by_crane: dict[str, list[int]] = {}
    for index, operation in enumerate(operations):
        by_crane.setdefault(operation.crane_id, []).append(index)
    for indices in by_crane.values():
        indices.sort(key=lambda index: _operation_order_key(operations[index], index))
    return by_crane


def _next_same_crane_operation(
    operations: tuple[ScheduledOperation, ...],
    index: int,
) -> int | None:
    crane_id = operations[index].crane_id
    indices = [
        item
        for item, operation in enumerate(operations)
        if operation.crane_id == crane_id
    ]
    indices.sort(key=lambda item: _operation_order_key(operations[item], item))
    position = indices.index(index)
    return indices[position + 1] if position + 1 < len(indices) else None


def _previous_same_crane_operation(
    operations: tuple[ScheduledOperation, ...],
    index: int,
) -> int | None:
    crane_id = operations[index].crane_id
    indices = [
        item
        for item, operation in enumerate(operations)
        if operation.crane_id == crane_id
    ]
    indices.sort(key=lambda item: _operation_order_key(operations[item], item))
    position = indices.index(index)
    return indices[position - 1] if position > 0 else None


def _operation_touches_bay(operation: ScheduledOperation, bay: int) -> bool:
    return (
        min(operation.start_position.bay, operation.end_position.bay)
        <= bay
        <= max(operation.start_position.bay, operation.end_position.bay)
    )


def _operation_order_key(
    operation: ScheduledOperation,
    index: int,
) -> tuple[float, float, int]:
    return (operation.start_time, operation.end_time, index)


def _operation_id(index: int) -> str:
    return f"op_{index:04d}"


def _position_dict(position: Position) -> dict[str, int]:
    return {"bay": position.bay, "row": position.row}


def _slot_dict(slot: Slot | None) -> dict[str, object] | None:
    if slot is None:
        return None
    return {
        "block_id": slot.block_id,
        "bay": slot.bay,
        "row": slot.row,
        "tier": slot.tier,
    }


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
            newline="",
        ) as handle:
            handle.write(text)
            temporary = Path(handle.name)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
