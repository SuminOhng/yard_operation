from __future__ import annotations

import unittest

from irbp_replica.control.pressure import (
    compute_phase_weight,
    movement_pressure,
    normalized_movement_pressure,
    phase_pressure,
    phase_weight,
)
from irbp_replica.domain.models import PhaseState, RoadState


class PressureEquationTests(unittest.TestCase):
    def test_equation_1_uses_smaller_queue_or_capacity(self) -> None:
        self.assertEqual(movement_pressure(8, 5), 5)
        self.assertEqual(movement_pressure(3, 9), 3)

    def test_equation_2_normalizes_by_upstream_length(self) -> None:
        self.assertAlmostEqual(normalized_movement_pressure(8, 5, 100), 0.05)

    def test_equation_3_sums_downstream_capacity(self) -> None:
        self.assertAlmostEqual(phase_pressure(9, (2, 4), 120), 0.05)

    def test_equation_4_clamps_negative_pressure(self) -> None:
        self.assertEqual(phase_weight(-2.5), 0.0)
        self.assertEqual(phase_weight(1.25), 1.25)

    def test_phase_snapshot_evaluates_equations_3_and_4(self) -> None:
        roads = {
            "in": RoadState("in", 100, 8, 0),
            "out-a": RoadState("out-a", 80, 0, 3),
            "out-b": RoadState("out-b", 80, 0, 4),
        }
        phase = PhaseState("p", "s", "in", ("out-a", "out-b"), 0)
        self.assertAlmostEqual(compute_phase_weight(phase, roads), 0.07)

    def test_zero_queue_has_zero_weight(self) -> None:
        roads = {
            "in": RoadState("in", 100, 0, 0),
            "out": RoadState("out", 80, 0, 10),
        }
        phase = PhaseState("p", "s", "in", ("out",), 0)
        self.assertEqual(compute_phase_weight(phase, roads), 0.0)

    def test_invalid_units_and_lengths_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            movement_pressure(-1, 2)
        with self.assertRaises(ValueError):
            normalized_movement_pressure(1, 2, 0)
        with self.assertRaises(ValueError):
            phase_pressure(1, (), 10)


if __name__ == "__main__":
    unittest.main()
