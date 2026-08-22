from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    ContainerStatus,
    CooperationPolicy,
    DomainError,
    Position,
    Slot,
    StackState,
    TransferSlotKind,
    TransferSlotSpec,
    constraints_for,
    load_instance,
    parse_instance,
    run_three_policy_baseline,
    validate_instance,
    validate_policy_lattice,
    virtual_transfer_slots,
)


class PhysicalModelPhaseOneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = ROOT / "data" / "static_fair_micro.json"
        self.instance = load_instance(self.path)

    def test_native_input_builds_structured_yard_state(self) -> None:
        self.assertEqual(self.instance.schema_version, "3.1.0")
        self.assertEqual(self.instance.layout.block_id, "B1")
        self.assertEqual(self.instance.layout.tiers, 4)
        self.assertEqual(len(self.instance.yard.stacks), 12)
        self.assertEqual(len(self.instance.initial_state.stacks), 12)
        self.assertEqual(len(self.instance.jobs), 2)

        layout = self.instance.layout
        self.assertEqual(tuple(layout.working_bays), (1, 2, 3, 4, 5, 6))
        self.assertEqual(layout.seaside_parking_bay, 0)
        self.assertEqual(layout.landside_parking_bay, 7)
        self.assertTrue(layout.is_on_crane_rail(0))
        self.assertTrue(layout.is_on_crane_rail(7))
        self.assertFalse(layout.is_work_bay(0))
        self.assertFalse(layout.is_work_bay(7))

        inbound = self.instance.jobs_by_id["JOB_IN_NEAR"]
        self.assertEqual(inbound.final_slot, Slot("B1", 2, 1, 1))
        container = self.instance.initial_state.containers_by_id[
            "CONT_IN_NEAR"
        ]
        self.assertIs(container.status, ContainerStatus.ON_AGV)
        self.assertEqual(container.target_slot, inbound.final_slot)

    def test_sparse_stack_input_becomes_complete_regular_yard(self) -> None:
        occupied = [
            stack
            for stack in self.instance.initial_state.stacks
            if stack.containers
        ]
        self.assertEqual(len(occupied), 1)
        self.assertEqual(occupied[0].containers, ("CONT_OUT_FAR",))
        self.assertEqual(occupied[0].top_container, "CONT_OUT_FAR")

    def test_stack_capacity_violation_is_rejected(self) -> None:
        target = self.instance.initial_state.stacks[0]
        overflow = replace(
            target,
            containers=("A", "B", "C", "D", "E"),
        )
        state = replace(
            self.instance.initial_state,
            stacks=(overflow,) + self.instance.initial_state.stacks[1:],
        )
        invalid = replace(self.instance, initial_state=state)
        with self.assertRaisesRegex(DomainError, "exceeds capacity"):
            validate_instance(invalid)

    def test_container_tier_must_match_bottom_to_top_stack_order(self) -> None:
        containers = list(self.instance.initial_state.containers)
        outbound_index = next(
            index
            for index, container in enumerate(containers)
            if container.container_id == "CONT_OUT_FAR"
        )
        containers[outbound_index] = replace(
            containers[outbound_index],
            current_slot=Slot("B1", 6, 1, 2),
        )
        invalid = replace(
            self.instance,
            initial_state=replace(
                self.instance.initial_state,
                containers=tuple(containers),
            ),
        )
        with self.assertRaisesRegex(DomainError, "stack location is inconsistent"):
            validate_instance(invalid)

    def test_stacking_target_must_equal_job_final_slot(self) -> None:
        containers = list(self.instance.initial_state.containers)
        inbound_index = next(
            index
            for index, container in enumerate(containers)
            if container.container_id == "CONT_IN_NEAR"
        )
        containers[inbound_index] = replace(
            containers[inbound_index],
            target_slot=Slot("B1", 2, 1, 2),
        )
        invalid = replace(
            self.instance,
            initial_state=replace(
                self.instance.initial_state,
                containers=tuple(containers),
            ),
        )
        with self.assertRaisesRegex(DomainError, "stacking result"):
            validate_instance(invalid)

    def test_loader_rejects_unknown_physical_fields(self) -> None:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["layout"]["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            parse_instance(payload)

    def test_input_transfer_id_cannot_use_reserved_virtual_prefix(self) -> None:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        original_id = payload["transfer_slots"][0]["id"]
        reserved_id = "VIRTUAL::USER_COLLISION"
        payload["transfer_slots"][0]["id"] = reserved_id
        for state in payload["initial_state"]["transfer_slots"]:
            if state["slot_id"] == original_id:
                state["slot_id"] = reserved_id
        with self.assertRaisesRegex(DomainError, "reserved virtual ID prefix"):
            parse_instance(payload)

    def test_unscheduled_blocker_can_be_represented_in_initial_state(self) -> None:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["initial_state"]["stacks"][0]["containers"].append(
            "BLOCKER_1"
        )
        payload["initial_state"]["containers"].append(
            {
                "container_id": "BLOCKER_1",
                "status": "IN_STACK",
                "current_slot": {
                    "block_id": "B1",
                    "bay": 6,
                    "row": 1,
                    "tier": 2
                },
                "target_slot": None
            }
        )
        instance = parse_instance(payload)
        stack = instance.initial_state.stacks_by_key[
            instance.initial_state.containers_by_id[
                "BLOCKER_1"
            ].current_slot.stack_key
        ]
        self.assertEqual(stack.top_container, "BLOCKER_1")

    def test_virtual_transfer_points_are_deterministic_and_skip_fixed_coordinates(
        self,
    ) -> None:
        fixed_slots = (
            TransferSlotSpec(
                "FIXED_ENABLED", Position(1, 1), 2
            ),
            TransferSlotSpec(
                "FIXED_DISABLED", Position(2, 2), 1, enabled=False
            ),
        )

        points = virtual_transfer_slots(self.instance.layout, fixed_slots)

        self.assertEqual(
            tuple(point.id for point in points[:3]),
            (
                "VIRTUAL::B1::BAY_1::ROW_2",
                "VIRTUAL::B1::BAY_2::ROW_1",
                "VIRTUAL::B1::BAY_3::ROW_1",
            ),
        )
        self.assertEqual(len(points), 10)
        self.assertNotIn(Position(1, 1), {point.position for point in points})
        self.assertNotIn(Position(2, 2), {point.position for point in points})
        self.assertTrue(
            all(
                point.kind is TransferSlotKind.VIRTUAL_STACK
                and point.capacity == 1
                and point.enabled
                for point in points
            )
        )

    def test_policy_contract_exposes_fixed_and_virtual_transfer_points(self) -> None:
        validate_policy_lattice(self.instance)
        no = constraints_for(self.instance, CooperationPolicy.NO_SHARING)
        handshake = constraints_for(
            self.instance, CooperationPolicy.HANDSHAKE_AREA
        )
        any_bay = constraints_for(self.instance, CooperationPolicy.ANY_BAY)
        self.assertFalse(no.handover_allowed)
        self.assertEqual(no.transfer_points, ())
        self.assertTrue(handshake.handover_allowed)
        self.assertEqual(no.allowed_handover_bays, frozenset())
        self.assertEqual(handshake.allowed_handover_bays, frozenset({3}))
        self.assertEqual(
            handshake.allowed_handover_point_ids,
            frozenset({"H_ROW_1", "H_ROW_2"}),
        )
        self.assertEqual(
            any_bay.allowed_handover_bays,
            frozenset(self.instance.layout.working_bays),
        )
        self.assertEqual(len(any_bay.transfer_points), 12)
        self.assertEqual(
            any_bay.transfer_points_by_id["H_ROW_1"].kind,
            TransferSlotKind.FIXED_BUFFER,
        )
        self.assertEqual(
            any_bay.transfer_points_by_id[
                "VIRTUAL::B1::BAY_4::ROW_2"
            ].kind,
            TransferSlotKind.VIRTUAL_STACK,
        )
        self.assertNotIn(
            "VIRTUAL::B1::BAY_4::ROW_1",
            any_bay.allowed_handover_point_ids,
        )
        self.assertTrue(
            no.allowed_handover_point_ids
            <= handshake.allowed_handover_point_ids
            <= any_bay.allowed_handover_point_ids
        )

    def test_baseline_still_produces_a_valid_upper_bound(self) -> None:
        outcomes = run_three_policy_baseline(self.instance)
        self.assertTrue(all(item.validation.valid for item in outcomes.values()))
        self.assertEqual(
            {item.feasible_upper_bound for item in outcomes.values()},
            {17.0},
        )


if __name__ == "__main__":
    unittest.main()
