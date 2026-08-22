"""Execute every manifest scenario under every cooperation policy."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from ..bounds import BoundCalculation, BoundCalculationRequest, calculate_bounds
from ..loader import load_instance
from ..planners import Planner
from ..policy import CooperationPolicy
from .manifest import BenchmarkManifest, BenchmarkScenario


@dataclass(frozen=True, slots=True)
class BoundBatchRecord:
    scenario: BenchmarkScenario
    policy: CooperationPolicy
    expected_outcome: str
    actual_status: str
    expectation_met: bool
    runtime_seconds: float
    calculation: BoundCalculation


@dataclass(frozen=True, slots=True)
class BoundBatchRun:
    manifest: BenchmarkManifest
    records: tuple[BoundBatchRecord, ...]

    @property
    def all_expectations_met(self) -> bool:
        return bool(self.records) and all(
            record.expectation_met for record in self.records
        )

    @property
    def complete_count(self) -> int:
        return sum(record.actual_status == "COMPLETE" for record in self.records)


def run_bound_batch(
    manifest: BenchmarkManifest,
    planner: Planner | None = None,
) -> BoundBatchRun:
    """Run scenarios in manifest order and policies in enum order."""

    records: list[BoundBatchRecord] = []
    for scenario in manifest.scenarios:
        instance = load_instance(scenario.instance_path)
        if len(instance.jobs) != scenario.job_count:
            raise ValueError(
                f"scenario {scenario.id!r} job_count differs from its instance"
            )
        for policy in CooperationPolicy:
            request = BoundCalculationRequest(
                instance=instance,
                policy=policy,
                existing_job_ids=scenario.existing_job_ids,
                new_job_ids=scenario.new_job_ids,
                decision_time=scenario.decision_time,
            )
            started = perf_counter()
            calculation = calculate_bounds(request, planner)
            runtime = perf_counter() - started
            actual = _status(calculation)
            expected = scenario.expected_outcome(policy)
            records.append(
                BoundBatchRecord(
                    scenario=scenario,
                    policy=policy,
                    expected_outcome=expected,
                    actual_status=actual,
                    expectation_met=_matches(expected, actual),
                    runtime_seconds=runtime,
                    calculation=calculation,
                )
            )
    return BoundBatchRun(manifest, tuple(records))


def _status(calculation: BoundCalculation) -> str:
    result = calculation.result
    if result.upper_bound_validated and result.lower_bound_certified:
        return "COMPLETE"
    if result.upper_bound_validated:
        return "UPPER_BOUND_ONLY"
    if result.lower_bound_certified:
        return "LOWER_BOUND_ONLY"
    return "FAILED"


def _matches(expected: str, actual: str) -> bool:
    if expected == "COMPLETE":
        return actual == "COMPLETE"
    if expected == "INFEASIBLE":
        return actual == "LOWER_BOUND_ONLY"
    return False

