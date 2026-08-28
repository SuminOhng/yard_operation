from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    BoundCalculationRequest,
    CandidateSchedule,
    CooperationPolicy,
    build_full_replan_instance,
    calculate_full_replan_upper_bound,
    calculate_upper_bounds,
    load_instance,
)


class BoundPhaseThreeFullReplanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.instance = load_instance(
            ROOT / "data" / "static_fair_micro.json"
        )

    def _request(
        self,
        policy: CooperationPolicy,
        *,
        decision_time: float = 0.0,
    ) -> BoundCalculationRequest:
        return BoundCalculationRequest(
            instance=self.instance,
            policy=policy,
            existing_job_ids=("JOB_IN_NEAR",),
            new_job_ids=("JOB_OUT_FAR",),
            decision_time=decision_time,
        )

    def test_every_policy_produces_a_valid_full_replan_bound(self) -> None:
        for policy in CooperationPolicy:
            with self.subTest(policy=policy.value):
                calculation = calculate_full_replan_upper_bound(
                    self._request(policy)
                )
                self.assertTrue(
                    calculation.result.upper_bound_validated,
                    calculation.result.error,
                )
                self.assertIsNotNone(
                    calculation.result.full_replan_upper_bound
                )
                self.assertTrue(calculation.validation.valid)
                self.assertEqual(
                    calculation.validation.simulation.completed_job_ids,
                    frozenset({"JOB_IN_NEAR", "JOB_OUT_FAR"}),
                )

    def test_new_jobs_cannot_start_before_decision_time(self) -> None:
        request = self._request(
            CooperationPolicy.NO_SHARING,
            decision_time=100.0,
        )
        instance = build_full_replan_instance(request)
        self.assertEqual(
            instance.jobs_by_id["JOB_OUT_FAR"].release_time,
            100.0,
        )
        self.assertEqual(
            instance.jobs_by_id["JOB_IN_NEAR"].release_time,
            self.instance.jobs_by_id["JOB_IN_NEAR"].release_time,
        )
        calculation = calculate_full_replan_upper_bound(request)
        self.assertTrue(
            calculation.result.upper_bound_validated,
            calculation.result.error,
        )
        new_job_starts = tuple(
            operation.start_time
            for operation in calculation.schedule.operations
            if operation.job_id == "JOB_OUT_FAR"
        )
        self.assertTrue(new_job_starts)
        self.assertGreaterEqual(min(new_job_starts), 100.0)

    def test_merged_calculator_selects_smallest_validated_bound(self) -> None:
        calculation = calculate_upper_bounds(
            self._request(CooperationPolicy.HANDSHAKE_AREA)
        )
        result = calculation.result
        self.assertTrue(result.upper_bound_validated)
        self.assertEqual(
            result.best_known_upper_bound,
            min(
                result.strict_append_upper_bound,
                result.full_replan_upper_bound,
            ),
        )
        self.assertEqual(
            result.makespan_extension,
            result.best_known_upper_bound - result.baseline_makespan,
        )
        self.assertIsNone(result.combined_lower_bound)
        self.assertFalse(result.lower_bound_certified)

    def test_merged_calculator_preserves_both_audit_artifacts(self) -> None:
        calculation = calculate_upper_bounds(
            self._request(CooperationPolicy.ANY_BAY)
        )
        self.assertIsNotNone(calculation.strict_append.combined_schedule)
        self.assertTrue(calculation.strict_append.combined_validation.valid)
        self.assertIsNotNone(calculation.full_replan.schedule)
        self.assertTrue(calculation.full_replan.validation.valid)
        self.assertEqual(len(calculation.result.bound_provenance), 5)

    def test_invalid_replan_does_not_create_a_numeric_bound(self) -> None:
        def invalid_planner(instance, policy):
            return CandidateSchedule(instance.instance_id, policy, ())

        calculation = calculate_full_replan_upper_bound(
            self._request(CooperationPolicy.NO_SHARING),
            planner=invalid_planner,
        )
        self.assertFalse(calculation.result.upper_bound_validated)
        self.assertIsNone(calculation.result.full_replan_upper_bound)
        self.assertIsNone(calculation.result.best_known_upper_bound)
        self.assertIn("failed physical validation", calculation.result.error)


if __name__ == "__main__":
    unittest.main()

