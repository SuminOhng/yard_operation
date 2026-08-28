"""Atomic JSON, CSV, Markdown, and per-run artifacts for a bound batch."""

from __future__ import annotations

import csv
import io
import json
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..bounds import write_bound_calculation
from ..schedule import CandidateSchedule, OperationPurpose, OperationType
from .runner import BoundBatchRecord, BoundBatchRun


BATCH_SUMMARY_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class BatchBundlePaths:
    output_dir: Path
    summary_json: Path
    summary_csv: Path
    summary_markdown: Path
    calculation_artifacts: tuple[Path, ...]


def batch_summary_dict(batch: BoundBatchRun) -> dict[str, object]:
    """Return the compact machine-readable summary of one batch."""

    return {
        "schema_version": BATCH_SUMMARY_SCHEMA_VERSION,
        "manifest_schema_version": batch.manifest.schema_version,
        "manifest_source": str(batch.manifest.source_path),
        "scenario_count": len(batch.manifest.scenarios),
        "record_count": len(batch.records),
        "complete_count": batch.complete_count,
        "expectation_match_count": sum(
            record.expectation_met for record in batch.records
        ),
        "all_expectations_met": batch.all_expectations_met,
        "records": [_record_dict(record) for record in batch.records],
    }


def write_bound_batch_bundle(
    batch: BoundBatchRun,
    output_dir: str | Path,
) -> BatchBundlePaths:
    """Write detailed artifacts first and publish summaries last."""

    directory = Path(output_dir)
    if directory.exists() and any(directory.iterdir()):
        raise FileExistsError(
            "batch output directory must be absent or empty"
        )
    directory.mkdir(parents=True, exist_ok=True)
    artifact_paths: list[Path] = []
    for record in batch.records:
        path = (
            directory
            / "artifacts"
            / record.scenario.id
            / f"{record.policy.value.lower()}.json"
        )
        write_bound_calculation(
            record.calculation,
            path,
            source_input=record.scenario.instance_path,
        )
        artifact_paths.append(path)

    rows = [_record_dict(record) for record in batch.records]
    summary_json = directory / "batch_summary.json"
    summary_csv = directory / "batch_summary.csv"
    summary_markdown = directory / "batch_summary.md"
    _write_text_atomic(
        summary_json,
        json.dumps(
            batch_summary_dict(batch),
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
    )
    _write_text_atomic(summary_csv, _csv_text(rows))
    _write_text_atomic(summary_markdown, _markdown_text(batch, rows))
    return BatchBundlePaths(
        output_dir=directory,
        summary_json=summary_json,
        summary_csv=summary_csv,
        summary_markdown=summary_markdown,
        calculation_artifacts=tuple(artifact_paths),
    )


def _record_dict(record: BoundBatchRecord) -> dict[str, object]:
    result = record.calculation.result
    method, schedule = _best_schedule(record)
    return {
        "scenario_id": record.scenario.id,
        "feature": record.scenario.feature,
        "job_count": record.scenario.job_count,
        "existing_job_count": len(record.scenario.existing_job_ids),
        "new_job_count": len(record.scenario.new_job_ids),
        "decision_time": record.scenario.decision_time,
        "policy": record.policy.value,
        "expected_outcome": record.expected_outcome,
        "actual_status": record.actual_status,
        "expectation_met": record.expectation_met,
        "baseline_makespan": result.baseline_makespan,
        "strict_append_upper_bound": result.strict_append_upper_bound,
        "full_replan_upper_bound": result.full_replan_upper_bound,
        "best_known_upper_bound": result.best_known_upper_bound,
        "best_upper_bound_method": method,
        "combined_lower_bound": result.combined_lower_bound,
        "absolute_gap": result.absolute_gap,
        "relative_gap": result.relative_gap,
        "makespan_extension": result.makespan_extension,
        "handover_count": _count_handover(schedule),
        "reshuffle_count": _count_reshuffle(schedule),
        "operation_count": len(schedule.operations) if schedule else 0,
        "used_transfer_slot_ids": sorted(
            {
                operation.transfer_slot_id
                for operation in schedule.operations
                if operation.transfer_slot_id is not None
            }
        )
        if schedule
        else [],
        "runtime_seconds": record.runtime_seconds,
        "error": result.error,
    }


def _best_schedule(
    record: BoundBatchRecord,
) -> tuple[str | None, CandidateSchedule | None]:
    result = record.calculation.result
    best = result.best_known_upper_bound
    if best is None:
        return None, None
    append = result.strict_append_upper_bound
    if append is not None and math.isclose(
        best, append, rel_tol=0.0, abs_tol=1e-9
    ):
        return (
            "STRICT_APPEND",
            record.calculation.upper_bounds.strict_append.combined_schedule,
        )
    return (
        "FULL_REPLAN",
        record.calculation.upper_bounds.full_replan.schedule,
    )


def _count_handover(schedule: CandidateSchedule | None) -> int:
    if schedule is None:
        return 0
    return sum(
        operation.operation_type is OperationType.HANDOVER_DROP
        for operation in schedule.operations
    )


def _count_reshuffle(schedule: CandidateSchedule | None) -> int:
    if schedule is None:
        return 0
    return sum(
        operation.purpose is OperationPurpose.RESHUFFLE
        and operation.operation_type is OperationType.PICKUP
        for operation in schedule.operations
    )


def _csv_text(rows: list[dict[str, object]]) -> str:
    fields = tuple(rows[0]) if rows else ()
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: "|".join(value) if isinstance(value, list) else value
                for key, value in row.items()
            }
        )
    return buffer.getvalue()


def _markdown_text(
    batch: BoundBatchRun,
    rows: list[dict[str, object]],
) -> str:
    lines = [
        "# Bound Batch Summary",
        "",
        f"- Scenarios: {len(batch.manifest.scenarios)}",
        f"- Policy runs: {len(batch.records)}",
        f"- Complete runs: {batch.complete_count}",
        f"- All expectations met: {str(batch.all_expectations_met).lower()}",
        "",
        "| Scenario | Policy | Status | Append UB | Replan UB | Best UB | LB | Gap | H | R | Method |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| {scenario_id} | {policy} | {actual_status} | {append} | "
            "{replan} | {best} | {lower} | {gap} | {handover} | "
            "{reshuffle} | {method} |".format(
                scenario_id=row["scenario_id"],
                policy=row["policy"],
                actual_status=row["actual_status"],
                append=_number(row["strict_append_upper_bound"]),
                replan=_number(row["full_replan_upper_bound"]),
                best=_number(row["best_known_upper_bound"]),
                lower=_number(row["combined_lower_bound"]),
                gap=_percent(row["relative_gap"]),
                handover=row["handover_count"],
                reshuffle=row["reshuffle_count"],
                method=row["best_upper_bound_method"] or "-",
            )
        )
    return "\n".join(lines) + "\n"


def _number(value) -> str:
    return "-" if value is None else f"{value:.3f}"


def _percent(value) -> str:
    return "-" if value is None else f"{100.0 * value:.1f}%"


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
            newline="",
        ) as handle:
            handle.write(text)
            temporary = Path(handle.name)
        temporary.replace(path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
