from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    VISUALIZATION_SCHEMA_VERSION,
    BoundCalculationRequest,
    CooperationPolicy,
    build_static_schedule_visualization,
    calculate_bounds,
    load_instance,
    visualization_dict,
    write_schedule_visualization_bundle,
)


class StaticScheduleVisualizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.input_path = ROOT / "data" / "static_fair_micro.json"
        cls.instance = load_instance(cls.input_path)
        cls.calculations = tuple(
            calculate_bounds(
                BoundCalculationRequest(
                    instance=cls.instance,
                    policy=policy,
                    existing_job_ids=("JOB_IN_NEAR",),
                    new_job_ids=("JOB_OUT_FAR",),
                    decision_time=0.0,
                )
            )
            for policy in CooperationPolicy
        )
        cls.visualization = build_static_schedule_visualization(
            cls.calculations,
            title="Micro three-policy schedule",
        )

    def test_view_uses_schedule_that_proves_each_best_upper_bound(self) -> None:
        self.assertEqual(
            tuple(item.policy for item in self.visualization.policies),
            tuple(CooperationPolicy),
        )
        for policy in self.visualization.policies:
            self.assertTrue(policy.schedule_valid)
            self.assertTrue(policy.upper_bound_validated)
            self.assertTrue(policy.lower_bound_certified)
            self.assertEqual(
                policy.schedule_makespan,
                policy.best_known_upper_bound,
            )
            self.assertTrue(policy.operations)
            self.assertEqual(
                tuple(operation.operation_index for operation in policy.operations),
                tuple(range(len(policy.operations))),
            )

    def test_json_contains_bounds_and_exact_operation_positions(self) -> None:
        payload = visualization_dict(self.visualization)
        self.assertEqual(
            payload["schema_version"],
            VISUALIZATION_SCHEMA_VERSION,
        )
        self.assertEqual(len(payload["policies"]), 3)
        self.assertEqual(len(payload["route_candidates"]), 3)
        self.assertEqual(len(payload["instance"]["initial_cranes"]), 2)
        self.assertTrue(payload["instance"]["initial_containers"])
        directions = {
            container["container_id"]: container["direction"]
            for container in payload["instance"]["initial_containers"]
        }
        self.assertEqual(directions["CONT_IN_NEAR"], "INBOUND")
        self.assertEqual(directions["CONT_OUT_FAR"], "OUTBOUND")
        first = payload["policies"][0]
        self.assertEqual(first["best_known_upper_bound"], 17.0)
        self.assertEqual(first["combined_lower_bound"], 6.0)
        self.assertIn("start_position", first["operations"][0])
        self.assertIn("end_position", first["operations"][0])
        self.assertIn("state_after", first["operations"][0])
        self.assertIn("accepted", first["operations"][0])
        self.assertIn("transfer_point_kind", first["operations"][0])

    def test_bundle_writes_standalone_html_and_audit_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "visualization"
            paths = write_schedule_visualization_bundle(
                self.visualization,
                output,
            )
            source = paths.index_html.read_text(encoding="utf-8")
            payload = json.loads(paths.data_json.read_text(encoding="utf-8"))
            self.assertIn("<svg id=\"gantt\"", source)
            self.assertIn("<svg id=\"yard-replay\"", source)
            self.assertIn("id=\"route-candidates\"", source)
            self.assertIn("운반 후보 makespan (미채택 포함)", source)
            self.assertIn("미채택 후보", source)
            self.assertIn("실제 ${candidate.policy}", source)
            self.assertIn("id=\"replay-time\"", source)
            self.assertIn("수입 컨테이너 (INBOUND)", source)
            self.assertIn("수출 컨테이너 (OUTBOUND)", source)
            self.assertIn("container-inbound", source)
            self.assertIn("container-outbound", source)
            self.assertIn("고정 Transfer buffer", source)
            self.assertIn("ANY 임시 Stack 인계점", source)
            self.assertIn("usedTransferPoints", source)
            self.assertIn("임시 tier", source)
            self.assertIn("점유 ${formatNumber", source)
            self.assertIn("NO_SHARING", source)
            self.assertNotIn("fetch(", source)
            self.assertEqual(payload["instance"]["instance_id"], self.instance.instance_id)
            self.assertEqual(list(output.glob(".*.tmp")), [])

    def test_true_any_replay_records_only_the_selected_virtual_point(self) -> None:
        instance = load_instance(ROOT / "data" / "true_any_bay_replay_demo.json")
        calculations = tuple(
            calculate_bounds(
                BoundCalculationRequest(
                    instance=instance,
                    policy=policy,
                    existing_job_ids=("JOB_OUTBOUND",),
                    new_job_ids=("JOB_INBOUND",),
                    decision_time=0.0,
                )
            )
            for policy in CooperationPolicy
        )
        payload = visualization_dict(
            build_static_schedule_visualization(calculations)
        )
        any_bay = next(
            item for item in payload["policies"]
            if item["policy"] == "ANY_BAY"
        )
        any_route = next(
            item for item in payload["route_candidates"]
            if item["route_key"] == "ANY_BAY_HANDOVER"
        )
        used = {
            (
                operation["transfer_slot_id"],
                operation["transfer_point_kind"],
            )
            for operation in any_bay["operations"]
            if operation["transfer_slot_id"] is not None
        }
        self.assertEqual(
            used,
            {("H_ROW_1", "FIXED_BUFFER")},
        )
        handover_drop = next(
            operation for operation in any_bay["operations"]
            if operation["operation_type"] == "HANDOVER_DROP"
            and operation["transfer_point_kind"] == "FIXED_BUFFER"
        )
        self.assertEqual(handover_drop["transfer_slot_id"], "H_ROW_1")
        self.assertAlmostEqual(any_bay["best_known_upper_bound"], 11.6)
        self.assertTrue(any_route["selected"])
        self.assertAlmostEqual(any_route["makespan"], 11.6)
        self.assertEqual(any_route["method"], "HANDSHAKE_FALLBACK")

    def test_cli_calculates_three_policies_and_writes_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "cli"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "render_schedule.py"),
                    "--input",
                    str(self.input_path),
                    "--existing-jobs",
                    "JOB_IN_NEAR",
                    "--new-jobs",
                    "JOB_OUT_FAR",
                    "--decision-time",
                    "0",
                    "--output-dir",
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
            self.assertEqual(console["policy_count"], 3)
            self.assertTrue((output / "index.html").is_file())
            self.assertTrue((output / "visualization_data.json").is_file())


if __name__ == "__main__":
    unittest.main()
