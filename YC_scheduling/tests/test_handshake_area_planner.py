from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    CooperationPolicy,
    OperationPurpose,
    OperationType,
    build_handshake_area_schedule,
    build_no_sharing_schedule,
    constraints_for,
    parse_instance,
    validate_schedule,
)


class HandshakeAreaPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        path = ROOT / "data" / "static_fair_micro.json"
        self.payload = json.loads(path.read_text(encoding="utf-8"))

    def _outside_gate_job(self, *, row: int = 2):
        self.payload["jobs"] = [
            {
                "id": "JOB_GATE_TO_GATE",
                "container_id": "CONT_GATE_TO_GATE",
                "direction": "OUTBOUND",
                "origin": {"bay": 7, "row": row},
                "destination": {"bay": 0, "row": row},
                "final_slot": None,
                "release_time": 0.0,
                "agv_ready_time": 0.0,
            }
        ]
        self.payload["initial_state"]["stacks"] = []
        self.payload["initial_state"]["containers"] = [
            {
                "container_id": "CONT_GATE_TO_GATE",
                "status": "ON_AGV",
                "current_slot": None,
                "target_slot": None,
            }
        ]
        return parse_instance(self.payload)

    def test_pipeline_handover_can_improve_the_direct_candidate(self) -> None:
        instance = parse_instance(self.payload)
        direct = build_no_sharing_schedule(instance)
        direct_result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.NO_SHARING),
            direct,
        )
        schedule = build_handshake_area_schedule(instance)
        result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.HANDSHAKE_AREA),
            schedule,
        )
        self.assertTrue(result.valid, result.issues)
        self.assertLess(result.makespan, direct_result.makespan)
        self.assertGreater(result.handover_count, 0)
        self.assertTrue(
            any(
                operation.operation_type
                in {OperationType.HANDOVER_DROP, OperationType.HANDOVER_PICKUP}
                for operation in schedule.operations
            )
        )

    def test_gate_to_gate_job_uses_exactly_one_handover(self) -> None:
        instance = self._outside_gate_job()
        schedule = build_handshake_area_schedule(instance)
        result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.HANDSHAKE_AREA),
            schedule,
        )
        self.assertTrue(result.valid, result.issues)
        self.assertEqual(result.handover_count, 1)
        handovers = [
            operation
            for operation in schedule.operations
            if operation.operation_type
            in {OperationType.HANDOVER_DROP, OperationType.HANDOVER_PICKUP}
        ]
        self.assertEqual(
            [operation.operation_type for operation in handovers],
            [OperationType.HANDOVER_DROP, OperationType.HANDOVER_PICKUP],
        )
        self.assertEqual({operation.crane_id for operation in handovers}, {"C_SEA", "C_LAND"})
        self.assertEqual({operation.start_position.bay for operation in handovers}, {3})

    def test_transfer_row_minimizes_loaded_travel(self) -> None:
        instance = self._outside_gate_job(row=2)
        schedule = build_handshake_area_schedule(instance)
        transfer_ids = {
            operation.transfer_slot_id
            for operation in schedule.operations
            if operation.operation_type
            in {OperationType.HANDOVER_DROP, OperationType.HANDOVER_PICKUP}
        }
        self.assertEqual(transfer_ids, {"H_ROW_2"})

    def test_blocker_is_reshuffled_before_handover_pickup(self) -> None:
        self.payload["jobs"] = [
            job
            for job in self.payload["jobs"]
            if job["id"] == "JOB_OUT_FAR"
        ]
        self.payload["initial_state"]["containers"] = [
            container
            for container in self.payload["initial_state"]["containers"]
            if container["container_id"] == "CONT_OUT_FAR"
        ]
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
        self.payload["motion"]["pickup_seconds"] = 0.1
        self.payload["motion"]["drop_seconds"] = 0.1
        instance = parse_instance(self.payload)
        schedule = build_handshake_area_schedule(instance)
        result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.HANDSHAKE_AREA),
            schedule,
        )
        self.assertTrue(result.valid, result.issues)
        self.assertEqual(result.handover_count, 1)
        reshuffles = [
            operation
            for operation in schedule.operations
            if operation.purpose is OperationPurpose.RESHUFFLE
        ]
        self.assertEqual(len(reshuffles), 3)
        self.assertTrue(
            all(operation.container_id == "BLOCKER_1" for operation in reshuffles)
        )

    def test_wrong_policy_argument_is_rejected(self) -> None:
        instance = parse_instance(self.payload)
        with self.assertRaisesRegex(ValueError, "HANDSHAKE_AREA only"):
            build_handshake_area_schedule(instance, CooperationPolicy.ANY_BAY)


if __name__ == "__main__":
    unittest.main()
