from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    CooperationPolicy,
    ReferenceOptimalityScope,
    ReferenceSearchConfig,
    ReferenceSearchLimitError,
    build_no_sharing_schedule,
    load_instance,
    reference_result_dict,
    solve_exhaustive_reference,
    solve_three_policy_reference,
    validate_schedule,
    constraints_for,
)


class ExhaustiveReferenceSolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = ROOT / "data" / "benchmarks" / "02_handshake_cross_4jobs.json"
        cls.instance = load_instance(cls.path)

    def test_enumerates_every_job_order_and_returns_valid_schedule(self) -> None:
        result = solve_exhaustive_reference(
            self.instance,
            CooperationPolicy.NO_SHARING,
        )
        self.assertEqual(result.expected_permutation_count, math.factorial(4))
        self.assertEqual(result.evaluated_permutation_count, math.factorial(4))
        self.assertEqual(
            result.feasible_candidate_count + result.infeasible_candidate_count,
            math.factorial(4),
        )
        self.assertTrue(result.search_complete)
        self.assertTrue(result.optimal_within_scope)
        self.assertFalse(result.globally_optimal)
        self.assertIs(
            result.optimality_scope,
            ReferenceOptimalityScope.JOB_ORDER_AND_CURRENT_PLANNER_CANDIDATES,
        )
        validation = validate_schedule(
            self.instance,
            constraints_for(self.instance, CooperationPolicy.NO_SHARING),
            result.best_schedule,
        )
        self.assertTrue(validation.valid, validation.issues)

    def test_reference_is_never_worse_than_original_job_order(self) -> None:
        original = build_no_sharing_schedule(self.instance)
        original_validation = validate_schedule(
            self.instance,
            constraints_for(self.instance, CooperationPolicy.NO_SHARING),
            original,
        )
        result = solve_exhaustive_reference(
            self.instance,
            CooperationPolicy.NO_SHARING,
        )
        self.assertLessEqual(result.best_makespan, original_validation.makespan)

    def test_three_policy_reference_reports_non_nested_candidate_bounds(self) -> None:
        result = solve_three_policy_reference(self.instance)
        self.assertEqual(len(result.records), 3)
        self.assertFalse(result.nested_reference_bounds_hold)
        self.assertTrue(
            all(record.evaluated_permutation_count == 24 for record in result.records)
        )

    def test_job_limit_rejects_before_factorial_search(self) -> None:
        with self.assertRaisesRegex(ReferenceSearchLimitError, "was not started"):
            solve_exhaustive_reference(
                self.instance,
                CooperationPolicy.NO_SHARING,
                config=ReferenceSearchConfig(maximum_jobs=3),
            )

    def test_serialization_states_the_narrow_certificate(self) -> None:
        result = solve_exhaustive_reference(
            self.instance,
            CooperationPolicy.NO_SHARING,
        )
        payload = reference_result_dict(result)
        json.dumps(payload, allow_nan=False)
        self.assertTrue(payload["certificate"]["optimal_within_scope"])
        self.assertFalse(payload["certificate"]["globally_optimal"])
        self.assertEqual(
            payload["search"]["evaluated_permutation_count"],
            24,
        )

    def test_cli_writes_all_policy_reference_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "reference.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_reference_solver.py"),
                    "--input",
                    str(self.path),
                    "--policy",
                    "ALL",
                    "--search-space",
                    "JOB_ORDER",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            console = json.loads(completed.stdout)
            self.assertEqual(console["status"], "COMPLETE")
            artifact = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(artifact["nested_reference_bounds_hold"])
            self.assertEqual(len(artifact["records"]), 3)


if __name__ == "__main__":
    unittest.main()
