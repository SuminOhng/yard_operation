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
    build_static_schedule_visualization,
    calculate_bounds,
    load_instance,
    write_schedule_visualization_bundle,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Calculate all three static YC policies and render one "
            "standalone Gantt and spatial-replay bundle."
        )
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--existing-jobs", nargs="+", required=True)
    parser.add_argument("--new-jobs", nargs="+", required=True)
    parser.add_argument("--decision-time", type=float, default=0.0)
    parser.add_argument("--title")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        instance = load_instance(args.input)
        calculations = tuple(
            calculate_bounds(
                BoundCalculationRequest(
                    instance=instance,
                    policy=policy,
                    existing_job_ids=tuple(args.existing_jobs),
                    new_job_ids=tuple(args.new_jobs),
                    decision_time=args.decision_time,
                )
            )
            for policy in CooperationPolicy
        )
        visualization = build_static_schedule_visualization(
            calculations,
            title=args.title,
        )
        paths = write_schedule_visualization_bundle(
            visualization,
            args.output_dir,
        )
        complete = all(
            policy.upper_bound_validated and policy.lower_bound_certified
            for policy in visualization.policies
        )
        summary = {
            "status": "COMPLETE" if complete else "INCOMPLETE",
            "instance_id": visualization.instance_id,
            "policy_count": len(visualization.policies),
            "index_html": str(paths.index_html),
            "data_json": str(paths.data_json),
            "route_candidates": [
                {
                    "route_key": candidate.route_key,
                    "method": candidate.method,
                    "valid": candidate.valid,
                    "makespan": candidate.makespan,
                    "handover_count": candidate.handover_count,
                    "selected": candidate.selected,
                }
                for candidate in visualization.route_candidates
            ],
            "policies": [
                {
                    "policy": policy.policy.value,
                    "status": policy.status,
                    "best_known_upper_bound": policy.best_known_upper_bound,
                    "combined_lower_bound": policy.combined_lower_bound,
                    "relative_gap": policy.relative_gap,
                    "upper_bound_method": policy.upper_bound_method,
                }
                for policy in visualization.policies
            ],
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0 if complete else 1
    except Exception as exc:
        print(
            f"SCHEDULE_VISUALIZATION_ERROR: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
