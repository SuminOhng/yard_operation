from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yard_crane_v3 import (
    CooperationPolicy,
    OperationType,
    build_handshake_area_schedule,
    load_instance,
    run_policy,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the designated-H handshake-area scheduler."
    )
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    instance = load_instance(args.input)
    outcome = run_policy(
        instance,
        CooperationPolicy.HANDSHAKE_AREA,
        planner=build_handshake_area_schedule,
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
    return 0 if outcome.validation.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())

