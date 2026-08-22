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
    ContainerStatus,
    CooperationPolicy,
    OperationPurpose,
    OperationType,
    Position,
    ScheduledOperation,
    Slot,
    constraints_for,
    load_instance,
    parse_instance,
    validate_schedule,
)


class PhysicalSimulatorPhaseThreeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = ROOT / "data" / "static_fair_micro.json"

    def _blocked_outbound_instance(self):
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["jobs"] = [
            job for job in payload["jobs"] if job["id"] == "JOB_OUT_FAR"
        ]
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
        return parse_instance(payload)

    def _reshuffle_schedule(
        self,
        instance,
        *,
        blocker_target: Slot = Slot("B1", 5, 1, 1),
    ) -> CandidateSchedule:
        p0, p5, p6 = Position(0, 1), Position(5, 1), Position(6, 1)
        reshuffle_drop_end = 9 + 1 + blocker_target.tier * 0.5
        return CandidateSchedule(
            instance_id=instance.instance_id,
            policy=CooperationPolicy.NO_SHARING,
            operations=(
                ScheduledOperation(
                    "C_SEA", OperationType.MOVE_EMPTY, 0, 6, p0, p6
                ),
                ScheduledOperation(
                    crane_id="C_SEA",
                    operation_type=OperationType.PICKUP,
                    start_time=6,
                    end_time=8,
                    start_position=p6,
                    end_position=p6,
                    container_id="BLOCKER_1",
                    purpose=OperationPurpose.RESHUFFLE,
                ),
                ScheduledOperation(
                    crane_id="C_SEA",
                    operation_type=OperationType.MOVE_LOADED,
                    start_time=8,
                    end_time=9,
                    start_position=p6,
                    end_position=blocker_target.position,
                    container_id="BLOCKER_1",
                    purpose=OperationPurpose.RESHUFFLE,
                ),
                ScheduledOperation(
                    crane_id="C_SEA",
                    operation_type=OperationType.FINAL_DROP,
                    start_time=9,
                    end_time=reshuffle_drop_end,
                    start_position=blocker_target.position,
                    end_position=blocker_target.position,
                    container_id="BLOCKER_1",
                    target_slot=blocker_target,
                    purpose=OperationPurpose.RESHUFFLE,
                ),
                ScheduledOperation(
                    "C_SEA",
                    OperationType.MOVE_EMPTY,
                    reshuffle_drop_end,
                    reshuffle_drop_end + 1,
                    blocker_target.position,
                    p6,
                ),
                ScheduledOperation(
                    "C_SEA",
                    OperationType.PICKUP,
                    reshuffle_drop_end + 1,
                    reshuffle_drop_end + 2.5,
                    p6,
                    p6,
                    "JOB_OUT_FAR",
                ),
                ScheduledOperation(
                    "C_SEA",
                    OperationType.MOVE_LOADED,
                    reshuffle_drop_end + 2.5,
                    reshuffle_drop_end + 8.5,
                    p6,
                    p0,
                    "JOB_OUT_FAR",
                ),
                ScheduledOperation(
                    "C_SEA",
                    OperationType.FINAL_DROP,
                    reshuffle_drop_end + 8.5,
                    reshuffle_drop_end + 9.5,
                    p0,
                    p0,
                    "JOB_OUT_FAR",
                ),
            ),
        )

    def test_reshuffle_unblocks_and_completes_outbound_job(self) -> None:
        instance = self._blocked_outbound_instance()
        result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.NO_SHARING),
            self._reshuffle_schedule(instance),
        )
        self.assertTrue(result.valid, result.issues)
        self.assertEqual(result.makespan, 20.0)
        self.assertEqual(result.handover_count, 0)
        final = result.simulation.final_state
        blocker = final.containers_by_id["BLOCKER_1"]
        outbound = final.containers_by_id["CONT_OUT_FAR"]
        self.assertIs(blocker.status, ContainerStatus.IN_STACK)
        self.assertEqual(blocker.current_slot, Slot("B1", 5, 1, 1))
        self.assertIs(outbound.status, ContainerStatus.COMPLETED)
        self.assertEqual(
            final.stacks_by_key[Slot("B1", 5, 1, 1).stack_key].containers,
            ("BLOCKER_1",),
        )
        self.assertEqual(
            final.stacks_by_key[Slot("B1", 6, 1, 1).stack_key].containers,
            (),
        )

    def test_reshuffle_drop_to_non_next_tier_is_rejected(self) -> None:
        instance = self._blocked_outbound_instance()
        result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.NO_SHARING),
            self._reshuffle_schedule(
                instance, blocker_target=Slot("B1", 5, 1, 2)
            ),
        )
        codes = {violation.code for violation in result.simulation.violations}
        self.assertFalse(result.valid)
        self.assertIn("TARGET_TIER_NOT_NEXT", codes)

    def test_operation_trace_contains_stack_and_container_delta(self) -> None:
        instance = self._blocked_outbound_instance()
        result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.NO_SHARING),
            self._reshuffle_schedule(instance),
        )
        pickup_delta = result.simulation.operation_traces[1].state_delta
        drop_delta = result.simulation.operation_traces[3].state_delta
        self.assertEqual(
            pickup_delta.stack_changes[0].before,
            ("CONT_OUT_FAR", "BLOCKER_1"),
        )
        self.assertEqual(
            pickup_delta.stack_changes[0].after,
            ("CONT_OUT_FAR",),
        )
        self.assertIs(
            pickup_delta.container_status_after,
            ContainerStatus.ON_CRANE,
        )
        self.assertEqual(
            drop_delta.stack_changes[0].after,
            ("BLOCKER_1",),
        )
        self.assertIs(
            drop_delta.container_status_after,
            ContainerStatus.IN_STACK,
        )

    def test_continuous_crane_crossing_is_rejected_inside_simulator(self) -> None:
        instance = load_instance(self.path)
        schedule = CandidateSchedule(
            instance_id=instance.instance_id,
            policy=CooperationPolicy.NO_SHARING,
            operations=(
                ScheduledOperation(
                    "C_SEA",
                    OperationType.MOVE_EMPTY,
                    0,
                    4,
                    Position(0, 1),
                    Position(4, 1),
                ),
                ScheduledOperation(
                    "C_LAND",
                    OperationType.MOVE_EMPTY,
                    0,
                    4,
                    Position(7, 1),
                    Position(3, 1),
                ),
            ),
        )
        result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.NO_SHARING),
            schedule,
        )
        codes = {violation.code for violation in result.simulation.violations}
        self.assertFalse(result.valid)
        self.assertIn("CRANE_SEPARATION", codes)

    def test_validator_is_a_direct_facade_over_simulation_result(self) -> None:
        instance = self._blocked_outbound_instance()
        result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.NO_SHARING),
            self._reshuffle_schedule(instance),
        )
        self.assertEqual(result.valid, result.simulation.valid)
        self.assertEqual(result.makespan, result.simulation.makespan)
        self.assertEqual(result.handover_count, result.simulation.handover_count)
        self.assertEqual(
            [(issue.code, issue.message) for issue in result.issues],
            [
                (violation.code, violation.message)
                for violation in result.simulation.violations
            ],
        )


if __name__ == "__main__":
    unittest.main()
