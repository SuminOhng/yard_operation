from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yard_crane_v3 import load_instance, run_three_policy_baseline


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    outcomes = run_three_policy_baseline(load_instance(args.input))
    print(
        json.dumps(
            {
                policy.value: {
                    "valid": outcome.validation.valid,
                    "feasible_upper_bound": outcome.feasible_upper_bound,
                    "planner": outcome.planner,
                    "completed_job_ids": sorted(
                        outcome.validation.simulation.completed_job_ids
                    ),
                    "final_state_time": (
                        outcome.validation.simulation.final_state.current_time
                    ),
                    "violation_codes": [
                        violation.code
                        for violation in outcome.validation.simulation.violations
                    ],
                }
                for policy, outcome in outcomes.items()
            },
            indent=2,
        )
    )
    return 0 if all(item.validation.valid for item in outcomes.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
