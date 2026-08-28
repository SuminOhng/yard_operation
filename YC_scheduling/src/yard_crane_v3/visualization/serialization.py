"""Stable JSON representation for static schedule visualizations."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .model import StaticScheduleVisualization


VISUALIZATION_SCHEMA_VERSION = "2.2.0"


def visualization_dict(
    visualization: StaticScheduleVisualization,
) -> dict[str, object]:
    return {
        "schema_version": VISUALIZATION_SCHEMA_VERSION,
        "instance": {
            "instance_id": visualization.instance_id,
            "title": visualization.title,
            "block_id": visualization.block_id,
            "work_bays": visualization.work_bays,
            "rows": visualization.rows,
            "tiers": visualization.tiers,
            "seaside_parking_bay": visualization.seaside_parking_bay,
            "landside_parking_bay": visualization.landside_parking_bay,
            "handshake_bay": visualization.handshake_bay,
            "decision_time": visualization.decision_time,
            "existing_job_ids": list(visualization.existing_job_ids),
            "new_job_ids": list(visualization.new_job_ids),
            "shared_time_horizon": visualization.shared_time_horizon,
            "minimum_crane_separation_bays": (
                visualization.minimum_crane_separation_bays
            ),
            "initial_cranes": [
                {
                    "crane_id": crane.crane_id,
                    "side": crane.side,
                    "position": {"bay": crane.bay, "row": crane.row},
                    "carrying_container": crane.carrying_container,
                }
                for crane in visualization.initial_cranes
            ],
            "initial_containers": [
                {
                    "container_id": container.container_id,
                    "direction": container.direction,
                    "status": container.status,
                    "position": (
                        {"bay": container.bay, "row": container.row}
                        if container.bay is not None and container.row is not None
                        else None
                    ),
                    "tier": container.tier,
                    "carried_by": container.carried_by,
                    "transfer_slot_id": container.transfer_slot_id,
                }
                for container in visualization.initial_containers
            ],
            "transfer_slots": [
                {
                    "slot_id": slot.slot_id,
                    "position": {"bay": slot.bay, "row": slot.row},
                    "capacity": slot.capacity,
                    "enabled": slot.enabled,
                }
                for slot in visualization.transfer_slots
            ],
        },
        "route_candidates": [
            {
                "route_key": candidate.route_key,
                "policy": candidate.policy.value,
                "method": candidate.method,
                "valid": candidate.valid,
                "makespan": candidate.makespan,
                "handover_count": candidate.handover_count,
                "operation_count": candidate.operation_count,
                "selected": candidate.selected,
                "error": candidate.error,
            }
            for candidate in visualization.route_candidates
        ],
        "policies": [
            {
                "policy": policy.policy.value,
                "status": policy.status,
                "upper_bound_validated": policy.upper_bound_validated,
                "lower_bound_certified": policy.lower_bound_certified,
                "best_known_upper_bound": policy.best_known_upper_bound,
                "combined_lower_bound": policy.combined_lower_bound,
                "absolute_gap": policy.absolute_gap,
                "relative_gap": policy.relative_gap,
                "strict_append_upper_bound": policy.strict_append_upper_bound,
                "full_replan_upper_bound": policy.full_replan_upper_bound,
                "upper_bound_method": policy.upper_bound_method,
                "schedule_makespan": policy.schedule_makespan,
                "schedule_valid": policy.schedule_valid,
                "handover_count": policy.handover_count,
                "reshuffle_count": policy.reshuffle_count,
                "concurrent_crane_seconds": policy.concurrent_crane_seconds,
                "average_transfer_wait_seconds": (
                    policy.average_transfer_wait_seconds
                ),
                "crane_ids": list(policy.crane_ids),
                "violation_codes": list(policy.violation_codes),
                "error": policy.error,
                "operations": [
                    {
                        "operation_index": operation.operation_index,
                        "crane_id": operation.crane_id,
                        "operation_type": operation.operation_type.value,
                        "purpose": operation.purpose.value,
                        "start_time": operation.start_time,
                        "end_time": operation.end_time,
                        "duration": operation.duration,
                        "start_position": {
                            "bay": operation.start_bay,
                            "row": operation.start_row,
                        },
                        "end_position": {
                            "bay": operation.end_bay,
                            "row": operation.end_row,
                        },
                        "job_id": operation.job_id,
                        "container_id": operation.container_id,
                        "transfer_slot_id": operation.transfer_slot_id,
                        "transfer_point_kind": operation.transfer_point_kind,
                        "target_slot": (
                            {
                                "bay": operation.target_bay,
                                "row": operation.target_row,
                                "tier": operation.target_tier,
                            }
                            if operation.target_bay is not None
                            and operation.target_row is not None
                            and operation.target_tier is not None
                            else None
                        ),
                        "accepted": operation.accepted,
                        "state_after": {
                            "crane_load": operation.crane_load_after,
                            "container_status": operation.container_status_after,
                            "container_slot": (
                                {
                                    "bay": operation.container_bay_after,
                                    "row": operation.container_row_after,
                                    "tier": operation.container_tier_after,
                                }
                                if operation.container_bay_after is not None
                                and operation.container_row_after is not None
                                and operation.container_tier_after is not None
                                else None
                            ),
                            "transfer_slot_id": (
                                operation.container_transfer_after
                            ),
                        },
                    }
                    for operation in policy.operations
                ],
            }
            for policy in visualization.policies
        ],
    }


def write_visualization_data(
    visualization: StaticScheduleVisualization,
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    text = json.dumps(
        visualization_dict(visualization),
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"
    _write_text_atomic(path, text)
    return path


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
