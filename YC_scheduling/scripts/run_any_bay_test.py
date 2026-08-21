from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yard_crane_v3 import (
    BoundCalculationRequest,
    CooperationPolicy,
    OperationType,
    build_per_job_transfer_test_schedule,
    build_static_schedule_visualization,
    calculate_bounds,
    load_instance,
    run_policy,
    write_schedule_visualization_bundle,
)


def _split_job_ids(instance) -> tuple[tuple[str, ...], tuple[str, ...]]:
    job_ids = tuple(job.id for job in instance.jobs)
    if len(job_ids) < 2:
        raise ValueError("visualization mode needs at least two jobs")
    return (job_ids[:1], job_ids[1:])


def _build_calculations(instance, existing_job_ids, new_job_ids, decision_time):
    policies = (
        (CooperationPolicy.NO_SHARING, None),
        (CooperationPolicy.HANDSHAKE_AREA, None),
        (CooperationPolicy.ANY_BAY, build_per_job_transfer_test_schedule),
    )
    return tuple(
        calculate_bounds(
            BoundCalculationRequest(
                instance=instance,
                policy=policy,
                existing_job_ids=existing_job_ids,
                new_job_ids=new_job_ids,
                decision_time=decision_time,
            ),
            planner=planner,
        )
        for policy, planner in policies
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run per-job virtual ANY_BAY experiment."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--visualize", action="store_true")
    parser.add_argument("--existing-jobs", nargs="+")
    parser.add_argument("--new-jobs", nargs="+")
    parser.add_argument("--decision-time", type=float, default=0.0)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--title")
    args = parser.parse_args()

    instance = load_instance(args.input)
    outcome = run_policy(
        instance,
        CooperationPolicy.ANY_BAY,
        planner=build_per_job_transfer_test_schedule,
    )

    transfer_ids = sorted(
        {
            operation.transfer_slot_id
            for operation in outcome.schedule.operations
            if operation.operation_type
            in {OperationType.HANDOVER_DROP, OperationType.HANDOVER_PICKUP}
            and operation.transfer_slot_id is not None
        }
    )
    print(
        json.dumps(
            {
                "policy": outcome.policy.value,
                "planner": outcome.planner,
                "valid": outcome.validation.valid,
                "feasible_upper_bound": outcome.feasible_upper_bound,
                "handover_count": outcome.validation.handover_count,
                "used_transfer_slot_ids": transfer_ids,
                "operation_count": len(outcome.schedule.operations),
                "violation_codes": [
                    issue.code for issue in outcome.validation.issues
                ],
            },
            indent=2,
        )
    )

    if args.visualize:
        existing_job_ids = (
            tuple(args.existing_jobs) if args.existing_jobs else _split_job_ids(instance)[0]
        )
        new_job_ids = (
            tuple(args.new_jobs) if args.new_jobs else _split_job_ids(instance)[1]
        )
        visualization = build_static_schedule_visualization(
            _build_calculations(
                instance,
                existing_job_ids,
                new_job_ids,
                args.decision_time,
            ),
            title=args.title,
        )
        output_dir = (
            args.output_dir
            or PROJECT_ROOT
            / "results"
            / f"visualization_{instance.instance_id}_any_bay"
        ).resolve()
        paths = write_schedule_visualization_bundle(visualization, output_dir)
        print(
            json.dumps(
                {
                    "visualization": {
                        "index_html": str(paths.index_html),
                        "data_json": str(paths.data_json),
                    }
                },
                indent=2,
            )
        )

    return 0 if outcome.validation.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
