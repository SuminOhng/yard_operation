from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    CooperationPolicy,
    JobRegion,
    OperationPurpose,
    OperationType,
    build_no_sharing_schedule,
    classify_job,
    constraints_for,
    parse_instance,
    validate_schedule,
)


class NoSharingPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        path = ROOT / "data" / "static_fair_micro.json"
        self.payload = json.loads(path.read_text(encoding="utf-8"))

    def test_job_regions_are_explicit(self) -> None:
        instance = parse_instance(self.payload)
        self.assertIs(
            classify_job(instance, instance.jobs_by_id["JOB_IN_NEAR"]),
            JobRegion.SEA_LOCAL,
        )
        self.assertIs(
            classify_job(instance, instance.jobs_by_id["JOB_OUT_FAR"]),
            JobRegion.CROSS_REGION,
        )

    def test_two_local_jobs_use_both_cranes_concurrently(self) -> None:
        self.payload["jobs"][1]["destination"] = {"bay": 7, "row": 1}
        instance = parse_instance(self.payload)
        schedule = build_no_sharing_schedule(instance)
        validation = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.NO_SHARING),
            schedule,
        )
        self.assertTrue(validation.valid, validation.issues)
        self.assertEqual(
            {operation.crane_id for operation in schedule.operations},
            {"C_SEA", "C_LAND"},
        )
        sea_end = max(
            operation.end_time
            for operation in schedule.operations
            if operation.crane_id == "C_SEA"
        )
        land_start = min(
            operation.start_time
            for operation in schedule.operations
            if operation.crane_id == "C_LAND"
        )
        self.assertLess(land_start, sea_end)
        self.assertEqual(validation.handover_count, 0)

    def test_cross_region_job_runs_with_other_crane_parked(self) -> None:
        instance = parse_instance(self.payload)
        schedule = build_no_sharing_schedule(instance)
        validation = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.NO_SHARING),
            schedule,
        )
        self.assertTrue(validation.valid, validation.issues)
        self.assertEqual(validation.makespan, 17.0)
        self.assertEqual(validation.handover_count, 0)

    def test_blocker_is_automatically_reshuffled(self) -> None:
        self.payload["initial_state"]["stacks"][0]["containers"].append(
            "BLOCKER_1"
        )
        self.payload["initial_state"]["containers"].append(
            {
                "container_id": "BLOCKER_1",
                "status": "IN_STACK",
                "current_slot": {
                    "block_id": "B1",
                    "bay": 6,
                    "row": 1,
                    "tier": 2,
                },
                "target_slot": None,
            }
        )
        instance = parse_instance(self.payload)
        schedule = build_no_sharing_schedule(instance)
        validation = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.NO_SHARING),
            schedule,
        )
        self.assertTrue(validation.valid, validation.issues)
        reshuffles = [
            operation
            for operation in schedule.operations
            if operation.purpose is OperationPurpose.RESHUFFLE
        ]
        self.assertEqual(len(reshuffles), 3)
        self.assertTrue(
            all(operation.container_id == "BLOCKER_1" for operation in reshuffles)
        )
        self.assertEqual(validation.handover_count, 0)

    def test_landside_idle_crane_pre_reshuffles_future_cross_blocker(self) -> None:
        self.payload["initial_state"]["stacks"] = [
            {
                "block_id": "B1",
                "bay": 2,
                "row": 1,
                "containers": ["CONT_MID"],
            },
            {
                "block_id": "B1",
                "bay": 6,
                "row": 1,
                "containers": ["CONT_OUT_FAR", "BLOCKER_1"],
            },
        ]
        self.payload["initial_state"]["containers"] = [
            {
                "container_id": "CONT_MID",
                "status": "IN_STACK",
                "current_slot": {
                    "block_id": "B1",
                    "bay": 2,
                    "row": 1,
                    "tier": 1,
                },
                "target_slot": None,
            },
            {
                "container_id": "CONT_OUT_FAR",
                "status": "IN_STACK",
                "current_slot": {
                    "block_id": "B1",
                    "bay": 6,
                    "row": 1,
                    "tier": 1,
                },
                "target_slot": None,
            },
            {
                "container_id": "BLOCKER_1",
                "status": "IN_STACK",
                "current_slot": {
                    "block_id": "B1",
                    "bay": 6,
                    "row": 1,
                    "tier": 2,
                },
                "target_slot": None,
            },
        ]
        self.payload["jobs"] = [
            {
                "id": "JOB_MID_CROSS",
                "container_id": "CONT_MID",
                "direction": "OUTBOUND",
                "origin": {"bay": 2, "row": 1},
                "destination": {"bay": 5, "row": 1},
                "final_slot": None,
                "release_time": 0.0,
                "agv_ready_time": 0.0,
            },
            {
                "id": "JOB_OUT_FAR",
                "container_id": "CONT_OUT_FAR",
                "direction": "OUTBOUND",
                "origin": {"bay": 6, "row": 1},
                "destination": {"bay": 0, "row": 1},
                "final_slot": None,
                "release_time": 0.0,
                "agv_ready_time": 0.0,
            },
        ]
        instance = parse_instance(self.payload)
        schedule = build_no_sharing_schedule(instance)
        validation = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.NO_SHARING),
            schedule,
        )
        self.assertTrue(validation.valid, validation.issues)
        blocker_reshuffles = [
            operation
            for operation in schedule.operations
            if operation.purpose is OperationPurpose.RESHUFFLE
            and operation.container_id == "BLOCKER_1"
        ]
        self.assertEqual(len(blocker_reshuffles), 3)
        self.assertTrue(
            all(operation.crane_id == "C_LAND" for operation in blocker_reshuffles)
        )
        self.assertLess(
            max(operation.end_time for operation in blocker_reshuffles),
            min(
                operation.start_time
                for operation in schedule.operations
                if operation.job_id == "JOB_OUT_FAR"
                and operation.operation_type is OperationType.PICKUP
            ),
        )
        self.assertEqual(validation.handover_count, 0)

if __name__ == "__main__":
    unittest.main()
