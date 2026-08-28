"""Run exhaustive small-instance reference search from the command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    CooperationPolicy,
    ReferenceSearchConfig,
    load_instance,
    reference_result_dict,
    route_reference_result_dict,
    solve_exhaustive_reference,
    solve_route_mode_reference,
    solve_three_policy_reference,
    solve_three_policy_route_reference,
    three_policy_reference_dict,
    three_policy_route_reference_dict,
    write_reference_result,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enumerate every job order for one or all YC policies."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument(
        "--policy",
        choices=[policy.value for policy in CooperationPolicy] + ["ALL"],
        default="ALL",
    )
    parser.add_argument("--maximum-jobs", type=int, default=8)
    parser.add_argument("--maximum-route-candidates", type=int, default=100000)
    parser.add_argument(
        "--search-space",
        choices=["JOB_ORDER", "ROUTE_MODE"],
        default="ROUTE_MODE",
    )
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        instance = load_instance(arguments.input)
        config = ReferenceSearchConfig(
            maximum_jobs=arguments.maximum_jobs,
            maximum_route_candidates=arguments.maximum_route_candidates,
        )
        if arguments.search_space == "ROUTE_MODE" and arguments.policy == "ALL":
            result = solve_three_policy_route_reference(instance, config=config)
            payload = three_policy_route_reference_dict(result)
        elif arguments.search_space == "ROUTE_MODE":
            result = solve_route_mode_reference(
                instance,
                CooperationPolicy(arguments.policy),
                config=config,
            )
            payload = route_reference_result_dict(result)
        elif arguments.policy == "ALL":
            result = solve_three_policy_reference(instance, config=config)
            payload = three_policy_reference_dict(result)
        else:
            result = solve_exhaustive_reference(
                instance,
                CooperationPolicy(arguments.policy),
                config=config,
            )
            payload = reference_result_dict(result)
        output_path = write_reference_result(payload, arguments.output)
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}))
        return 2

    print(
        json.dumps(
            {
                "status": "COMPLETE",
                "instance_id": instance.instance_id,
                "policy": arguments.policy,
                "search_space": arguments.search_space,
                "output": str(output_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
