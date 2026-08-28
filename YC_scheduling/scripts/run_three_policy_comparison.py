from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yard_crane_v3 import (
    comparison_summary_dict,
    load_instance,
    run_three_policy_comparison,
    write_comparison_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the three actual policy planners on one input."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    comparison = run_three_policy_comparison(load_instance(args.input))
    summary = comparison_summary_dict(comparison)
    if args.output_dir is not None:
        written = write_comparison_bundle(comparison, args.output_dir)
        summary["written_files"] = [str(path) for path in written]
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if (
        comparison.all_valid
        and comparison.nested_upper_bounds_hold is not False
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())

