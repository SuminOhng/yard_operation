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
    BOUND_ARTIFACT_SCHEMA_VERSION,
    BoundCalculationRequest,
    CandidateSchedule,
    CooperationPolicy,
    bound_calculation_dict,
    calculate_bounds,
    load_instance,
    write_bound_calculation,
)


class BoundSerializationAndCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.input_path = ROOT / "data" / "static_fair_micro.json"
        self.instance = load_instance(self.input_path)
        self.request = BoundCalculationRequest(
            instance=self.instance,
            policy=CooperationPolicy.NO_SHARING,
            existing_job_ids=("JOB_IN_NEAR",),
            new_job_ids=("JOB_OUT_FAR",),
            decision_time=0.0,
        )
        self.calculation = calculate_bounds(self.request)

    def test_artifact_is_complete_and_json_serializable(self) -> None:
        artifact = bound_calculation_dict(
            self.calculation,
            source_input=self.input_path,
        )
        encoded = json.dumps(artifact, allow_nan=False)
        self.assertTrue(encoded)
        self.assertEqual(
            artifact["schema_version"],
            BOUND_ARTIFACT_SCHEMA_VERSION,
        )
        self.assertEqual(artifact["status"], "COMPLETE")
        self.assertEqual(
            artifact["result"]["best_known_upper_bound"],
            17.0,
        )
        self.assertEqual(
            artifact["result"]["combined_lower_bound"],
            6.0,
        )

    def test_artifact_keeps_schedules_validation_and_metrics(self) -> None:
        artifact = bound_calculation_dict(self.calculation)
        append = artifact["strict_append"]
        combined = append["combined_schedule"]
        self.assertTrue(combined["operations"])
        self.assertTrue(combined["validation"]["valid"])
        self.assertEqual(
            set(combined["validation"]["completed_job_ids"]),
            {"JOB_IN_NEAR", "JOB_OUT_FAR"},
        )
        self.assertIn("busy_seconds_by_crane", combined["metrics"])
        self.assertIsNotNone(append["residual_initial_state"])
        self.assertTrue(
            artifact["full_replan"]["schedule"]["validation"]["valid"]
        )
        self.assertEqual(
            len(artifact["lower_bound"]["job_components"]),
            2,
        )

    def test_atomic_writer_creates_parent_and_leaves_no_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "bound.json"
            written = write_bound_calculation(
                self.calculation,
                output,
                source_input=self.input_path,
            )
            self.assertEqual(written, output)
            self.assertTrue(output.is_file())
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "COMPLETE")
            self.assertEqual(list(output.parent.glob("*.tmp")), [])
            self.assertEqual(list(output.parent.glob(".*.tmp")), [])

    def test_planner_failures_are_saved_without_fake_upper_bounds(self) -> None:
        def invalid_planner(instance, policy):
            return CandidateSchedule(instance.instance_id, policy, ())

        calculation = calculate_bounds(
            self.request,
            planner=invalid_planner,
        )
        artifact = bound_calculation_dict(calculation)
        self.assertEqual(artifact["status"], "LOWER_BOUND_ONLY")
        self.assertIsNone(artifact["result"]["best_known_upper_bound"])
        self.assertIsNotNone(artifact["strict_append"]["error"])
        self.assertIsNotNone(artifact["full_replan"]["error"])

    def test_cli_writes_a_complete_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "cli" / "result.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_bound_calculator.py"),
                    "--input",
                    str(self.input_path),
                    "--policy",
                    "HANDSHAKE_AREA",
                    "--existing-jobs",
                    "JOB_IN_NEAR",
                    "--new-jobs",
                    "JOB_OUT_FAR",
                    "--decision-time",
                    "0",
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
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(console["status"], "COMPLETE")
            self.assertEqual(payload["request"]["policy"], "HANDSHAKE_AREA")
            self.assertEqual(payload["status"], "COMPLETE")

    def test_cli_rejects_an_invalid_job_partition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "invalid.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_bound_calculator.py"),
                    "--input",
                    str(self.input_path),
                    "--policy",
                    "NO_SHARING",
                    "--existing-jobs",
                    "JOB_IN_NEAR",
                    "--new-jobs",
                    "JOB_IN_NEAR",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("BOUND_CALCULATOR_ERROR", completed.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
