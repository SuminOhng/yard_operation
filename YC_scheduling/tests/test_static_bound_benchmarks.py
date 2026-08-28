from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = ROOT / "data" / "benchmarks"
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    BoundCalculationRequest,
    CooperationPolicy,
    MoveDirection,
    OperationPurpose,
    OperationType,
    calculate_bounds,
    load_instance,
)


class StaticBoundBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        manifest = json.loads(
            (BENCHMARK_DIR / "benchmark_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        cls.manifest = manifest
        cls.entries = {
            entry["id"]: entry for entry in manifest["benchmarks"]
        }
        cls.instances = {}
        cls.calculations = {}
        for benchmark_id, entry in cls.entries.items():
            instance = load_instance(BENCHMARK_DIR / entry["instance_file"])
            cls.instances[benchmark_id] = instance
            for policy in CooperationPolicy:
                request = BoundCalculationRequest(
                    instance=instance,
                    policy=policy,
                    existing_job_ids=tuple(entry["existing_job_ids"]),
                    new_job_ids=tuple(entry["new_job_ids"]),
                    decision_time=entry["decision_time"],
                )
                cls.calculations[(benchmark_id, policy)] = calculate_bounds(
                    request
                )

    def test_manifest_defines_exactly_five_complete_partitions(self) -> None:
        self.assertEqual(self.manifest["schema_version"], "1.0.0")
        self.assertEqual(len(self.entries), 5)
        for benchmark_id, entry in self.entries.items():
            with self.subTest(benchmark=benchmark_id):
                instance = self.instances[benchmark_id]
                existing = set(entry["existing_job_ids"])
                new = set(entry["new_job_ids"])
                self.assertFalse(existing & new)
                self.assertEqual(existing | new, set(instance.jobs_by_id))
                self.assertEqual(entry["job_count"], len(instance.jobs))
                self.assertGreaterEqual(len(instance.jobs), 4)
                self.assertLessEqual(len(instance.jobs), 6)

    def test_manifest_policy_outcomes_match_calculator_results(self) -> None:
        for benchmark_id, entry in self.entries.items():
            complete = set(entry["expected_complete_policies"])
            infeasible = set(entry["expected_infeasible_policies"])
            for policy in CooperationPolicy:
                with self.subTest(benchmark=benchmark_id, policy=policy.value):
                    result = self.calculations[(benchmark_id, policy)].result
                    if policy.value in complete:
                        self.assertTrue(result.upper_bound_validated, result.error)
                        self.assertTrue(result.lower_bound_certified, result.error)
                        self.assertIsNone(result.error)
                        self.assertLessEqual(
                            result.combined_lower_bound,
                            result.best_known_upper_bound,
                        )
                    elif policy.value in infeasible:
                        self.assertFalse(result.upper_bound_validated)
                        self.assertTrue(result.lower_bound_certified)
                        self.assertIsNone(result.best_known_upper_bound)
                        self.assertIsNotNone(result.error)
                    else:
                        self.fail(
                            f"{benchmark_id}/{policy.value} has no expectation"
                        )

    def test_balanced_local_case_uses_no_handover(self) -> None:
        benchmark_id = "BALANCED_LOCAL_4"
        for policy in CooperationPolicy:
            calculation = self.calculations[(benchmark_id, policy)]
            validation = calculation.upper_bounds.full_replan.validation
            self.assertTrue(validation.valid)
            self.assertEqual(validation.handover_count, 0)

    def test_edge_to_edge_case_is_feasible_for_all_policies(self) -> None:
        benchmark_id = "HANDSHAKE_CROSS_4"
        no_sharing = self.calculations[
            (benchmark_id, CooperationPolicy.NO_SHARING)
        ]
        self.assertTrue(no_sharing.result.upper_bound_validated)
        self.assertEqual(
            no_sharing.upper_bounds.full_replan.validation.handover_count,
            0,
        )
        for policy in CooperationPolicy:
            calculation = self.calculations[(benchmark_id, policy)]
            validation = calculation.upper_bounds.full_replan.validation
            self.assertTrue(validation.valid)
            self.assertEqual(validation.handover_count, 0)
        handshake_schedule = self.calculations[
            (benchmark_id, CooperationPolicy.HANDSHAKE_AREA)
        ].upper_bounds.full_replan.schedule
        self.assertTrue(
            all(
                operation.transfer_slot_id in {None, "H_R1", "H_R2"}
                for operation in handshake_schedule.operations
            )
        )

    def test_any_bay_case_selects_virtual_slot_independently(self) -> None:
        benchmark_id = "ANY_BAY_ADVANTAGE_4"
        baselines = {
            policy: self.calculations[
                (benchmark_id, policy)
            ].result.baseline_makespan
            for policy in CooperationPolicy
        }
        self.assertGreater(
            baselines[CooperationPolicy.ANY_BAY],
            baselines[CooperationPolicy.HANDSHAKE_AREA],
        )
        self.assertLess(
            baselines[CooperationPolicy.HANDSHAKE_AREA],
            baselines[CooperationPolicy.NO_SHARING],
        )
        existing_schedule = self.calculations[
            (benchmark_id, CooperationPolicy.ANY_BAY)
        ].upper_bounds.strict_append.existing_schedule
        used_slots = {
            operation.transfer_slot_id
            for operation in existing_schedule.operations
            if operation.transfer_slot_id is not None
        }
        self.assertEqual(
            used_slots,
            {"VIRTUAL::B1::BAY_2::ROW_1"},
        )

    def test_append_blocker_case_requires_reshuffles(self) -> None:
        benchmark_id = "APPEND_BLOCKER_4"
        for policy in CooperationPolicy:
            schedule = self.calculations[
                (benchmark_id, policy)
            ].upper_bounds.strict_append.new_schedule
            reshuffles = sum(
                operation.purpose is OperationPurpose.RESHUFFLE
                and operation.operation_type is OperationType.PICKUP
                for operation in schedule.operations
            )
            self.assertGreaterEqual(reshuffles, 2)

    def test_mixed_case_contains_both_directions_and_unscheduled_blocker(self) -> None:
        benchmark_id = "MIXED_RESHUFFLE_6"
        instance = self.instances[benchmark_id]
        self.assertEqual(
            {job.direction for job in instance.jobs},
            {MoveDirection.INBOUND, MoveDirection.OUTBOUND},
        )
        self.assertIn(
            "CONT_UNSCHEDULED_BLOCKER",
            instance.initial_state.containers_by_id,
        )
        job_container_ids = {job.container_id for job in instance.jobs}
        self.assertNotIn("CONT_UNSCHEDULED_BLOCKER", job_container_ids)
        for policy in CooperationPolicy:
            schedule = self.calculations[
                (benchmark_id, policy)
            ].upper_bounds.strict_append.combined_schedule
            reshuffles = sum(
                operation.purpose is OperationPurpose.RESHUFFLE
                and operation.operation_type is OperationType.PICKUP
                for operation in schedule.operations
            )
            self.assertGreaterEqual(reshuffles, 1)


if __name__ == "__main__":
    unittest.main()
