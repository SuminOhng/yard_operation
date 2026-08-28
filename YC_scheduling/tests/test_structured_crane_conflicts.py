from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    CandidateSchedule,
    CooperationPolicy,
    OperationType,
    Position,
    ScheduledOperation,
    constraints_for,
    detect_crane_conflicts,
    first_crane_conflict,
    load_instance,
    validate_schedule,
)


class StructuredCraneConflictTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.instance = load_instance(ROOT / "data" / "static_fair_micro.json")

    def _crossing_schedule(self) -> CandidateSchedule:
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
                    4.0,
                    Position(7, 1),
                    Position(3, 1),
                ),
            ),
        )

    def test_crossing_returns_exact_onset_and_witness(self) -> None:
        conflicts = detect_crane_conflicts(self.instance, self._crossing_schedule())
        self.assertEqual(len(conflicts), 1)
        conflict = conflicts[0]
        self.assertAlmostEqual(conflict.onset_time, 3.0)
        self.assertAlmostEqual(conflict.witness_time, 4.0)
        self.assertEqual(conflict.seaside_operation_index, 0)
        self.assertEqual(conflict.landside_operation_index, 1)
        self.assertAlmostEqual(conflict.seaside_bay, 4.0)
        self.assertAlmostEqual(conflict.landside_bay, 3.0)
        self.assertAlmostEqual(conflict.actual_separation, -1.0)
        self.assertAlmostEqual(conflict.required_separation, 1.0)
        self.assertAlmostEqual(conflict.violation_amount, 2.0)

    def test_stationary_crane_has_no_active_operation_index(self) -> None:
        schedule = CandidateSchedule(
            self.instance.instance_id,
            CooperationPolicy.NO_SHARING,
            (
                ScheduledOperation(
                    "C_LAND",
                    OperationType.MOVE_EMPTY,
                    0.0,
                    7.0,
                    Position(7, 1),
                    Position(0, 1),
                ),
            ),
        )
        conflict = first_crane_conflict(self.instance, schedule)
        self.assertIsNotNone(conflict)
        self.assertAlmostEqual(conflict.onset_time, 6.0)
        self.assertIsNone(conflict.seaside_operation_index)
        self.assertEqual(conflict.landside_operation_index, 0)

    def test_safe_parallel_motion_returns_no_conflict(self) -> None:
        schedule = CandidateSchedule(
            self.instance.instance_id,
            CooperationPolicy.NO_SHARING,
            (
                ScheduledOperation(
                    "C_SEA",
                    OperationType.MOVE_EMPTY,
                    0.0,
                    2.0,
                    Position(0, 1),
                    Position(2, 1),
                ),
                ScheduledOperation(
                    "C_LAND",
                    OperationType.MOVE_EMPTY,
                    0.0,
                    2.0,
                    Position(7, 1),
                    Position(5, 1),
                ),
            ),
        )
        self.assertEqual(detect_crane_conflicts(self.instance, schedule), ())
        self.assertIsNone(first_crane_conflict(self.instance, schedule))

    def test_validator_uses_same_structured_conflict_onset(self) -> None:
        schedule = self._crossing_schedule()
        conflict = first_crane_conflict(self.instance, schedule)
        validation = validate_schedule(
            self.instance,
            constraints_for(self.instance, CooperationPolicy.NO_SHARING),
            schedule,
        )
        violation = next(
            item
            for item in validation.simulation.violations
            if item.code == "CRANE_SEPARATION"
        )
        self.assertAlmostEqual(violation.time, conflict.onset_time)
        self.assertIn("t=3", violation.message)


if __name__ == "__main__":
    unittest.main()
