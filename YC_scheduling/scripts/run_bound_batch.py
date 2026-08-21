from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yard_crane_v3 import (
    load_benchmark_manifest,
    run_bound_batch,
    write_bound_batch_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run every benchmark scenario under all three cooperation "
            "policies and write JSON, CSV, and Markdown results."
        )
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = load_benchmark_manifest(args.manifest)
        batch = run_bound_batch(manifest)
        paths = write_bound_batch_bundle(batch, args.output_dir)
        summary = {
            "status": (
                "COMPLETE" if batch.all_expectations_met else "MISMATCH"
            ),
            "scenario_count": len(batch.manifest.scenarios),
            "policy_run_count": len(batch.records),
            "complete_run_count": batch.complete_count,
            "expectation_match_count": sum(
                record.expectation_met for record in batch.records
            ),
            "summary_json": str(paths.summary_json),
            "summary_csv": str(paths.summary_csv),
            "summary_markdown": str(paths.summary_markdown),
            "artifact_count": len(paths.calculation_artifacts),
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0 if batch.all_expectations_met else 1
    except Exception as exc:
        print(
            f"BOUND_BATCH_ERROR: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

