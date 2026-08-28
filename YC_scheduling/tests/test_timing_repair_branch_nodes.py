from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    BranchNodeStatus,
    CandidateSchedule,
    CooperationPolicy,
    CraneSide,
    OperationType,
    Position,
    RouteKind,
    RouteMode,
    ScheduledOperation,
    TimingConstraint,
    branch_on_first_conflict,
    build_explicit_route_schedule,
    create_root_branch_node,
    load_instance,
    normalize_timing_constraints,
    repair_schedule_timing,
    timing_constraint_signature,
)


class TimingRepairAndBranchNodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.instance = load_instance(
            ROOT / "data" / "benchmarks" / "01_balanced_local_4jobs.json"
        )

    def _valid_serial_schedule(self) -> CandidateSchedule:
        order = tuple(job.id for job in self.instance.jobs)
        modes = (
            RouteMode("JOB_LOCAL_IN_SEA", RouteKind.DIRECT, CraneSide.SEASIDE),
            RouteMode("JOB_LOCAL_OUT_LAND", RouteKind.DIRECT, CraneSide.LANDSIDE),
            RouteMode("JOB_LOCAL_OUT_SEA", RouteKind.DIRECT, CraneSide.SEASIDE),
            RouteMode("JOB_LOCAL_IN_LAND", RouteKind.DIRECT, CraneSide.LANDSIDE),
        )
        return build_explicit_route_schedule(
            self.instance,
            CooperationPolicy.NO_SHARING,
            order,
            modes,
        )

    def test_timing_constraint_delays_operation_and_crane_successors(self) -> None:
        schedule = self._valid_serial_schedule()
        first_sea = next(
            index
            for index, operation in enumerate(schedule.operations)
            if operation.crane_id == "C_SEA"
        )
        original = schedule.operations[first_sea]
        constraint = TimingConstraint(
            operation_index=first_sea,
            earliest_start=original.start_time + 5.0,
            delayed_crane_id="C_SEA",
            conflict_time=original.start_time,
            opposing_operation_index=None,
        )
        repaired = repair_schedule_timing(
            self.instance,
            schedule,
            (constraint,),
        )
        self.assertAlmostEqual(
            repaired.schedule.operations[first_sea].start_time,
            original.start_time + 5.0,
        )
        self.assertIn(first_sea, repaired.shifted_operation_indices)
        sea_operations = [
            operation
            for operation in repaired.schedule.operations
            if operation.crane_id == "C_SEA"
        ]
        for previous, current in zip(sea_operations, sea_operations[1:]):
            self.assertGreaterEqual(current.start_time, previous.end_time)

    def test_duplicate_constraints_keep_strongest_start(self) -> None:
        weak = TimingConstraint(0, 3.0, "C_SEA", 1.0, 1)
        strong = TimingConstraint(0, 7.0, "C_SEA", 2.0, 1)
        normalized = normalize_timing_constraints((weak, strong))
        self.assertEqual(normalized, (strong,))
        self.assertEqual(
            timing_constraint_signature((weak, strong)),
            ((0, 1, 7.0),),
        )

    def test_relative_order_survives_later_opponent_delay(self) -> None:
        schedule = self._repairable_crossing_schedule()
        delay_seaside_behind_landside = TimingConstraint(
            operation_index=0,
            earliest_start=2.0,
            delayed_crane_id="C_SEA",
            conflict_time=1.0,
            opposing_operation_index=1,
        )
        delay_landside = TimingConstraint(
            operation_index=1,
            earliest_start=6.0,
            delayed_crane_id="C_LAND",
            conflict_time=2.0,
            opposing_operation_index=None,
        )
        repaired = repair_schedule_timing(
            self.instance,
            schedule,
            (delay_seaside_behind_landside, delay_landside),
        )
        seaside = repaired.schedule.operations[0]
        landside = repaired.schedule.operations[1]
        self.assertAlmostEqual(landside.start_time, 6.0)
        self.assertGreaterEqual(seaside.start_time, landside.end_time)

    def _repairable_crossing_schedule(self) -> CandidateSchedule:
        return CandidateSchedule(
            self.instance.instance_id,
            CooperationPolicy.NO_SHARING,
            (
                ScheduledOperation(
                    "C_SEA",
                    OperationType.MOVE_EMPTY,
                    0.0,
                    4.0,
                    Position(0, 1),
                    Position(4, 1),
                ),
                ScheduledOperation(
                    "C_LAND",
                    OperationType.MOVE_EMPTY,
                    0.0,
                    2.0,
                    Position(9, 1),
                    Position(2, 1),
                ),
                ScheduledOperation(
                    "C_LAND",
                    OperationType.MOVE_EMPTY,
                    2.0,
                    4.0,
                    Position(2, 1),
                    Position(9, 1),
                ),
            ),
        )

    def test_first_conflict_creates_seaside_and_landside_children(self) -> None:
        root = create_root_branch_node(
            self.instance,
            self._repairable_crossing_schedule(),
        )
        self.assertIs(root.status, BranchNodeStatus.CONFLICTED)
        children = branch_on_first_conflict(self.instance, root)
        self.assertEqual([child.node_id for child in children], ["N0.S", "N0.L"])
        self.assertTrue(all(child.parent_id == "N0" for child in children))
        self.assertTrue(all(child.depth == 1 for child in children))
        self.assertEqual(
            {child.timing_constraints[0].delayed_crane_id for child in children},
            {"C_SEA", "C_LAND"},
        )
        self.assertTrue(any(child.first_conflict is None for child in children))

    def test_node_without_conflict_has_no_children(self) -> None:
        root = create_root_branch_node(self.instance, self._valid_serial_schedule())
        self.assertIs(root.status, BranchNodeStatus.FEASIBLE)
        self.assertEqual(branch_on_first_conflict(self.instance, root), ())

    def test_constraint_rejects_wrong_crane_identity(self) -> None:
        schedule = self._valid_serial_schedule()
        constraint = TimingConstraint(0, 1.0, "UNKNOWN", 0.0, None)
        with self.assertRaisesRegex(ValueError, "does not match"):
            repair_schedule_timing(self.instance, schedule, (constraint,))


if __name__ == "__main__":
    unittest.main()
