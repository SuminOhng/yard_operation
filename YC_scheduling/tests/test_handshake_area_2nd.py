from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import CooperationPolicy, constraints_for, parse_instance, validate_schedule
from yard_crane_v3.model import Position
from yard_crane_v3.planners.handshake_area_2nd import (
    MovementPhase,
    MovementTableEntry,
    SchedulingProfile,
    WaitReason,
    build_handshake_area_2nd_schedule,
    evaluate_handshake_area_2nd_candidates,
)
from yard_crane_v3.planners.handshake_area_2nd.paper_timing import (
    _movement_priority_key,
    record_waits,
)
from yard_crane_v3.reference_solver.timing_repair import (
    TimingConstraint,
    TimingConstraintReason,
)
from yard_crane_v3.schedule import (
    CandidateSchedule,
    OperationPurpose,
    OperationType,
    ScheduledOperation,
)
from yard_crane_v3.visualization import (
    build_single_schedule_visualization,
    render_schedule_visualization_html,
)


class HandshakeAreaSecondPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        payload = json.loads(
            (ROOT / "data" / "static_fair_micro.json").read_text(encoding="utf-8")
        )
        self.instance = parse_instance(payload)

    def test_evaluates_all_six_paper_style_candidates(self) -> None:
        evaluations = evaluate_handshake_area_2nd_candidates(
            self.instance,
            two_opt_iterations=10,
        )
        self.assertEqual(len(evaluations), 6)
        self.assertEqual(
            {evaluation.label for evaluation in evaluations},
            {
                "GHAREHGOZLI2017:FCFS:NEAR_IO",
                "GHAREHGOZLI2017:NN:NEAR_IO",
                "GHAREHGOZLI2017:2_OPT:NEAR_IO",
                "GHAREHGOZLI2017:FCFS:NEAR_REQUEST",
                "GHAREHGOZLI2017:NN:NEAR_REQUEST",
                "GHAREHGOZLI2017:2_OPT:NEAR_REQUEST",
            },
        )
        self.assertTrue(any(evaluation.valid for evaluation in evaluations))
        self.assertTrue(
            all(
                evaluation.blocking_seconds is not None
                and evaluation.blocking_seconds >= 0
                for evaluation in evaluations
                if evaluation.valid
            )
        )

    def test_dynamic_dispatch_uses_common_blocker_reshuffling(self) -> None:
        payload = json.loads(
            (ROOT / "data" / "static_fair_micro.json").read_text(encoding="utf-8")
        )
        payload["initial_state"]["stacks"][0]["containers"].append("BLOCKER_1")
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
        schedule = build_handshake_area_2nd_schedule(
            instance,
            profile=SchedulingProfile.DYNAMIC_LEG_DISPATCH,
            two_opt_iterations=10,
        )
        result = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.HANDSHAKE_AREA),
            schedule,
        )

        self.assertTrue(result.valid, result.issues)
        reshuffles = tuple(
            operation
            for operation in schedule.operations
            if operation.purpose is OperationPurpose.RESHUFFLE
        )
        self.assertEqual(len(reshuffles), 3)
        self.assertTrue(
            all(operation.container_id == "BLOCKER_1" for operation in reshuffles)
        )

    def test_two_opt_never_regresses_its_fcfs_seed(self) -> None:
        evaluations = evaluate_handshake_area_2nd_candidates(
            self.instance,
            two_opt_iterations=20,
            random_seed=42,
        )
        by_label = {evaluation.label: evaluation for evaluation in evaluations}
        for storage_rule in ("NEAR_IO", "NEAR_REQUEST"):
            fcfs = by_label[f"GHAREHGOZLI2017:FCFS:{storage_rule}"]
            two_opt = by_label[f"GHAREHGOZLI2017:2_OPT:{storage_rule}"]
            if fcfs.valid:
                self.assertTrue(two_opt.valid)
                self.assertLessEqual(two_opt.makespan, fcfs.makespan)

    def test_selected_schedule_is_physically_valid(self) -> None:
        schedule = build_handshake_area_2nd_schedule(
            self.instance,
            two_opt_iterations=20,
            random_seed=42,
        )
        validation = validate_schedule(
            self.instance,
            constraints_for(self.instance, CooperationPolicy.HANDSHAKE_AREA),
            schedule,
        )
        self.assertTrue(validation.valid, validation.issues)
        self.assertGreater(validation.handover_count, 0)

    def test_every_operation_has_request_block_and_rank(self) -> None:
        evaluation = next(
            item
            for item in evaluate_handshake_area_2nd_candidates(
                self.instance,
                two_opt_iterations=0,
            )
            if item.label == "GHAREHGOZLI2017:FCFS:NEAR_IO"
        )
        self.assertTrue(evaluation.valid)
        self.assertIsNotNone(evaluation.schedule)
        assert evaluation.schedule is not None
        self.assertEqual(
            tuple(entry.operation_index for entry in evaluation.movement_table),
            tuple(range(len(evaluation.schedule.operations))),
        )
        self.assertTrue(
            all(entry.request_block_id for entry in evaluation.movement_table)
        )
        self.assertTrue(
            all(entry.movement_table_rank >= 0 for entry in evaluation.movement_table)
        )

    def test_split_job_donor_phase_always_has_priority(self) -> None:
        evaluation = next(
            item
            for item in evaluate_handshake_area_2nd_candidates(
                self.instance,
                two_opt_iterations=0,
            )
            if item.label == "GHAREHGOZLI2017:FCFS:NEAR_IO"
        )
        split_entries = tuple(
            entry
            for entry in evaluation.movement_table
            if entry.request_block_id == "JOB_OUT_FAR"
        )
        donors = tuple(
            entry for entry in split_entries if entry.phase is MovementPhase.DONOR
        )
        receivers = tuple(
            entry for entry in split_entries if entry.phase is MovementPhase.RECEIVER
        )
        self.assertTrue(donors)
        self.assertTrue(receivers)
        self.assertLess(
            max(_movement_priority_key(entry) for entry in donors),
            min(_movement_priority_key(entry) for entry in receivers),
        )

    def test_paper_table_4_block_order_and_handover_waits(self) -> None:
        p = Position(1, 1)
        operations = (
            ScheduledOperation("C_LAND", OperationType.WAIT, 0, 156, p, p),
            ScheduledOperation("C_SEA", OperationType.WAIT, 0, 96, p, p),
            ScheduledOperation("C_SEA", OperationType.WAIT, 252, 348, p, p),
            ScheduledOperation("C_SEA", OperationType.WAIT, 402, 486, p, p),
            ScheduledOperation("C_LAND", OperationType.WAIT, 228, 312, p, p),
            ScheduledOperation("C_LAND", OperationType.WAIT, 354, 456, p, p),
            ScheduledOperation("C_SEA", OperationType.WAIT, 492, 582, p, p),
            ScheduledOperation("C_SEA", OperationType.WAIT, 582, 732, p, p),
            ScheduledOperation("C_LAND", OperationType.WAIT, 456, 552, p, p),
            ScheduledOperation("C_LAND", OperationType.WAIT, 918, 1002, p, p),
        )
        schedule = CandidateSchedule(
            self.instance.instance_id,
            CooperationPolicy.HANDSHAKE_AREA,
            operations,
        )
        movement_table = (
            MovementTableEntry(0, "1", 0, MovementPhase.DONOR),
            MovementTableEntry(1, "1", 0, MovementPhase.RECEIVER),
            MovementTableEntry(2, "1", 0, MovementPhase.RECEIVER),
            MovementTableEntry(3, "2", 1, MovementPhase.LOCAL),
            MovementTableEntry(4, "3", 2, MovementPhase.LOCAL),
            MovementTableEntry(5, "4", 3, MovementPhase.LOCAL),
            MovementTableEntry(6, "5", 4, MovementPhase.LOCAL),
            MovementTableEntry(7, "6", 5, MovementPhase.DONOR),
            MovementTableEntry(8, "6", 5, MovementPhase.RECEIVER),
            MovementTableEntry(9, "6", 5, MovementPhase.RECEIVER),
        )
        constraints = (
            TimingConstraint(
                operation_index=2,
                earliest_start=252,
                delayed_crane_id="C_SEA",
                conflict_time=96,
                opposing_operation_index=1,
                reason=TimingConstraintReason.TRANSFER_ACCESS_ORDER,
            ),
            TimingConstraint(
                operation_index=9,
                earliest_start=918,
                delayed_crane_id="C_LAND",
                conflict_time=552,
                opposing_operation_index=7,
                reason=TimingConstraintReason.TRANSFER_ACCESS_ORDER,
            ),
        )
        waits = record_waits(
            self.instance,
            schedule,
            movement_table,
            constraints,
        )
        block_order = tuple(
            entry.request_block_id
            for index, entry in enumerate(movement_table)
            if index == 0
            or entry.request_block_id != movement_table[index - 1].request_block_id
        )
        self.assertEqual(block_order, ("1", "2", "3", "4", "5", "6"))
        self.assertEqual(
            [(record.request_block_id, record.seconds) for record in waits],
            [("1", 156), ("6", 366)],
        )
        self.assertTrue(
            all(record.reason is WaitReason.HANDOVER_PRECEDENCE for record in waits)
        )

    def test_crane_conflict_wait_is_recorded_as_interference(self) -> None:
        p = Position(1, 1)
        schedule = CandidateSchedule(
            self.instance.instance_id,
            CooperationPolicy.HANDSHAKE_AREA,
            (
                ScheduledOperation("C_LAND", OperationType.WAIT, 0, 10, p, p),
                ScheduledOperation("C_SEA", OperationType.WAIT, 10, 15, p, p),
            ),
        )
        movement_table = (
            MovementTableEntry(0, "A", 0, MovementPhase.LOCAL),
            MovementTableEntry(1, "B", 1, MovementPhase.LOCAL),
        )
        waits = record_waits(
            self.instance,
            schedule,
            movement_table,
            (
                TimingConstraint(
                    operation_index=1,
                    earliest_start=10,
                    delayed_crane_id="C_SEA",
                    conflict_time=0,
                    opposing_operation_index=0,
                    reason=TimingConstraintReason.CRANE_CONFLICT_REPAIR,
                ),
            ),
        )
        self.assertEqual(len(waits), 1)
        self.assertEqual(waits[0].seconds, 10)
        self.assertIs(waits[0].reason, WaitReason.CRANE_INTERFERENCE)

    def test_request_level_table_keeps_split_legs_consecutive(self) -> None:
        evaluation = next(
            item
            for item in evaluate_handshake_area_2nd_candidates(
                self.instance,
                two_opt_iterations=0,
                profile=SchedulingProfile.PAPER_2017,
            )
            if item.label
            == "GHAREHGOZLI2017:PAPER_2017:FCFS:NEAR_IO"
        )
        self.assertTrue(evaluation.valid)
        self.assertEqual(len(evaluation.request_legs), 3)
        donor, receiver = evaluation.request_legs[-2:]
        self.assertEqual(donor.request_block_id, "JOB_OUT_FAR")
        self.assertEqual(receiver.request_block_id, "JOB_OUT_FAR")
        self.assertIs(donor.phase, MovementPhase.DONOR)
        self.assertIs(receiver.phase, MovementPhase.RECEIVER)
        self.assertEqual(
            receiver.movement_table_rank,
            donor.movement_table_rank + 1,
        )
        rank_by_phase = {
            leg.phase: leg.movement_table_rank
            for leg in evaluation.request_legs
            if leg.request_block_id == "JOB_OUT_FAR"
        }
        self.assertTrue(
            all(
                entry.movement_table_rank == rank_by_phase[entry.phase]
                for entry in evaluation.movement_table
                if entry.request_block_id == "JOB_OUT_FAR"
            )
        )

    def test_paper_profile_candidate_renders_as_single_replay(self) -> None:
        evaluation = next(
            item
            for item in evaluate_handshake_area_2nd_candidates(
                self.instance,
                two_opt_iterations=0,
                profile=SchedulingProfile.PAPER_2017,
            )
            if item.valid
        )
        assert evaluation.schedule is not None
        assert evaluation.validation is not None
        visualization = build_single_schedule_visualization(
            self.instance,
            evaluation.schedule,
            evaluation.validation,
            title="Paper replay test",
            method=evaluation.label,
        )
        source = render_schedule_visualization_html(visualization)
        self.assertEqual(len(visualization.policies), 1)
        self.assertIn("Paper replay test", source)
        self.assertIn('id="yard-replay"', source)

    def test_donor_pickup_can_finish_before_handover_wait(self) -> None:
        instance = parse_instance(
            json.loads(
                (ROOT / "data" / "large_15out_5in_seed42.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        evaluation = evaluate_handshake_area_2nd_candidates(
            instance,
            two_opt_iterations=0,
            profile=SchedulingProfile.PAPER_2017,
        )[1]
        assert evaluation.schedule is not None
        prepared_waits = []
        for wait in evaluation.wait_records:
            delayed = evaluation.schedule.operations[wait.operation_index]
            prior_pickups = tuple(
                operation
                for operation in evaluation.schedule.operations[: wait.operation_index]
                if operation.crane_id == wait.crane_id
                and operation.job_id == wait.request_block_id
                and operation.operation_type is OperationType.PICKUP
            )
            if prior_pickups:
                prepared_waits.append((prior_pickups[-1], delayed, wait))
        self.assertTrue(prepared_waits)
        self.assertTrue(
            any(
                pickup.end_time <= delayed.start_time - wait.seconds + 1e-9
                for pickup, delayed, wait in prepared_waits
            )
        )

    def test_dynamic_leg_dispatch_reduces_nn_land_waiting(self) -> None:
        instance = parse_instance(
            json.loads(
                (ROOT / "data" / "large_15out_5in_seed42.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        paper_nn = evaluate_handshake_area_2nd_candidates(
            instance,
            two_opt_iterations=0,
            profile=SchedulingProfile.PAPER_2017,
        )[1]
        dynamic_nn = evaluate_handshake_area_2nd_candidates(
            instance,
            two_opt_iterations=0,
            profile=SchedulingProfile.DYNAMIC_LEG_DISPATCH,
        )[1]
        self.assertTrue(dynamic_nn.valid)
        self.assertFalse(dynamic_nn.fallback_used)
        self.assertLess(dynamic_nn.makespan, paper_nn.makespan)
        self.assertTrue(dynamic_nn.bypass_records)
        self.assertTrue(
            all(record.crane_id == "C_LAND" for record in dynamic_nn.bypass_records)
        )
        assert dynamic_nn.schedule is not None
        used_slots = {
            operation.transfer_slot_id
            for operation in dynamic_nn.schedule.operations
            if operation.transfer_slot_id is not None
        }
        self.assertEqual(
            used_slots,
            {"H_B10_R1", "H_B10_R2", "H_B10_R3", "H_B10_R4"},
        )

    def test_dynamic_profile_falls_back_instead_of_regressing(self) -> None:
        dynamic = evaluate_handshake_area_2nd_candidates(
            self.instance,
            two_opt_iterations=10,
            profile=SchedulingProfile.DYNAMIC_LEG_DISPATCH,
        )
        paper = evaluate_handshake_area_2nd_candidates(
            self.instance,
            two_opt_iterations=10,
            profile=SchedulingProfile.PAPER_2017,
        )
        for candidate, baseline in zip(dynamic, paper):
            if baseline.valid:
                self.assertTrue(candidate.valid)
                self.assertLessEqual(candidate.makespan, baseline.makespan)


if __name__ == "__main__":
    unittest.main()
