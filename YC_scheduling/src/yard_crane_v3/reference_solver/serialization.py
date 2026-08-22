"""JSON-safe serialization for exhaustive reference certificates."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from ..schedule import ScheduledOperation
from .result import (
    ReferenceSearchResult,
    RouteReferenceSearchResult,
    ThreePolicyReferenceResult,
    ThreePolicyRouteReferenceResult,
)
from .routes import route_mode_dict


REFERENCE_RESULT_SCHEMA_VERSION = "1.0.0"


def _operation_dict(operation: ScheduledOperation) -> dict[str, object]:
    return {
        "crane_id": operation.crane_id,
        "operation_type": operation.operation_type.value,
        "purpose": operation.purpose.value,
        "start_time": operation.start_time,
        "end_time": operation.end_time,
        "start_position": {
            "bay": operation.start_position.bay,
            "row": operation.start_position.row,
        },
        "end_position": {
            "bay": operation.end_position.bay,
            "row": operation.end_position.row,
        },
        "job_id": operation.job_id,
        "container_id": operation.container_id,
        "transfer_slot_id": operation.transfer_slot_id,
    }


def reference_result_dict(
    result: ReferenceSearchResult,
) -> dict[str, object]:
    return {
        "schema_version": REFERENCE_RESULT_SCHEMA_VERSION,
        "instance_id": result.instance_id,
        "policy": result.policy.value,
        "search": {
            "job_count": result.job_count,
            "expected_permutation_count": result.expected_permutation_count,
            "evaluated_permutation_count": result.evaluated_permutation_count,
            "feasible_candidate_count": result.feasible_candidate_count,
            "infeasible_candidate_count": result.infeasible_candidate_count,
            "runtime_seconds": result.runtime_seconds,
            "search_complete": result.search_complete,
        },
        "certificate": {
            "optimal_within_scope": result.optimal_within_scope,
            "globally_optimal": result.globally_optimal,
            "optimality_scope": result.optimality_scope.value,
            "explanation": (
                "All job permutations were evaluated with the current "
                "deterministic policy planner; this is not a global "
                "twin-crane optimality proof."
            ),
        },
        "best": {
            "job_order": list(result.best_job_order),
            "makespan": result.best_makespan,
            "handover_count": result.best_validation.handover_count,
            "operation_count": len(result.best_schedule.operations),
            "operations": [
                _operation_dict(operation)
                for operation in result.best_schedule.operations
            ],
        },
        "failure_samples": list(result.failure_samples),
    }


def three_policy_reference_dict(
    result: ThreePolicyReferenceResult,
) -> dict[str, object]:
    return {
        "schema_version": REFERENCE_RESULT_SCHEMA_VERSION,
        "instance_id": result.instance_id,
        "nested_reference_bounds_hold": (
            result.nested_reference_bounds_hold
        ),
        "records": [reference_result_dict(record) for record in result.records],
    }


def route_reference_result_dict(
    result: RouteReferenceSearchResult,
) -> dict[str, object]:
    return {
        "schema_version": REFERENCE_RESULT_SCHEMA_VERSION,
        "instance_id": result.instance_id,
        "policy": result.policy.value,
        "search": {
            "job_count": result.job_count,
            "permutation_count": result.permutation_count,
            "planner_candidate_count": result.planner_candidate_count,
            "explicit_route_candidate_count": (
                result.explicit_route_candidate_count
            ),
            "concurrent_candidate_count": result.concurrent_candidate_count,
            "expected_candidate_count": result.expected_candidate_count,
            "evaluated_candidate_count": result.evaluated_candidate_count,
            "feasible_candidate_count": result.feasible_candidate_count,
            "infeasible_candidate_count": result.infeasible_candidate_count,
            "runtime_seconds": result.runtime_seconds,
            "search_complete": result.search_complete,
        },
        "certificate": {
            "optimal_within_scope": result.optimal_within_scope,
            "globally_optimal": result.globally_optimal,
            "optimality_scope": result.optimality_scope.value,
            "explanation": (
                "Every job order, current policy-planner candidate, explicit "
                "serial route, and deterministic precedence-preserving "
                "left-shift candidate was evaluated. Arbitrary waits and all "
                "possible interleavings are not covered."
            ),
        },
        "best": {
            "job_order": list(result.best_job_order),
            "route_modes": [
                route_mode_dict(mode) for mode in result.best_route_modes
            ],
            "candidate_source": result.best_candidate_source,
            "crane_job_sequences": [
                {
                    "crane_id": crane_id,
                    "job_ids": list(job_ids),
                }
                for crane_id, job_ids in result.best_crane_job_sequences
            ],
            "makespan": result.best_makespan,
            "handover_count": result.best_validation.handover_count,
            "operation_count": len(result.best_schedule.operations),
            "operations": [
                _operation_dict(operation)
                for operation in result.best_schedule.operations
            ],
        },
        "failure_samples": list(result.failure_samples),
    }


def three_policy_route_reference_dict(
    result: ThreePolicyRouteReferenceResult,
) -> dict[str, object]:
    return {
        "schema_version": REFERENCE_RESULT_SCHEMA_VERSION,
        "instance_id": result.instance_id,
        "nested_reference_bounds_hold": result.nested_reference_bounds_hold,
        "records": [
            route_reference_result_dict(record) for record in result.records
        ],
    }


def write_reference_result(
    payload: dict[str, object],
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return path.resolve()
