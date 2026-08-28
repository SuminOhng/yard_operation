from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    CandidateSchedule,
    ContainerState,
    ContainerStatus,
    CooperationPolicy,
    OperationPurpose,
    OperationType,
    Position,
    ScheduledOperation,
    Slot,
    TransferSlotState,
    constraints_for,
    load_instance,
    parse_instance,
    run_policy,
    validate_instance,
    validate_schedule,
)
from yard_crane_v3.simulation.engine import _validate_operation_start
from yard_crane_v3.simulation.working_state import WorkingState


class PhysicalSimulatorPhaseTwoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = ROOT / "data" / "static_fair_micro.json"
        self.instance = load_instance(self.path)

    def test_valid_baseline_changes_stack_container_and_crane_state(self) -> None:
        outcome = run_policy(self.instance, CooperationPolicy.NO_SHARING)
        self.assertTrue(outcome.validation.valid, outcome.validation.issues)
        simulation = outcome.validation.simulation
        self.assertEqual(
            simulation.completed_job_ids,
            frozenset({"JOB_IN_NEAR", "JOB_OUT_FAR"}),
        )
        final = simulation.final_state
        inbound = final.containers_by_id["CONT_IN_NEAR"]
        outbound = final.containers_by_id["CONT_OUT_FAR"]
        self.assertIs(inbound.status, ContainerStatus.IN_STACK)
        self.assertEqual(inbound.current_slot, Slot("B1", 2, 1, 1))
        self.assertIs(outbound.status, ContainerStatus.COMPLETED)
        self.assertIsNone(outbound.current_slot)
        self.assertEqual(
            final.stacks_by_key[Slot("B1", 2, 1, 1).stack_key].containers,
            ("CONT_IN_NEAR",),
        )
        self.assertEqual(
            final.stacks_by_key[Slot("B1", 6, 1, 1).stack_key].containers,
            (),
        )
        self.assertEqual(final.cranes_by_id["C_SEA"].position, Position(0, 1))

    def test_blocked_pickup_is_rejected_by_replay(self) -> None:
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
                    "tier": 2,
                },
                "target_slot": None,
            }
        )
        instance = parse_instance(payload)
        outcome = run_policy(instance, CooperationPolicy.NO_SHARING)
        codes = {
            violation.code
            for violation in outcome.validation.simulation.violations
        }
        self.assertFalse(outcome.validation.valid)
        self.assertIn("BLOCKED_BY_CONTAINER", codes)
        self.assertNotIn(
            "JOB_OUT_FAR", outcome.validation.simulation.completed_job_ids
        )

    def test_drop_to_non_next_target_tier_is_rejected(self) -> None:
        jobs = list(self.instance.jobs)
        inbound_index = next(
            index for index, job in enumerate(jobs) if job.id == "JOB_IN_NEAR"
        )
        jobs[inbound_index] = replace(
            jobs[inbound_index], final_slot=Slot("B1", 2, 1, 2)
        )
        containers = list(self.instance.initial_state.containers)
        container_index = next(
            index
            for index, container in enumerate(containers)
            if container.container_id == "CONT_IN_NEAR"
        )
        containers[container_index] = replace(
            containers[container_index], target_slot=Slot("B1", 2, 1, 2)
        )
        instance = replace(
            self.instance,
            jobs=tuple(jobs),
            initial_state=replace(
                self.instance.initial_state, containers=tuple(containers)
            ),
        )
        validate_instance(instance)
        outcome = run_policy(instance, CooperationPolicy.NO_SHARING)
        codes = {
            violation.code
            for violation in outcome.validation.simulation.violations
        }
        self.assertFalse(outcome.validation.valid)
        self.assertIn("TARGET_TIER_NOT_NEXT", codes)

    def _single_far_inbound_instance(self):
        inbound = self.instance.jobs_by_id["JOB_IN_NEAR"]
        inbound = replace(
            inbound,
            destination=Position(5, 1),
            final_slot=Slot("B1", 5, 1, 1),
        )
        containers = tuple(
            replace(container, target_slot=Slot("B1", 5, 1, 1))
            if container.container_id == "CONT_IN_NEAR"
            else container
            for container in self.instance.initial_state.containers
        )
        instance = replace(
            self.instance,
            jobs=(inbound,),
            initial_state=replace(
                self.instance.initial_state, containers=containers
            ),
        )
        validate_instance(instance)
        return instance

    def _valid_handover_schedule(self, instance) -> CandidateSchedule:
        p0, p2, p3, p4, p5, p7 = (
            Position(0, 1),
            Position(2, 1),
            Position(3, 1),
            Position(4, 1),
            Position(5, 1),
            Position(7, 1),
        )
        return CandidateSchedule(
            instance.instance_id,
            CooperationPolicy.HANDSHAKE_AREA,
            (
                ScheduledOperation("C_SEA", OperationType.PICKUP, 0, 1, p0, p0, "JOB_IN_NEAR"),
                ScheduledOperation("C_SEA", OperationType.MOVE_LOADED, 1, 4, p0, p3, "JOB_IN_NEAR"),
                ScheduledOperation("C_SEA", OperationType.HANDOVER_DROP, 4, 5, p3, p3, "JOB_IN_NEAR", "H_ROW_1", purpose=OperationPurpose.HANDOVER),
                ScheduledOperation("C_SEA", OperationType.MOVE_EMPTY, 5, 6, p3, p2),
                ScheduledOperation("C_LAND", OperationType.MOVE_EMPTY, 0, 3, p7, p4),
                ScheduledOperation("C_LAND", OperationType.WAIT, 3, 6, p4, p4),
                ScheduledOperation("C_LAND", OperationType.MOVE_EMPTY, 6, 7, p4, p3),
                ScheduledOperation("C_LAND", OperationType.HANDOVER_PICKUP, 7, 8, p3, p3, "JOB_IN_NEAR", "H_ROW_1", purpose=OperationPurpose.HANDOVER),
                ScheduledOperation("C_LAND", OperationType.MOVE_LOADED, 8, 10, p3, p5, "JOB_IN_NEAR"),
                ScheduledOperation("C_LAND", OperationType.FINAL_DROP, 10, 11.5, p5, p5, "JOB_IN_NEAR"),
            ),
        )

    def _valid_virtual_handover_schedule(
        self, instance
    ) -> CandidateSchedule:
        p0 = Position(0, 1)
        p3 = Position(3, 2)
        p4 = Position(4, 2)
        p5_row_1 = Position(5, 1)
        p5_row_2 = Position(5, 2)
        p7 = Position(7, 1)
        point_id = "VIRTUAL::B1::BAY_4::ROW_2"
        return CandidateSchedule(
            instance.instance_id,
            CooperationPolicy.ANY_BAY,
            (
                ScheduledOperation(
                    "C_SEA", OperationType.PICKUP, 0, 1, p0, p0,
                    "JOB_IN_NEAR",
                ),
                ScheduledOperation(
                    "C_SEA", OperationType.MOVE_LOADED, 1, 5, p0, p4,
                    "JOB_IN_NEAR",
                ),
                ScheduledOperation(
                    "C_SEA", OperationType.HANDOVER_DROP, 5, 6.5, p4,
                    p4, "JOB_IN_NEAR", point_id,
                    purpose=OperationPurpose.HANDOVER,
                ),
                ScheduledOperation(
                    "C_SEA", OperationType.MOVE_EMPTY, 6.5, 7.5, p4,
                    p3,
                ),
                ScheduledOperation(
                    "C_LAND", OperationType.MOVE_EMPTY, 0, 2, p7,
                    p5_row_2,
                ),
                ScheduledOperation(
                    "C_LAND", OperationType.WAIT, 2, 7.5, p5_row_2,
                    p5_row_2,
                ),
                ScheduledOperation(
                    "C_LAND", OperationType.MOVE_EMPTY, 7.5, 8.5,
                    p5_row_2, p4,
                ),
                ScheduledOperation(
                    "C_LAND", OperationType.HANDOVER_PICKUP, 8.5, 10,
                    p4, p4, "JOB_IN_NEAR", point_id,
                    purpose=OperationPurpose.HANDOVER,
                ),
                ScheduledOperation(
                    "C_LAND", OperationType.MOVE_LOADED, 10, 11, p4,
                    p5_row_1, "JOB_IN_NEAR",
                ),
                ScheduledOperation(
                    "C_LAND", OperationType.FINAL_DROP, 11, 12.5,
                    p5_row_1, p5_row_1, "JOB_IN_NEAR",
                ),
            ),
        )

    def test_valid_handover_updates_transfer_and_final_stack(self) -> None:
        instance = self._single_far_inbound_instance()
        result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.HANDSHAKE_AREA),
            self._valid_handover_schedule(instance),
        )
        self.assertTrue(result.valid, result.issues)
        self.assertEqual(result.makespan, 11.5)
        final = result.simulation.final_state
        self.assertEqual(
            final.transfer_slots_by_id["H_ROW_1"].containers, ()
        )
        self.assertEqual(
            final.stacks_by_key[Slot("B1", 5, 1, 1).stack_key].containers,
            ("CONT_IN_NEAR",),
        )
        self.assertIs(
            final.containers_by_id["CONT_IN_NEAR"].status,
            ContainerStatus.IN_STACK,
        )

    def test_stack_backed_handover_uses_next_tier_and_preserves_base(self) -> None:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["transfer_slots"][0]["kind"] = "STACK_BACKED"
        payload["initial_state"]["stacks"].append(
            {
                "block_id": "B1",
                "bay": 3,
                "row": 1,
                "containers": ["H_BASE"],
            }
        )
        payload["initial_state"]["containers"].append(
            {
                "container_id": "H_BASE",
                "status": "IN_STACK",
                "current_slot": {
                    "block_id": "B1",
                    "bay": 3,
                    "row": 1,
                    "tier": 1,
                },
                "target_slot": None,
            }
        )
        instance = self._single_far_inbound_instance_from_payload(payload)
        p0, p2, p3, p4, p5, p7 = (
            Position(0, 1),
            Position(2, 1),
            Position(3, 1),
            Position(4, 1),
            Position(5, 1),
            Position(7, 1),
        )
        schedule = CandidateSchedule(
            instance.instance_id,
            CooperationPolicy.HANDSHAKE_AREA,
            (
                ScheduledOperation("C_SEA", OperationType.PICKUP, 0, 1, p0, p0, "JOB_IN_NEAR"),
                ScheduledOperation("C_SEA", OperationType.MOVE_LOADED, 1, 4, p0, p3, "JOB_IN_NEAR"),
                ScheduledOperation("C_SEA", OperationType.HANDOVER_DROP, 4, 6, p3, p3, "JOB_IN_NEAR", "H_ROW_1", purpose=OperationPurpose.HANDOVER),
                ScheduledOperation("C_SEA", OperationType.MOVE_EMPTY, 6, 7, p3, p2),
                ScheduledOperation("C_LAND", OperationType.MOVE_EMPTY, 0, 3, p7, p4),
                ScheduledOperation("C_LAND", OperationType.WAIT, 3, 7, p4, p4),
                ScheduledOperation("C_LAND", OperationType.MOVE_EMPTY, 7, 8, p4, p3),
                ScheduledOperation("C_LAND", OperationType.HANDOVER_PICKUP, 8, 10, p3, p3, "JOB_IN_NEAR", "H_ROW_1", purpose=OperationPurpose.HANDOVER),
                ScheduledOperation("C_LAND", OperationType.MOVE_LOADED, 10, 12, p3, p5, "JOB_IN_NEAR"),
                ScheduledOperation("C_LAND", OperationType.FINAL_DROP, 12, 13.5, p5, p5, "JOB_IN_NEAR"),
            ),
        )

        result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.HANDSHAKE_AREA),
            schedule,
        )

        self.assertTrue(result.valid, result.issues)
        h_slot = Slot("B1", 3, 1, 2)
        self.assertEqual(
            result.simulation.final_state.stacks_by_key[h_slot.stack_key].containers,
            ("H_BASE",),
        )
        drop_delta = result.simulation.operation_traces[2].state_delta
        pickup_delta = result.simulation.operation_traces[7].state_delta
        self.assertEqual(drop_delta.container_slot_after, h_slot)
        self.assertEqual(drop_delta.stack_changes[0].after, ("H_BASE", "CONT_IN_NEAR"))
        self.assertEqual(pickup_delta.stack_changes[0].after, ("H_BASE",))

    def _single_far_inbound_instance_from_payload(self, payload):
        instance = parse_instance(payload)
        inbound = instance.jobs_by_id["JOB_IN_NEAR"]
        inbound = replace(
            inbound,
            destination=Position(5, 1),
            final_slot=Slot("B1", 5, 1, 1),
        )
        containers = tuple(
            replace(container, target_slot=Slot("B1", 5, 1, 1))
            if container.container_id == "CONT_IN_NEAR"
            else container
            for container in instance.initial_state.containers
        )
        instance = replace(
            instance,
            jobs=(inbound,),
            initial_state=replace(instance.initial_state, containers=containers),
        )
        validate_instance(instance)
        return instance

    def test_full_transfer_slot_rejects_handover_drop(self) -> None:
        instance = self._single_far_inbound_instance()
        holder = ContainerState(
            container_id="TRANSFER_HOLDER",
            status=ContainerStatus.AT_TRANSFER_SLOT,
            transfer_slot_id="H_ROW_1",
        )
        transfer_states = tuple(
            replace(slot, containers=("TRANSFER_HOLDER",))
            if slot.slot_id == "H_ROW_1"
            else slot
            for slot in instance.initial_state.transfer_slots
        )
        instance = replace(
            instance,
            initial_state=replace(
                instance.initial_state,
                containers=instance.initial_state.containers + (holder,),
                transfer_slots=transfer_states,
            ),
        )
        validate_instance(instance)
        result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.HANDSHAKE_AREA),
            self._valid_handover_schedule(instance),
        )
        codes = {
            violation.code for violation in result.simulation.violations
        }
        self.assertFalse(result.valid)
        self.assertIn("TRANSFER_CAPACITY", codes)

    def test_full_target_stack_rejects_final_drop(self) -> None:
        instance = self._single_far_inbound_instance()
        target_key = Slot("B1", 5, 1, 1).stack_key
        blocker_ids = tuple(f"FULL_{tier}" for tier in range(1, 5))
        stack_states = tuple(
            replace(stack, containers=blocker_ids)
            if stack.key == target_key
            else stack
            for stack in instance.initial_state.stacks
        )
        blockers = tuple(
            ContainerState(
                container_id=container_id,
                status=ContainerStatus.IN_STACK,
                current_slot=Slot("B1", 5, 1, tier),
            )
            for tier, container_id in enumerate(blocker_ids, start=1)
        )
        instance = replace(
            instance,
            initial_state=replace(
                instance.initial_state,
                stacks=stack_states,
                containers=instance.initial_state.containers + blockers,
            ),
        )
        validate_instance(instance)
        result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.HANDSHAKE_AREA),
            self._valid_handover_schedule(instance),
        )
        codes = {
            violation.code for violation in result.simulation.violations
        }
        self.assertFalse(result.valid)
        self.assertIn("STACK_CAPACITY", codes)

    def test_valid_virtual_handover_uses_stack_then_releases_it(self) -> None:
        instance = self._single_far_inbound_instance()
        schedule = self._valid_virtual_handover_schedule(instance)
        result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.ANY_BAY),
            schedule,
        )

        self.assertTrue(result.valid, result.issues)
        self.assertEqual(result.makespan, 12.5)
        virtual_slot = Slot("B1", 4, 2, 1)
        self.assertEqual(
            result.simulation.final_state.stacks_by_key[
                virtual_slot.stack_key
            ].containers,
            (),
        )
        self.assertNotIn(
            "VIRTUAL::B1::BAY_4::ROW_2",
            result.simulation.final_state.transfer_slots_by_id,
        )
        drop_delta = result.simulation.operation_traces[2].state_delta
        pickup_delta = result.simulation.operation_traces[7].state_delta
        self.assertEqual(drop_delta.container_slot_after, virtual_slot)
        self.assertEqual(drop_delta.stack_changes[0].after, ("CONT_IN_NEAR",))
        self.assertEqual(pickup_delta.container_slot_before, virtual_slot)
        self.assertEqual(pickup_delta.stack_changes[0].after, ())

    def test_full_stack_rejects_virtual_handover_drop(self) -> None:
        instance = self._single_far_inbound_instance()
        key = Slot("B1", 4, 2, 1).stack_key
        blocker_ids = tuple(f"VIRTUAL_FULL_{tier}" for tier in range(1, 5))
        stacks = tuple(
            replace(stack, containers=blocker_ids)
            if stack.key == key
            else stack
            for stack in instance.initial_state.stacks
        )
        blockers = tuple(
            ContainerState(
                container_id=container_id,
                status=ContainerStatus.IN_STACK,
                current_slot=Slot("B1", 4, 2, tier),
            )
            for tier, container_id in enumerate(blocker_ids, start=1)
        )
        instance = replace(
            instance,
            initial_state=replace(
                instance.initial_state,
                stacks=stacks,
                containers=instance.initial_state.containers + blockers,
            ),
        )
        validate_instance(instance)

        result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.ANY_BAY),
            self._valid_virtual_handover_schedule(instance),
        )
        codes = {item.code for item in result.simulation.violations}
        self.assertFalse(result.valid)
        self.assertIn("STACK_CAPACITY", codes)

    def test_handshake_policy_rejects_virtual_transfer_point(self) -> None:
        instance = self._single_far_inbound_instance()
        schedule = replace(
            self._valid_virtual_handover_schedule(instance),
            policy=CooperationPolicy.HANDSHAKE_AREA,
        )
        result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.HANDSHAKE_AREA),
            schedule,
        )
        codes = {item.code for item in result.simulation.violations}
        self.assertFalse(result.valid)
        self.assertIn("TRANSFER_POINT_FORBIDDEN", codes)

    def test_virtual_pickup_rejects_same_crane_as_donor(self) -> None:
        instance = self._single_far_inbound_instance()
        p0 = Position(0, 1)
        p3 = Position(3, 2)
        p4 = Position(4, 2)
        point_id = "VIRTUAL::B1::BAY_4::ROW_2"
        schedule = CandidateSchedule(
            instance.instance_id,
            CooperationPolicy.ANY_BAY,
            (
                ScheduledOperation(
                    "C_SEA", OperationType.PICKUP, 0, 1, p0, p0,
                    "JOB_IN_NEAR",
                ),
                ScheduledOperation(
                    "C_SEA", OperationType.MOVE_LOADED, 1, 5, p0, p4,
                    "JOB_IN_NEAR",
                ),
                ScheduledOperation(
                    "C_SEA", OperationType.HANDOVER_DROP, 5, 6.5, p4,
                    p4, "JOB_IN_NEAR", point_id,
                    purpose=OperationPurpose.HANDOVER,
                ),
                ScheduledOperation(
                    "C_SEA", OperationType.MOVE_EMPTY, 6.5, 7.5, p4,
                    p3,
                ),
                ScheduledOperation(
                    "C_SEA", OperationType.MOVE_EMPTY, 7.5, 8.5, p3,
                    p4,
                ),
                ScheduledOperation(
                    "C_SEA", OperationType.HANDOVER_PICKUP, 8.5, 10,
                    p4, p4, "JOB_IN_NEAR", point_id,
                    purpose=OperationPurpose.HANDOVER,
                ),
            ),
        )
        result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.ANY_BAY),
            schedule,
        )
        codes = {item.code for item in result.simulation.violations}
        self.assertFalse(result.valid)
        self.assertIn("HANDOVER_SAME_CRANE", codes)

    def test_virtual_pickup_requires_container_at_stack_top(self) -> None:
        instance = self._single_far_inbound_instance()
        constraints = constraints_for(instance, CooperationPolicy.ANY_BAY)
        state = WorkingState(instance)
        point_id = "VIRTUAL::B1::BAY_4::ROW_2"
        point = constraints.transfer_points_by_id[point_id]
        slot = Slot("B1", 4, 2, 1)
        container_id = "CONT_IN_NEAR"
        state.stacks[slot.stack_key].extend((container_id, "BLOCKER"))
        state.ensure_transfer_point(point_id).append(container_id)
        state.virtual_handover_donors[point_id] = "C_SEA"
        state.update_container(
            container_id,
            status=ContainerStatus.AT_TRANSFER_SLOT,
            current_slot=slot,
            carried_by=None,
            transfer_slot_id=point_id,
        )
        state.update_crane("C_LAND", position=point.position)
        operation = ScheduledOperation(
            "C_LAND", OperationType.HANDOVER_PICKUP, 0, 1.5,
            point.position, point.position, "JOB_IN_NEAR", point_id,
            purpose=OperationPurpose.HANDOVER,
        )
        codes = []

        def fail(code, *_args) -> None:
            codes.append(code)

        _validate_operation_start(
            state, instance, constraints, operation, 0, fail
        )
        self.assertIn("HANDOVER_NOT_TOP", codes)


if __name__ == "__main__":
    unittest.main()
