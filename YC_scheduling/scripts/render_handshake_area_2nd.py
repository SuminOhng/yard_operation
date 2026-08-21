from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yard_crane_v3 import load_instance
from yard_crane_v3.planners.handshake_area_2nd import (
    SchedulingHeuristic,
    SchedulingProfile,
    evaluate_handshake_area_2nd_candidates,
)
from yard_crane_v3.visualization import (
    build_single_schedule_visualization,
    write_schedule_visualization_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render the 2017-style handshake heuristic and replay."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=2017)
    parser.add_argument(
        "--profile",
        choices=tuple(profile.value for profile in SchedulingProfile),
        default=SchedulingProfile.PAPER_2017.value,
    )
    parser.add_argument("--title", default="Gharehgozli 2017-style Handshake Replay")
    parser.add_argument(
        "--heuristic",
        choices=("BEST", *(heuristic.value for heuristic in SchedulingHeuristic)),
        default="BEST",
        help="Render the best candidate overall or the best candidate of one heuristic.",
    )
    args = parser.parse_args()

    instance = load_instance(args.input)
    profile = SchedulingProfile(args.profile)
    evaluations = evaluate_handshake_area_2nd_candidates(
        instance,
        two_opt_iterations=args.iterations,
        random_seed=args.seed,
        profile=profile,
    )
    valid = tuple(item for item in evaluations if item.valid)
    if args.heuristic != "BEST":
        valid = tuple(
            item
            for item in valid
            if f":{args.heuristic}:" in item.label
        )
    if not valid:
        raise RuntimeError("no valid 2017-style handshake candidate")
    selected = min(
        valid,
        key=lambda item: (
            item.makespan,
            item.handover_count,
            item.label,
        ),
    )
    assert selected.schedule is not None
    assert selected.validation is not None
    operations = selected.schedule.operations
    preparation_before_waits = []
    for wait in selected.wait_records:
        delayed = operations[wait.operation_index]
        prior_job_operations = tuple(
            operation
            for operation in operations[: wait.operation_index]
            if operation.crane_id == wait.crane_id
            and operation.job_id == wait.request_block_id
        )
        prior = prior_job_operations[-1] if prior_job_operations else None
        wait_start = delayed.start_time - wait.seconds
        preparation_before_waits.append(
            {
                "request_block_id": wait.request_block_id,
                "crane_id": wait.crane_id,
                "delayed_operation": delayed.operation_type.value,
                "wait_start": wait_start,
                "prior_job_operation": (
                    prior.operation_type.value if prior is not None else None
                ),
                "prior_job_operation_end": (
                    prior.end_time if prior is not None else None
                ),
                "prepared_before_wait": (
                    prior is not None and prior.end_time <= wait_start + 1e-9
                ),
            }
        )
    visualization = build_single_schedule_visualization(
        instance,
        selected.schedule,
        selected.validation,
        title=args.title,
        method=selected.label,
    )
    paths = write_schedule_visualization_bundle(visualization, args.output_dir)
    report = {
        "instance_id": instance.instance_id,
        "profile": profile.value,
        "heuristic_selection": args.heuristic,
        "selected": selected.label,
        "makespan": selected.makespan,
        "blocking_seconds": selected.blocking_seconds,
        "conflict_repairs": selected.conflict_repairs,
        "handover_count": selected.handover_count,
        "request_leg_count": len(selected.request_legs),
        "operation_count": len(selected.schedule.operations),
        "job_order": list(selected.job_order),
        "bypasses": [
            {
                "crane_id": record.crane_id,
                "blocked_request_block_id": record.blocked_request_block_id,
                "executed_request_block_id": record.executed_request_block_id,
                "wait_reason": record.wait_reason,
                "original_blocked_index": record.original_blocked_index,
                "original_executed_index": record.original_executed_index,
            }
            for record in selected.bypass_records
        ],
        "fallback_used": selected.fallback_used,
        "experimental_makespan": selected.experimental_makespan,
        "attempted_bypass_count": len(selected.attempted_bypass_records),
        "preparation_before_waits": preparation_before_waits,
        "request_legs": [
            {
                "rank": leg.movement_table_rank,
                "request_block_id": leg.request_block_id,
                "job_id": leg.job_id,
                "crane_id": leg.crane_id,
                "phase": leg.phase.value,
                "origin_bay": leg.origin_bay,
                "destination_bay": leg.destination_bay,
            }
            for leg in selected.request_legs
        ],
        "waits": [
            {
                "operation_index": wait.operation_index,
                "request_block_id": wait.request_block_id,
                "crane_id": wait.crane_id,
                "reason": wait.reason.value,
                "seconds": wait.seconds,
            }
            for wait in selected.wait_records
        ],
        "candidates": [
            {
                "label": item.label,
                "valid": item.valid,
                "makespan": item.makespan,
                "blocking_seconds": item.blocking_seconds,
                "conflict_repairs": item.conflict_repairs,
                "bypass_count": len(item.bypass_records),
                "attempted_bypass_count": len(item.attempted_bypass_records),
                "fallback_used": item.fallback_used,
                "experimental_makespan": item.experimental_makespan,
                "error": item.error,
            }
            for item in evaluations
        ],
        "index_html": str(paths.index_html),
        "visualization_data": str(paths.data_json),
    }
    report_path = paths.output_dir / "paper_heuristic_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
