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
    build_any_bay_schedule,
    build_static_schedule_visualization,
    calculate_bounds,
    load_instance,
    run_policy,
    write_schedule_visualization_bundle,
)


def _split_job_ids(instance) -> tuple[tuple[str, ...], tuple[str, ...]]:
    job_ids = tuple(job.id for job in instance.jobs)
    if len(job_ids) < 2:
        raise ValueError(
            "visualization mode needs at least two jobs in the instance"
        )
    return (job_ids[:1], job_ids[1:])


def _validate_split(
    instance,
    existing: tuple[str, ...] | None,
    new: tuple[str, ...] | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    all_job_ids = tuple(job.id for job in instance.jobs)
    all_set = set(all_job_ids)
    if existing is None or new is None:
        return _split_job_ids(instance)
    if set(existing) & set(new):
        raise ValueError("existing and new job ids overlap")

    combined = set(existing) | set(new)
    if combined != all_set:
        missing = all_set - combined
        extra = combined - all_set
        detail: list[str] = []
        if missing:
            detail.append(f"missing: {', '.join(sorted(missing))}")
        if extra:
            detail.append(f"extra: {', '.join(sorted(extra))}")
        raise ValueError(
            "existing/new job ids must partition all jobs ("
            + "; ".join(detail)
            + ")"
        )
    return tuple(existing), tuple(new)


def _build_calculations(
    instance,
    existing_job_ids: tuple[str, ...],
    new_job_ids: tuple[str, ...],
    decision_time: float,
):
    policies = (
        (CooperationPolicy.NO_SHARING, None),
        (CooperationPolicy.HANDSHAKE_AREA, None),
        (CooperationPolicy.ANY_BAY, build_any_bay_schedule),
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
    parser = argparse.ArgumentParser(description="Run ANY_BAY variants.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--existing-jobs", nargs="+")
    parser.add_argument("--new-jobs", nargs="+")
    parser.add_argument("--decision-time", type=float, default=0.0)
    parser.add_argument("--visualize", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="directory for visualization bundle (optional)",
    )
    parser.add_argument("--title")
    args = parser.parse_args()

    instance = load_instance(args.input)
    outcome = run_policy(
        instance,
        CooperationPolicy.ANY_BAY,
        planner=build_any_bay_schedule,
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
                "used_crane_ids": sorted(
                    {item.crane_id for item in outcome.schedule.operations}
                ),
                "used_transfer_slot_ids": transfer_ids,
                "completed_job_ids": sorted(
                    outcome.validation.simulation.completed_job_ids
                ),
                "operation_count": len(outcome.schedule.operations),
                "violation_codes": [
                    issue.code for issue in outcome.validation.issues
                ],
            },
            indent=2,
        )
    )

    if args.visualize:
        existing_job_ids, new_job_ids = _validate_split(
            instance,
            tuple(args.existing_jobs) if args.existing_jobs else None,
            tuple(args.new_jobs) if args.new_jobs else None,
        )
        calculations = _build_calculations(
            instance,
            existing_job_ids,
            new_job_ids,
            args.decision_time,
        )
        visualization = build_static_schedule_visualization(
            calculations,
            title=args.title,
        )
        output_dir = (
            (args.output_dir or
            PROJECT_ROOT
            / "results"
            / f"visualization_{instance.instance_id}_any_bay"
            )
        )
        output_dir = Path(output_dir).resolve()
        paths = write_schedule_visualization_bundle(
            visualization,
            output_dir,
        )
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
