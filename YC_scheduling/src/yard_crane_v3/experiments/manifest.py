"""Strict benchmark-manifest contract used by batch experiments."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from ..policy import CooperationPolicy


class BenchmarkManifestError(ValueError):
    """Raised when a benchmark batch definition is incomplete or ambiguous."""


@dataclass(frozen=True, slots=True)
class BenchmarkScenario:
    id: str
    instance_path: Path
    job_count: int
    feature: str
    description: str
    existing_job_ids: tuple[str, ...]
    new_job_ids: tuple[str, ...]
    decision_time: float
    expected_complete_policies: frozenset[CooperationPolicy]
    expected_infeasible_policies: frozenset[CooperationPolicy]

    def expected_outcome(self, policy: CooperationPolicy) -> str:
        if policy in self.expected_complete_policies:
            return "COMPLETE"
        if policy in self.expected_infeasible_policies:
            return "INFEASIBLE"
        raise BenchmarkManifestError(
            f"scenario {self.id!r} has no expectation for {policy.value}"
        )


@dataclass(frozen=True, slots=True)
class BenchmarkManifest:
    schema_version: str
    source_path: Path
    scenarios: tuple[BenchmarkScenario, ...]


def load_benchmark_manifest(path: str | Path) -> BenchmarkManifest:
    """Load and validate one manifest without silently accepting extra fields."""

    source = Path(path).resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkManifestError(f"cannot load manifest: {exc}") from exc
    root = _object(payload, "manifest", {"schema_version", "benchmarks"})
    if root["schema_version"] != "1.0.0":
        raise BenchmarkManifestError("manifest schema_version must be '1.0.0'")
    raw_entries = root["benchmarks"]
    if not isinstance(raw_entries, list) or not raw_entries:
        raise BenchmarkManifestError("benchmarks must be a nonempty array")
    scenarios = tuple(
        _scenario(raw, index, source.parent)
        for index, raw in enumerate(raw_entries)
    )
    ids = [scenario.id for scenario in scenarios]
    if len(set(ids)) != len(ids):
        raise BenchmarkManifestError("benchmark IDs must be unique")
    paths = [scenario.instance_path for scenario in scenarios]
    if len(set(paths)) != len(paths):
        raise BenchmarkManifestError("instance files must be unique")
    return BenchmarkManifest("1.0.0", source, scenarios)


def _scenario(raw, index: int, base: Path) -> BenchmarkScenario:
    label = f"benchmarks[{index}]"
    item = _object(
        raw,
        label,
        {
            "id",
            "instance_file",
            "job_count",
            "feature",
            "description",
            "existing_job_ids",
            "new_job_ids",
            "decision_time",
            "expected_complete_policies",
            "expected_infeasible_policies",
        },
    )
    benchmark_id = str(item["id"])
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", benchmark_id) is None:
        raise BenchmarkManifestError(
            f"{label}.id must contain only letters, numbers, '_' or '-'"
        )
    instance_path = (base / str(item["instance_file"])).resolve()
    if not instance_path.is_file():
        raise BenchmarkManifestError(
            f"{label}.instance_file does not exist: {instance_path}"
        )
    job_count = int(item["job_count"])
    if job_count < 1:
        raise BenchmarkManifestError(f"{label}.job_count must be positive")
    existing = _string_tuple(item["existing_job_ids"], f"{label}.existing_job_ids")
    new = _string_tuple(item["new_job_ids"], f"{label}.new_job_ids")
    if not existing or not new:
        raise BenchmarkManifestError(
            f"{label} needs at least one existing and one new job"
        )
    if set(existing) & set(new):
        raise BenchmarkManifestError(f"{label} job partitions overlap")
    if len(existing) + len(new) != job_count:
        raise BenchmarkManifestError(
            f"{label}.job_count differs from the declared partition"
        )
    decision_time = float(item["decision_time"])
    if not math.isfinite(decision_time) or decision_time < 0:
        raise BenchmarkManifestError(
            f"{label}.decision_time must be finite and nonnegative"
        )
    complete = _policy_set(
        item["expected_complete_policies"],
        f"{label}.expected_complete_policies",
    )
    infeasible = _policy_set(
        item["expected_infeasible_policies"],
        f"{label}.expected_infeasible_policies",
    )
    if complete & infeasible:
        raise BenchmarkManifestError(f"{label} policy expectations overlap")
    if complete | infeasible != frozenset(CooperationPolicy):
        raise BenchmarkManifestError(
            f"{label} must classify every cooperation policy"
        )
    return BenchmarkScenario(
        id=benchmark_id,
        instance_path=instance_path,
        job_count=job_count,
        feature=str(item["feature"]),
        description=str(item["description"]),
        existing_job_ids=existing,
        new_job_ids=new,
        decision_time=decision_time,
        expected_complete_policies=complete,
        expected_infeasible_policies=infeasible,
    )


def _object(value, label: str, required: set[str]):
    if not isinstance(value, dict):
        raise BenchmarkManifestError(f"{label} must be an object")
    missing = required - set(value)
    unknown = set(value) - required
    if missing:
        raise BenchmarkManifestError(
            f"{label} is missing fields: {sorted(missing)}"
        )
    if unknown:
        raise BenchmarkManifestError(
            f"{label} contains unknown fields: {sorted(unknown)}"
        )
    return value


def _string_tuple(value, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise BenchmarkManifestError(f"{label} must be an array of IDs")
    result = tuple(value)
    if len(set(result)) != len(result):
        raise BenchmarkManifestError(f"{label} must contain unique IDs")
    return result


def _policy_set(value, label: str) -> frozenset[CooperationPolicy]:
    names = _string_tuple(value, label)
    try:
        return frozenset(CooperationPolicy(name) for name in names)
    except ValueError as exc:
        raise BenchmarkManifestError(f"{label} contains unknown policy") from exc
