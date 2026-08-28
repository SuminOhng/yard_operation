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
    calculate_bounds,
    load_instance,
    write_bound_calculation,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Calculate validated static yard-crane upper/lower bounds and "
            "write one auditable JSON artifact."
        )
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--policy",
        choices=tuple(policy.value for policy in CooperationPolicy),
        required=True,
    )
    parser.add_argument("--existing-jobs", nargs="+", required=True)
    parser.add_argument("--new-jobs", nargs="+", required=True)
    parser.add_argument("--decision-time", type=float, default=0.0)
    parser.add_argument("--certified-existing-lower-bound", type=float)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        instance = load_instance(args.input)
        request = BoundCalculationRequest(
            instance=instance,
            policy=CooperationPolicy(args.policy),
            existing_job_ids=tuple(args.existing_jobs),
            new_job_ids=tuple(args.new_jobs),
            decision_time=args.decision_time,
            certified_existing_lower_bound=(
                args.certified_existing_lower_bound
            ),
        )
        calculation = calculate_bounds(request)
        written = write_bound_calculation(
            calculation,
            args.output,
            source_input=args.input,
        )
        result = calculation.result
        summary = {
            "status": (
                "COMPLETE"
                if result.upper_bound_validated
                and result.lower_bound_certified
                else "INCOMPLETE"
            ),
            "instance_id": result.instance_id,
            "policy": result.policy.value,
            "strict_append_upper_bound": result.strict_append_upper_bound,
            "full_replan_upper_bound": result.full_replan_upper_bound,
            "best_known_upper_bound": result.best_known_upper_bound,
            "combined_lower_bound": result.combined_lower_bound,
            "absolute_gap": result.absolute_gap,
            "relative_gap": result.relative_gap,
            "output": str(written),
            "error": result.error,
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0 if summary["status"] == "COMPLETE" else 1
    except Exception as exc:
        print(
            f"BOUND_CALCULATOR_ERROR: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

