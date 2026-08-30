from __future__ import annotations

import unittest

from irbp_replica.control.phase_time import (
    allocate_phase_durations,
    extend_phase_for_hdv,
)


class PhaseDurationTests(unittest.TestCase):
    def test_paper_example_allocates_10_15_5_seconds(self) -> None:
        durations = allocate_phase_durations(
            {"p_ij": 1 / 3, "p_nj": 1 / 2, "p_mj": 1 / 6},
            cycle_length_s=30,
            resolution_s=1,
        )
        self.assertEqual(durations, {"p_ij": 10, "p_nj": 15, "p_mj": 5})

    def test_largest_remainder_preserves_cycle_and_stable_ties(self) -> None:
        durations = allocate_phase_durations(
            {"first": 1, "second": 1, "third": 1},
            cycle_length_s=10,
            resolution_s=1,
        )
        self.assertEqual(durations, {"first": 4, "second": 3, "third": 3})
        self.assertEqual(sum(durations.values()), 10)

    def test_zero_weight_phases_receive_zero(self) -> None:
        self.assertEqual(
            allocate_phase_durations({"a": 0, "b": 0}, 30, 1),
            {"a": 0.0, "b": 0.0},
        )
        self.assertEqual(
            allocate_phase_durations({"a": 1, "b": 0}, 30, 1),
            {"a": 30, "b": 0},
        )

    def test_non_divisible_resolution_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            allocate_phase_durations({"a": 1}, 30, 4)

    def test_algorithm_1_extends_for_consecutive_hdvs(self) -> None:
        adjusted = extend_phase_for_hdv(10, ("HDV", "HDV", "CAV"), 1, 30)
        self.assertEqual(adjusted, 12)

    def test_algorithm_1_stops_for_cav_or_empty_queue(self) -> None:
        self.assertEqual(extend_phase_for_hdv(10, ("CAV",), 1, 30), 10)
        self.assertEqual(extend_phase_for_hdv(10, (None,), 1, 30), 10)
        self.assertEqual(extend_phase_for_hdv(10, ("HDV", None), 1, 30), 11)

    def test_algorithm_1_respects_safety_cap(self) -> None:
        adjusted = extend_phase_for_hdv(10, ("HDV", "HDV", "HDV"), 1, 2)
        self.assertEqual(adjusted, 12)


if __name__ == "__main__":
    unittest.main()
