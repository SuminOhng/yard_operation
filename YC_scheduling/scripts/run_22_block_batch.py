from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yard_crane_v3 import (
    build_three_policy_comparison_visualization,
    comparison_summary_dict,
    load_instance,
    run_three_policy_comparison,
    write_comparison_bundle,
    write_schedule_visualization_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run all three policies on the 22-block instance set."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=PROJECT_ROOT / "data" / "blocks_22" / "manifest.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "results" / "blocks_22",
    )
    parser.add_argument(
        "--replay-output-dir",
        type=Path,
        help="Write replays from the exact schedules exported in output-dir.",
    )
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    entries = payload["instances"]
    if len(entries) != 22:
        raise ValueError("manifest must contain exactly 22 instances")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(f"output directory is not empty: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.replay_output_dir is not None:
        if (
            args.replay_output_dir.exists()
            and any(args.replay_output_dir.iterdir())
        ):
            raise FileExistsError(
                f"replay output directory is not empty: {args.replay_output_dir}"
            )
        args.replay_output_dir.mkdir(parents=True, exist_ok=True)

    futures = {}
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        for entry in entries:
            input_path = args.manifest.parent / entry["instance_file"]
            block_output = args.output_dir / entry["block_id"].lower()
            replay_output = (
                args.replay_output_dir / entry["block_id"].lower()
                if args.replay_output_dir is not None
                else None
            )
            future = executor.submit(
                _run_block,
                input_path,
                block_output,
                replay_output,
            )
            futures[future] = entry

        results = []
        for future in as_completed(futures):
            entry = futures[future]
            summary = future.result()
            results.append({"instance": entry, "comparison": summary})
            print(f"completed {entry['block_id']}", flush=True)

    results.sort(key=lambda result: result["instance"]["block_id"])
    rows = _rows(results)
    all_valid = all(row["valid"] for row in rows)
    all_have_reshuffles = all(row["reshuffle_count"] > 0 for row in rows)
    all_nested = all(
        result["comparison"]["nested_upper_bounds_hold"] is not False
        for result in results
    )
    summary = {
        "schema_version": "1.0.0",
        "set_id": payload["set_id"],
        "instance_count": len(results),
        "policy_run_count": len(rows),
        "all_valid": all_valid,
        "all_have_reshuffles": all_have_reshuffles,
        "all_nested_upper_bounds_hold": all_nested,
        "results": results,
    }
    _write_text(
        args.output_dir / "batch_summary.json",
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
    )
    _write_text(args.output_dir / "batch_summary.csv", _csv(rows))
    _write_text(args.output_dir / "README.md", _readme(rows, summary))
    return 0 if all_valid and all_have_reshuffles and all_nested else 1


def _run_block(
    input_path: Path,
    output_dir: Path,
    replay_output_dir: Path | None,
) -> dict[str, object]:
    instance = load_instance(input_path)
    comparison = run_three_policy_comparison(instance)
    write_comparison_bundle(comparison, output_dir)
    if replay_output_dir is not None:
        visualization = build_three_policy_comparison_visualization(
            instance,
            comparison,
            title=f"{instance.layout.block_id} - exact three-policy replay",
        )
        write_schedule_visualization_bundle(visualization, replay_output_dir)
    return comparison_summary_dict(comparison)


def _rows(results: list[dict[str, object]]) -> list[dict[str, object]]:
    rows = []
    for result in results:
        instance = result["instance"]
        comparison = result["comparison"]
        for policy, metrics in comparison["policies"].items():
            rows.append(
                {
                    "block_id": instance["block_id"],
                    "instance_id": instance["instance_id"],
                    "policy": policy,
                    "valid": metrics["valid"],
                    "makespan": metrics["feasible_upper_bound"],
                    "runtime_seconds": metrics["runtime_seconds"],
                    "handover_count": metrics["handover_count"],
                    "reshuffle_count": metrics["reshuffle_count"],
                    "operation_count": metrics["operation_count"],
                    "initial_container_count": instance["initial_container_count"],
                    "direct_blocker_count": instance["direct_blocker_count"],
                    "error": metrics["error"],
                }
            )
    return rows


def _csv(rows: list[dict[str, object]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=tuple(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _readme(rows: list[dict[str, object]], summary: dict[str, object]) -> str:
    lines = [
        "# 22 Block Scheduling Results",
        "",
        f"- Instances: {summary['instance_count']}",
        f"- Policy runs: {summary['policy_run_count']}",
        f"- All schedules valid: {str(summary['all_valid']).lower()}",
        f"- Reshuffles in every policy run: {str(summary['all_have_reshuffles']).lower()}",
        f"- Nested upper bounds hold: {str(summary['all_nested_upper_bounds_hold']).lower()}",
        "",
        "Each `block_XX` directory contains one comparison summary plus schedule and action-scenario JSON for all three policies.",
        "Estimated times are scheduling hints. The physical simulator must enforce action dependencies, resource locks, and continuous crane separation.",
        "",
        "| Block | Policy | Makespan | Handover | Reshuffle | Operations |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        makespan = row["makespan"]
        makespan_text = "-" if makespan is None else f"{makespan:.1f}"
        lines.append(
            f"| {row['block_id']} | {row['policy']} | {makespan_text} | "
            f"{row['handover_count']} | {row['reshuffle_count']} | "
            f"{row['operation_count']} |"
        )
    return "\n".join(lines) + "\n"


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
