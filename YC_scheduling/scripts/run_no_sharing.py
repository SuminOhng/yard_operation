from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yard_crane_v3 import (
    CooperationPolicy,
    build_no_sharing_schedule,
    load_instance,
    run_policy,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the two-crane no-sharing scheduler."
    )
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    instance = load_instance(args.input)
    outcome = run_policy(
        instance,
        CooperationPolicy.NO_SHARING,
        planner=build_no_sharing_schedule,
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
    return 0 if outcome.validation.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())

