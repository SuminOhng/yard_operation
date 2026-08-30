"""Run the complete seed-1 paper-grid BP/VTR and IR-BP baseline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from irbp_replica.simulation.paper_grid_runner import PaperGridRunError, run_paper_grid


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--max-steps",
        type=int,
        help="diagnostic cap; a cap reached before drain is a failed run",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "experiments" / "outputs" / "paper_grid_seed1.json",
        help="full reproducibility artifact",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    try:
        result = run_paper_grid(arguments.project_root, max_steps=arguments.max_steps)
    except PaperGridRunError as error:
        failure = {
            "status": "failed",
            "error": str(error),
            "diagnostics": error.diagnostics,
        }
        rendered_failure = json.dumps(failure, indent=2, sort_keys=True) + "\n"
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered_failure, encoding="utf-8", newline="\n")
        sys.stderr.write(rendered_failure)
        return 2
    rendered = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(rendered, encoding="utf-8", newline="\n")
    summary = {
        "output": str(arguments.output.resolve()),
        "termination": result.termination,
        "vehicle_counts": result.vehicle_counts,
        "topology": result.topology,
        "cav_routing": result.cav_routing,
        "hdv_routing": result.hdv_routing,
        "safety": result.safety,
        "event_digest": result.event_digest,
        "normalized_digest": result.normalized_digest,
    }
    sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
