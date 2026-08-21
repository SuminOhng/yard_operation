"""JSON-ready comparison summaries and per-policy schedule artifacts."""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from ..model import Position, Slot
from ..schedule import ScheduledOperation
from .result import PolicyComparisonRecord, ThreePolicyComparison


def comparison_summary_dict(
    comparison: ThreePolicyComparison,
) -> dict[str, object]:
    return {
        "instance_id": comparison.instance_id,
        "all_valid": comparison.all_valid,
        "nested_upper_bounds_hold": comparison.nested_upper_bounds_hold,
        "policies": {
            record.policy.value: _record_summary(record)
            for record in comparison.records
        },
    }


def policy_artifact_dict(
    record: PolicyComparisonRecord,
) -> dict[str, object]:
    result = _record_summary(record)
    result["instance_id"] = (
        record.schedule.instance_id if record.schedule is not None else None
    )
    result["operations"] = (
        [_operation_dict(operation) for operation in record.schedule.operations]
        if record.schedule is not None
        else []
    )
    return result


def write_comparison_bundle(
    comparison: ThreePolicyComparison,
    output_dir: str | Path,
) -> tuple[Path, ...]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    summary_path = directory / "comparison_summary.json"
    _write_json_atomic(summary_path, comparison_summary_dict(comparison))
    paths.append(summary_path)
    for record in comparison.records:
        path = directory / f"{record.policy.value.lower()}_schedule.json"
        _write_json_atomic(path, policy_artifact_dict(record))
        paths.append(path)
    return tuple(paths)


def _record_summary(record: PolicyComparisonRecord) -> dict[str, object]:
    metrics = asdict(record.metrics)
    bound = metrics["feasible_upper_bound"]
    if bound is not None:
        metrics["feasible_upper_bound"] = round(bound, 9)
    metrics["runtime_seconds"] = round(metrics["runtime_seconds"], 9)
    metrics["policy"] = record.policy.value
    metrics["planner"] = record.planner
    metrics["error"] = record.error
    return metrics


def _operation_dict(operation: ScheduledOperation) -> dict[str, object]:
    return {
        "crane_id": operation.crane_id,
        "operation_type": operation.operation_type.value,
        "purpose": operation.purpose.value,
        "start_time": operation.start_time,
        "end_time": operation.end_time,
        "start_position": _position_dict(operation.start_position),
        "end_position": _position_dict(operation.end_position),
        "job_id": operation.job_id,
        "container_id": operation.container_id,
        "transfer_slot_id": operation.transfer_slot_id,
        "target_slot": _slot_dict(operation.target_slot),
    }


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


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)
