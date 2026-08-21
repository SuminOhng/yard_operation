"""JSON artifacts for one complete bound-calculator run."""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from ..model import Position, Slot, YardState
from ..schedule import (
    CandidateSchedule,
    OperationPurpose,
    OperationType,
    ScheduledOperation,
)
from ..validator import ValidationResult
from .bound_calculator import BoundCalculation
from .result import BoundCalculationResult


BOUND_ARTIFACT_SCHEMA_VERSION = "1.0.0"


def bound_calculation_dict(
    calculation: BoundCalculation,
    *,
    source_input: str | Path | None = None,
) -> dict[str, object]:
    """Return a complete, JSON-ready, auditable calculation artifact."""

    request = calculation.request
    result = calculation.result
    append = calculation.upper_bounds.strict_append
    replan = calculation.upper_bounds.full_replan
    lower = calculation.lower_bound
    return {
        "schema_version": BOUND_ARTIFACT_SCHEMA_VERSION,
        "status": _calculation_status(result),
        "source_input": str(source_input) if source_input is not None else None,
        "request": {
            "instance_id": request.instance.instance_id,
            "policy": request.policy.value,
            "existing_job_ids": list(request.existing_job_ids),
            "new_job_ids": list(request.new_job_ids),
            "decision_time": request.decision_time,
            "certified_existing_lower_bound": (
                request.certified_existing_lower_bound
            ),
        },
        "result": _result_dict(result),
        "strict_append": {
            "planner": append.planner_name,
            "error": append.result.error,
            "existing_schedule": _schedule_dict(
                append.existing_schedule,
                append.existing_validation,
            ),
            "residual_initial_state": (
                _state_dict(append.residual_instance.initial_state)
                if append.residual_instance is not None
                else None
            ),
            "new_schedule": _schedule_dict(
                append.new_schedule,
                append.new_validation,
            ),
            "combined_schedule": _schedule_dict(
                append.combined_schedule,
                append.combined_validation,
            ),
        },
        "full_replan": {
            "planner": replan.planner_name,
            "error": replan.result.error,
            "effective_job_release_times": (
                {
                    job.id: job.release_time
                    for job in replan.replan_instance.jobs
                }
                if replan.replan_instance is not None
                else None
            ),
            "schedule": _schedule_dict(replan.schedule, replan.validation),
        },
        "lower_bound": {
            "active_crane_count": lower.active_crane_count,
            "job_components": [
                asdict(component) for component in lower.job_components
            ],
            "certified": result.lower_bound_certified,
        },
    }


def write_bound_calculation(
    calculation: BoundCalculation,
    output_path: str | Path,
    *,
    source_input: str | Path | None = None,
) -> Path:
    """Atomically publish one complete calculation artifact."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_atomic(
        path,
        bound_calculation_dict(calculation, source_input=source_input),
    )
    return path


def _calculation_status(result: BoundCalculationResult) -> str:
    if result.upper_bound_validated and result.lower_bound_certified:
        return "COMPLETE"
    if result.upper_bound_validated:
        return "UPPER_BOUND_ONLY"
    if result.lower_bound_certified:
        return "LOWER_BOUND_ONLY"
    return "FAILED"


def _result_dict(result: BoundCalculationResult) -> dict[str, object]:
    payload = asdict(result)
    payload["policy"] = result.policy.value
    payload["existing_job_ids"] = list(result.existing_job_ids)
    payload["new_job_ids"] = list(result.new_job_ids)
    payload["bound_provenance"] = list(result.bound_provenance)
    return payload


def _schedule_dict(
    schedule: CandidateSchedule | None,
    validation: ValidationResult | None,
) -> dict[str, object] | None:
    if schedule is None:
        return None
    return {
        "instance_id": schedule.instance_id,
        "policy": schedule.policy.value,
        "metrics": _schedule_metrics(schedule),
        "operations": [
            _operation_dict(operation) for operation in schedule.operations
        ],
        "validation": _validation_dict(validation),
    }


def _schedule_metrics(schedule: CandidateSchedule) -> dict[str, object]:
    operations = schedule.operations
    by_crane: dict[str, float] = {}
    for operation in operations:
        by_crane[operation.crane_id] = by_crane.get(
            operation.crane_id, 0.0
        ) + (operation.end_time - operation.start_time)
    return {
        "operation_count": len(operations),
        "handover_count": sum(
            operation.operation_type is OperationType.HANDOVER_DROP
            for operation in operations
        ),
        "reshuffle_count": sum(
            operation.purpose is OperationPurpose.RESHUFFLE
            and operation.operation_type is OperationType.PICKUP
            for operation in operations
        ),
        "empty_travel_seconds": sum(
            operation.end_time - operation.start_time
            for operation in operations
            if operation.operation_type is OperationType.MOVE_EMPTY
        ),
        "loaded_travel_seconds": sum(
            operation.end_time - operation.start_time
            for operation in operations
            if operation.operation_type is OperationType.MOVE_LOADED
        ),
        "busy_seconds_by_crane": dict(sorted(by_crane.items())),
    }


def _validation_dict(
    validation: ValidationResult | None,
) -> dict[str, object] | None:
    if validation is None:
        return None
    simulation = validation.simulation
    return {
        "valid": validation.valid,
        "makespan": validation.makespan,
        "handover_count": validation.handover_count,
        "completed_job_ids": sorted(simulation.completed_job_ids),
        "violations": [
            {
                "code": violation.code,
                "message": violation.message,
                "time": violation.time,
                "operation_index": violation.operation_index,
                "crane_id": violation.crane_id,
                "job_id": violation.job_id,
            }
            for violation in simulation.violations
        ],
        "final_state": _state_dict(simulation.final_state),
    }


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


def _state_dict(state: YardState) -> dict[str, object]:
    return {
        "current_time": state.current_time,
        "stacks": [
            {
                "block_id": stack.key.block_id,
                "bay": stack.key.bay,
                "row": stack.key.row,
                "containers": list(stack.containers),
            }
            for stack in state.stacks
        ],
        "containers": [
            {
                "container_id": container.container_id,
                "status": container.status.value,
                "current_slot": _slot_dict(container.current_slot),
                "target_slot": _slot_dict(container.target_slot),
                "carried_by": container.carried_by,
                "transfer_slot_id": container.transfer_slot_id,
            }
            for container in state.containers
        ],
        "cranes": [
            {
                "crane_id": crane.crane_id,
                "position": _position_dict(crane.position),
                "carrying_container": crane.carrying_container,
                "available_time": crane.available_time,
            }
            for crane in state.cranes
        ],
        "transfer_slots": [
            {
                "slot_id": slot.slot_id,
                "containers": list(slot.containers),
            }
            for slot in state.transfer_slots
        ],
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
    text = json.dumps(
        payload,
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"
    temporary: Path | None = None
    try:
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
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()

