from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    BoundCalculationRequest,
    CandidateSchedule,
    ContainerStatus,
    CooperationPolicy,
    OperationPurpose,
    ResidualStateError,
    Slot,
    build_residual_instance,
    calculate_strict_append_upper_bound,
    load_instance,
)


class BoundPhaseTwoStrictAppendTests(unittest.TestCase):
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

    def test_every_policy_produces_a_valid_strict_append_bound(self) -> None:
        for policy in CooperationPolicy:
            with self.subTest(policy=policy.value):
                calculation = calculate_strict_append_upper_bound(
                    self._request(policy)
                )
                result = calculation.result
                self.assertTrue(result.append_valid, result.error)
                self.assertTrue(result.upper_bound_validated)
                self.assertIsNotNone(result.strict_append_upper_bound)
                self.assertEqual(
                    result.best_known_upper_bound,
                    result.strict_append_upper_bound,
                )
                self.assertTrue(calculation.combined_validation.valid)
                self.assertEqual(
                    calculation.combined_validation.simulation.completed_job_ids,
                    frozenset({"JOB_IN_NEAR", "JOB_OUT_FAR"}),
                )

    def test_residual_state_preserves_inbound_container_as_stack_occupancy(self) -> None:
        calculation = calculate_strict_append_upper_bound(
            self._request(CooperationPolicy.NO_SHARING)
        )
        self.assertTrue(calculation.result.append_valid, calculation.result.error)
        residual = calculation.residual_instance
        container = residual.initial_state.containers_by_id["CONT_IN_NEAR"]
        self.assertIs(container.status, ContainerStatus.IN_STACK)
        self.assertIsNotNone(container.current_slot)
        self.assertIn(
            container.container_id,
            residual.initial_state.stacks_by_key[
                container.current_slot.stack_key
            ].containers,
        )

    def test_decision_time_delays_only_the_appended_plan(self) -> None:
        calculation = calculate_strict_append_upper_bound(
            self._request(
                CooperationPolicy.HANDSHAKE_AREA,
                decision_time=100.0,
            )
        )
        self.assertTrue(calculation.result.append_valid, calculation.result.error)
        self.assertEqual(calculation.residual_instance.initial_state.current_time, 100.0)
        self.assertGreaterEqual(
            min(operation.start_time for operation in calculation.new_schedule.operations),
            100.0,
        )
        self.assertLess(
            calculation.result.baseline_operation_horizon,
            100.0,
        )

    def test_bound_keeps_baseline_horizon_and_extension_separate(self) -> None:
        calculation = calculate_strict_append_upper_bound(
            self._request(CooperationPolicy.ANY_BAY)
        )
        result = calculation.result
        self.assertTrue(result.append_valid, result.error)
        self.assertAlmostEqual(
            result.makespan_extension,
            result.strict_append_upper_bound - result.baseline_makespan,
        )
        self.assertEqual(len(result.bound_provenance), 3)
        self.assertIsNone(result.combined_lower_bound)
        self.assertFalse(result.lower_bound_certified)

    def test_invalid_custom_planner_is_reported_without_a_fake_bound(self) -> None:
        def invalid_planner(instance, policy):
            return CandidateSchedule(instance.instance_id, policy, ())

        calculation = calculate_strict_append_upper_bound(
            self._request(CooperationPolicy.NO_SHARING),
            planner=invalid_planner,
        )
        self.assertFalse(calculation.result.append_valid)
        self.assertFalse(calculation.result.upper_bound_validated)
        self.assertIsNone(calculation.result.strict_append_upper_bound)
        self.assertIn("existing schedule failed", calculation.result.error)

    def test_residual_builder_rejects_time_before_replay_end(self) -> None:
        calculation = calculate_strict_append_upper_bound(
            self._request(CooperationPolicy.NO_SHARING)
        )
        self.assertTrue(calculation.result.append_valid, calculation.result.error)
        final_state = calculation.existing_validation.simulation.final_state
        with self.assertRaisesRegex(ResidualStateError, "must not precede"):
            build_residual_instance(
                self.instance,
                ("JOB_OUT_FAR",),
                final_state,
                continuation_time=final_state.current_time - 1.0,
            )

    def test_completed_inbound_can_be_reshuffled_as_new_job_blocker(self) -> None:
        target = Slot("B1", 6, 1, 2)
        jobs = tuple(
            replace(job, destination=target.position, final_slot=target)
            if job.id == "JOB_IN_NEAR"
            else job
            for job in self.instance.jobs
        )
        containers = tuple(
            replace(container, target_slot=target)
            if container.container_id == "CONT_IN_NEAR"
            else container
            for container in self.instance.initial_state.containers
        )
        instance = replace(
            self.instance,
            instance_id="STRICT_APPEND_BLOCKER",
            jobs=jobs,
            initial_state=replace(
                self.instance.initial_state,
                containers=containers,
            ),
        )
        request = BoundCalculationRequest(
            instance=instance,
            policy=CooperationPolicy.NO_SHARING,
            existing_job_ids=("JOB_IN_NEAR",),
            new_job_ids=("JOB_OUT_FAR",),
            decision_time=0.0,
        )
        calculation = calculate_strict_append_upper_bound(request)
        self.assertTrue(calculation.result.append_valid, calculation.result.error)
        self.assertTrue(
            any(
                operation.purpose is OperationPurpose.RESHUFFLE
                for operation in calculation.new_schedule.operations
            )
        )
        self.assertTrue(calculation.combined_validation.valid)


if __name__ == "__main__":
    unittest.main()
