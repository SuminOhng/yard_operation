from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    BoundCalculationRequest,
    CooperationPolicy,
    calculate_bounds,
    calculate_lower_bound,
    calculate_upper_bounds,
    load_instance,
)


class BoundPhaseFourLowerBoundTests(unittest.TestCase):
    def setUp(self) -> None:
        self.instance = load_instance(
            ROOT / "data" / "static_fair_micro.json"
        )

    def _request(self, **changes) -> BoundCalculationRequest:
        values = {
            "instance": self.instance,
            "policy": CooperationPolicy.NO_SHARING,
            "existing_job_ids": ("JOB_IN_NEAR",),
            "new_job_ids": ("JOB_OUT_FAR",),
            "decision_time": 0.0,
        }
        values.update(changes)
        return BoundCalculationRequest(**values)

    def test_complete_calculator_fills_bounds_and_gaps(self) -> None:
        calculation = calculate_bounds(self._request())
        result = calculation.result
        self.assertTrue(result.upper_bound_validated)
        self.assertTrue(result.lower_bound_certified)
        self.assertEqual(result.existing_jobs_lower_bound, 2.0)
        self.assertEqual(result.new_jobs_earliest_completion, 2.0)
        self.assertEqual(result.workload_lower_bound, 6.0)
        self.assertEqual(result.combined_lower_bound, 6.0)
        self.assertEqual(result.best_known_upper_bound, 17.0)
        self.assertEqual(result.absolute_gap, 11.0)
        self.assertAlmostEqual(result.relative_gap, 11.0 / 17.0)

    def test_job_components_expose_the_workload_proof(self) -> None:
        calculation = calculate_lower_bound(self._request())
        components = {
            component.job_id: component
            for component in calculation.job_components
        }
        self.assertEqual(calculation.active_crane_count, 2)
        self.assertEqual(
            components["JOB_IN_NEAR"].mandatory_work_seconds,
            4.0,
        )
        self.assertEqual(
            components["JOB_OUT_FAR"].mandatory_work_seconds,
            8.0,
        )
        self.assertIsNone(calculation.result.absolute_gap)
        self.assertTrue(calculation.result.lower_bound_certified)

    def test_existing_baseline_is_not_claimed_as_a_lower_bound(self) -> None:
        calculation = calculate_bounds(self._request())
        result = calculation.result
        self.assertEqual(result.baseline_makespan, 4.5)
        self.assertEqual(result.existing_jobs_lower_bound, 2.0)
        self.assertNotEqual(
            result.existing_jobs_lower_bound,
            result.baseline_makespan,
        )

    def test_supplied_certified_existing_bound_strengthens_combined_bound(self) -> None:
        calculation = calculate_bounds(
            self._request(certified_existing_lower_bound=7.0)
        )
        result = calculation.result
        self.assertEqual(result.existing_jobs_lower_bound, 7.0)
        self.assertEqual(result.combined_lower_bound, 7.0)
        self.assertEqual(result.absolute_gap, 10.0)
        self.assertTrue(result.lower_bound_certified)

    def test_decision_time_strengthens_new_job_earliest_completion(self) -> None:
        calculation = calculate_bounds(self._request(decision_time=100.0))
        result = calculation.result
        self.assertEqual(result.new_jobs_earliest_completion, 102.0)
        self.assertGreaterEqual(result.combined_lower_bound, 102.0)
        self.assertLessEqual(
            result.combined_lower_bound,
            result.best_known_upper_bound,
        )

    def test_contradictory_certified_input_is_not_reported_as_valid_gap(self) -> None:
        request = self._request(certified_existing_lower_bound=1000.0)
        upper = calculate_upper_bounds(request)
        lower = calculate_lower_bound(request, upper.result)
        self.assertFalse(lower.result.lower_bound_certified)
        self.assertIsNone(lower.result.absolute_gap)
        self.assertIsNone(lower.result.relative_gap)
        self.assertIn("contradiction", lower.result.error)

    def test_upper_bound_result_must_belong_to_the_same_request(self) -> None:
        request = self._request()
        upper = calculate_upper_bounds(request)
        foreign = replace(upper.result, decision_time=1.0)
        with self.assertRaisesRegex(ValueError, "another request"):
            calculate_lower_bound(request, foreign)


if __name__ == "__main__":
    unittest.main()

