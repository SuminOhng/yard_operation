from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "benchmarks" / "benchmark_manifest.json"
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    BATCH_SUMMARY_SCHEMA_VERSION,
    BenchmarkManifestError,
    batch_summary_dict,
    load_benchmark_manifest,
    run_bound_batch,
    write_bound_batch_bundle,
)


class BoundBatchRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = load_benchmark_manifest(MANIFEST_PATH)
        cls.batch = run_bound_batch(cls.manifest)

    def test_manifest_loader_returns_typed_scenarios(self) -> None:
        self.assertEqual(self.manifest.schema_version, "1.0.0")
        self.assertEqual(len(self.manifest.scenarios), 5)
        self.assertTrue(self.manifest.source_path.is_absolute())
        self.assertTrue(
            all(scenario.instance_path.is_file() for scenario in self.manifest.scenarios)
        )

    def test_batch_runs_fifteen_policy_cases_and_matches_expectations(self) -> None:
        self.assertEqual(len(self.batch.records), 15)
        self.assertEqual(self.batch.complete_count, 15)
        self.assertTrue(self.batch.all_expectations_met)
        mismatches = [
            record for record in self.batch.records if not record.expectation_met
        ]
        self.assertEqual(mismatches, [])

    def test_summary_contains_metrics_and_edge_case_complete_record(self) -> None:
        summary = batch_summary_dict(self.batch)
        json.dumps(summary, allow_nan=False)
        self.assertEqual(
            summary["schema_version"], BATCH_SUMMARY_SCHEMA_VERSION
        )
        self.assertEqual(summary["record_count"], 15)
        self.assertEqual(summary["expectation_match_count"], 15)
        gate_no_sharing = next(
            row
            for row in summary["records"]
            if row["scenario_id"] == "HANDSHAKE_CROSS_4"
            and row["policy"] == "NO_SHARING"
        )
        self.assertEqual(gate_no_sharing["expected_outcome"], "COMPLETE")
        self.assertEqual(gate_no_sharing["actual_status"], "COMPLETE")
        self.assertIsNotNone(gate_no_sharing["best_known_upper_bound"])
        self.assertIsNone(gate_no_sharing["error"])

    def test_bundle_writes_fifteen_artifacts_and_three_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = write_bound_batch_bundle(self.batch, directory)
            self.assertEqual(len(paths.calculation_artifacts), 15)
            self.assertTrue(all(path.is_file() for path in paths.calculation_artifacts))
            self.assertTrue(paths.summary_json.is_file())
            self.assertTrue(paths.summary_csv.is_file())
            self.assertTrue(paths.summary_markdown.is_file())

            summary = json.loads(
                paths.summary_json.read_text(encoding="utf-8")
            )
            self.assertTrue(summary["all_expectations_met"])
            with paths.summary_csv.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 15)
            markdown = paths.summary_markdown.read_text(encoding="utf-8")
            self.assertIn("# Bound Batch Summary", markdown)
            self.assertIn("ANY_BAY_ADVANTAGE_4", markdown)
            self.assertIn("HANDSHAKE_CROSS_4", markdown)

    def test_cli_executes_the_manifest_and_writes_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "batch"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "run_bound_batch.py"),
                    "--manifest",
                    str(MANIFEST_PATH),
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
            self.assertEqual(console["policy_run_count"], 15)
            self.assertEqual(console["complete_run_count"], 15)
            self.assertEqual(console["artifact_count"], 15)
            self.assertTrue((output / "batch_summary.json").is_file())

    def test_bundle_rejects_a_nonempty_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "occupied"
            output.mkdir()
            (output / "old_summary.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "absent or empty"):
                write_bound_batch_bundle(self.batch, output)

    def test_manifest_loader_rejects_unclassified_policies(self) -> None:
        payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        for entry in payload["benchmarks"]:
            entry["instance_file"] = str(
                MANIFEST_PATH.parent / entry["instance_file"]
            )
        payload["benchmarks"][0]["expected_complete_policies"] = [
            "NO_SHARING"
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad_manifest.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                BenchmarkManifestError,
                "classify every cooperation policy",
            ):
                load_benchmark_manifest(path)


if __name__ == "__main__":
    unittest.main()
