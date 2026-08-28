from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    CooperationPolicy,
    OperationType,
    PlannerInfeasibleError,
    TransferSlotKind,
    build_any_bay_schedule,
    build_per_job_transfer_test_schedule,
    constraints_for,
    evaluate_any_bay_candidates,
    evaluate_per_job_transfer_test_candidates,
    load_instance,
    parse_instance,
    validate_schedule,
)


class AnyBayPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        path = ROOT / "data" / "static_fair_micro.json"
        self.payload = json.loads(path.read_text(encoding="utf-8"))

    def _sea_to_land_gate_job(self):
        self.payload["jobs"] = [
            {
                "id": "JOB_SEA_TO_LAND_GATE",
                "container_id": "CONT_SEA_TO_LAND_GATE",
                "direction": "OUTBOUND",
                "origin": {"bay": 0, "row": 1},
                "destination": {"bay": 7, "row": 1},
                "final_slot": None,
                "release_time": 0.0,
                "agv_ready_time": 0.0,
            }
        ]
        self.payload["initial_state"]["stacks"] = []
        self.payload["initial_state"]["containers"] = [
            {
                "container_id": "CONT_SEA_TO_LAND_GATE",
                "status": "ON_AGV",
                "current_slot": None,
                "target_slot": None,
            }
        ]
        return parse_instance(self.payload)

    def _near_inbound_with_occupied_virtual_stack(self):
        self.payload["jobs"] = [
            {
                "id": "JOB_NEAR_INBOUND",
                "container_id": "CONT_NEAR_INBOUND",
                "direction": "INBOUND",
                "origin": {"bay": 0, "row": 1},
                "destination": {"bay": 2, "row": 1},
                "final_slot": {
                    "block_id": "B1",
                    "bay": 2,
                    "row": 1,
                    "tier": 1,
                },
                "release_time": 0.0,
                "agv_ready_time": 0.0,
            }
        ]
        self.payload["initial_state"]["stacks"] = [
            {
                "block_id": "B1",
                "bay": 5,
                "row": 1,
                "containers": ["STACK_BASE"],
            }
        ]
        self.payload["initial_state"]["containers"] = [
            {
                "container_id": "CONT_NEAR_INBOUND",
                "status": "ON_AGV",
                "current_slot": None,
                "target_slot": {
                    "block_id": "B1",
                    "bay": 2,
                    "row": 1,
                    "tier": 1,
                },
            },
            {
                "container_id": "STACK_BASE",
                "status": "IN_STACK",
                "current_slot": {
                    "block_id": "B1",
                    "bay": 5,
                    "row": 1,
                    "tier": 1,
                },
                "target_slot": None,
            },
        ]
        return parse_instance(self.payload)

    def test_any_bay_candidates_exclude_handshake_fallback(self) -> None:
        instance = parse_instance(self.payload)
        candidates = evaluate_any_bay_candidates(instance)
        self.assertTrue(candidates)
        self.assertTrue(
            all(item.label.startswith("PER_JOB_TRANSFER:") for item in candidates)
        )

    def test_any_bay_selects_best_true_any_point(self) -> None:
        instance = self._sea_to_land_gate_job()
        any_bay = build_any_bay_schedule(instance)
        any_result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.ANY_BAY),
            any_bay,
        )
        self.assertTrue(any_result.valid, any_result.issues)
        transfer_ids = {
            operation.transfer_slot_id
            for operation in any_bay.operations
            if operation.operation_type
            in {OperationType.HANDOVER_DROP, OperationType.HANDOVER_PICKUP}
        }
        self.assertTrue(transfer_ids)
        self.assertTrue(
            all(transfer_id.startswith("VIRTUAL::") for transfer_id in transfer_ids)
        )

    def test_disabled_bay_is_not_used(self) -> None:
        for slot in self.payload["transfer_slots"]:
            if slot["id"] == "T_BAY_4_ROW_1":
                slot["enabled"] = False
        instance = self._sea_to_land_gate_job()
        schedule = build_any_bay_schedule(instance)
        transfer_ids = {
            operation.transfer_slot_id
            for operation in schedule.operations
            if operation.operation_type
            in {OperationType.HANDOVER_DROP, OperationType.HANDOVER_PICKUP}
        }
        self.assertNotIn("T_BAY_4_ROW_1", transfer_ids)
        allowed_ids = constraints_for(
            instance,
            CooperationPolicy.ANY_BAY,
        ).allowed_handover_point_ids
        self.assertTrue(transfer_ids.issubset(allowed_ids))

    def test_virtual_stack_outside_job_corridor_is_valid_and_tier_aware(
        self,
    ) -> None:
        instance = self._near_inbound_with_occupied_virtual_stack()
        points = constraints_for(
            instance,
            CooperationPolicy.ANY_BAY,
        ).transfer_points_by_id
        virtual_id = "VIRTUAL::B1::BAY_5::ROW_1"
        self.assertIs(points[virtual_id].kind, TransferSlotKind.VIRTUAL_STACK)

        schedule = build_per_job_transfer_test_schedule(instance)
        result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.ANY_BAY),
            schedule,
        )
        self.assertTrue(result.valid, result.issues)

    def test_experimental_per_job_transfer_search_uses_multiple_bays(
        self,
    ) -> None:
        instance = load_instance(ROOT / "data" / "large_15out_5in_seed42.json")
        schedule = build_per_job_transfer_test_schedule(instance)
        result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.ANY_BAY),
            schedule,
        )
        self.assertTrue(result.valid, result.issues)
        self.assertAlmostEqual(result.makespan, 284.35)
        self.assertEqual(result.handover_count, 16)

        candidates = {
            item.label: item
            for item in evaluate_per_job_transfer_test_candidates(instance)
        }
        self.assertAlmostEqual(candidates["PER_JOB_TRANSFER:final"].makespan, 284.35)
        self.assertLess(
            candidates["PER_JOB_TRANSFER:final"].makespan,
            369.35,
        )
        transfer_bays = {
            operation.end_position.bay
            for operation in schedule.operations
            if operation.operation_type is OperationType.HANDOVER_DROP
        }
        self.assertGreater(len(transfer_bays), 1)

    def test_wrong_policy_argument_is_rejected(self) -> None:
        instance = parse_instance(self.payload)
        with self.assertRaisesRegex(ValueError, "ANY_BAY only"):
            build_any_bay_schedule(
                instance,
                CooperationPolicy.HANDSHAKE_AREA,
            )


if __name__ == "__main__":
    unittest.main()
