from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    CooperationPolicy,
    DEFAULT_POLICY_PLANNERS,
    action_scenario_dict,
    build_three_policy_comparison_visualization,
    comparison_summary_dict,
    load_instance,
    run_three_policy_comparison,
    write_comparison_bundle,
)


class ThreePolicyComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = ROOT / "data" / "any_bay_handover_micro.json"
        self.instance = load_instance(self.path)

    def test_real_policy_planners_run_on_one_instance(self) -> None:
        comparison = run_three_policy_comparison(self.instance)
        self.assertTrue(comparison.all_valid)
        self.assertFalse(comparison.nested_upper_bounds_hold)
        records = comparison.records_by_policy
        self.assertEqual(
            records[CooperationPolicy.NO_SHARING].planner,
            "build_no_sharing_schedule",
        )
        self.assertEqual(
            records[CooperationPolicy.HANDSHAKE_AREA].planner,
            "build_handshake_area_schedule",
        )
        self.assertEqual(
            records[CooperationPolicy.ANY_BAY].planner,
            "build_any_bay_schedule",
        )
        self.assertAlmostEqual(
            records[
                CooperationPolicy.NO_SHARING
            ].metrics.feasible_upper_bound,
            12.7,
        )
        self.assertAlmostEqual(
            records[
                CooperationPolicy.HANDSHAKE_AREA
            ].metrics.feasible_upper_bound,
            9.9,
        )
        self.assertAlmostEqual(
            records[
                CooperationPolicy.ANY_BAY
            ].metrics.feasible_upper_bound,
            10.9,
        )

    def test_summary_is_json_serializable(self) -> None:
        comparison = run_three_policy_comparison(self.instance)
        summary = comparison_summary_dict(comparison)
        encoded = json.dumps(summary)
        self.assertIn("nested_upper_bounds_hold", encoded)
        self.assertIn("H_ROW_1", encoded)
        self.assertGreaterEqual(
            summary["policies"]["ANY_BAY"]["runtime_seconds"],
            0.0,
        )

    def test_bundle_contains_summary_and_three_schedules(self) -> None:
        comparison = run_three_policy_comparison(self.instance)
        with tempfile.TemporaryDirectory() as directory:
            paths = write_comparison_bundle(comparison, directory)
            self.assertEqual(len(paths), 7)
            self.assertTrue(all(path.exists() for path in paths))
            summary = json.loads(paths[0].read_text(encoding="utf-8"))
            self.assertTrue(summary["all_valid"])
            any_path = next(
                path for path in paths if path.name == "any_bay_schedule.json"
            )
            any_payload = json.loads(any_path.read_text(encoding="utf-8"))
            self.assertEqual(any_payload["policy"], "ANY_BAY")
            self.assertTrue(any_payload["operations"])
            scenario_path = next(
                path for path in paths if path.name == "any_bay_scenario.json"
            )
            scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
            self.assertEqual(scenario["policy"], "ANY_BAY")
            self.assertEqual(
                scenario["execution_model"],
                "EVENT_DEPENDENCY_GRAPH",
            )
            self.assertTrue(scenario["actions"])
            self.assertTrue(
                any(
                    dependency["type"] == "CRANE_SEQUENCE"
                    for dependency in scenario["dependencies"]
                )
            )
            self.assertTrue(
                any(
                    dependency["type"] == "TRANSFER_SLOT_HAS_CONTAINER"
                    for dependency in scenario["dependencies"]
                )
            )

    def test_comparison_replay_uses_exact_exported_scenarios(self) -> None:
        comparison = run_three_policy_comparison(self.instance)
        visualization = build_three_policy_comparison_visualization(
            self.instance,
            comparison,
        )
        views = {view.policy: view for view in visualization.policies}
        self.assertEqual(tuple(views), tuple(CooperationPolicy))
        self.assertEqual(visualization.new_job_ids, ())
        self.assertEqual(
            visualization.existing_job_ids,
            tuple(job.id for job in self.instance.jobs),
        )
        for policy, record in comparison.records_by_policy.items():
            self.assertIsNotNone(record.schedule)
            scenario = action_scenario_dict(record.schedule)
            actions = scenario["actions"]
            operations = views[policy].operations
            self.assertEqual(len(actions), len(operations))
            for action, operation in zip(actions, operations, strict=True):
                self.assertEqual(
                    action["action_id"],
                    f"op_{operation.operation_index:04d}",
                )
                self.assertEqual(
                    action["action_type"],
                    operation.operation_type.value,
                )
                self.assertEqual(action["crane_id"], operation.crane_id)
                self.assertEqual(action["estimated_start_time"], operation.start_time)
                self.assertEqual(action["estimated_end_time"], operation.end_time)
                self.assertEqual(
                    action["from"],
                    {"bay": operation.start_bay, "row": operation.start_row},
                )
                self.assertEqual(
                    action["to"],
                    {"bay": operation.end_bay, "row": operation.end_row},
                )

    def test_one_planner_failure_does_not_hide_other_results(self) -> None:
        planners = dict(DEFAULT_POLICY_PLANNERS)

        def failing_planner(instance, policy):
            raise RuntimeError("intentional failure")

        planners[CooperationPolicy.HANDSHAKE_AREA] = failing_planner
        comparison = run_three_policy_comparison(self.instance, planners)
        records = comparison.records_by_policy
        self.assertFalse(comparison.all_valid)
        self.assertIsNone(comparison.nested_upper_bounds_hold)
        self.assertTrue(records[CooperationPolicy.NO_SHARING].metrics.valid)
        self.assertFalse(
            records[CooperationPolicy.HANDSHAKE_AREA].metrics.valid
        )
        self.assertEqual(
            records[
                CooperationPolicy.HANDSHAKE_AREA
            ].metrics.violation_codes,
            ("PLANNER_ERROR",),
        )
        self.assertTrue(records[CooperationPolicy.ANY_BAY].metrics.valid)


if __name__ == "__main__":
    unittest.main()
