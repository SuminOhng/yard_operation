"""Run the deterministic one-intersection SUMO/TraCI integration proof."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from irbp_replica.simulation.traci_smoke import run_sumo_smoke


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="repository root containing sumo/networks/smoke_intersection",
    )
    parser.add_argument("--max-steps", type=int, default=180)
    parser.add_argument(
        "--output",
        type=Path,
        help="optional JSON trace path; stdout is always written",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    result = run_sumo_smoke(arguments.project_root, max_steps=arguments.max_steps)
    rendered = json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(rendered, encoding="utf-8", newline="\n")
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
