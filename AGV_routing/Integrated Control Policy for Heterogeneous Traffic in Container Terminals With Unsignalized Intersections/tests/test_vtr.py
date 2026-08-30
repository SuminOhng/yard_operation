from __future__ import annotations

import unittest

from irbp_replica.control.vtr import (
    build_cycle_plan,
    clockwise_phases_after,
    order_token_stations,
    validate_single_activation,
)
from irbp_replica.domain.models import PhaseState, RoadState


def paper_phases() -> tuple[PhaseState, ...]:
    return (
        PhaseState("p_ij", "s_ij", "l_ij", ("l_jk",), 0, "HDV"),
        PhaseState("p_nj", "s_nj", "l_nj", ("l_jn",), 1, "CAV"),
        PhaseState("p_mj", "s_mj", "l_mj", ("l_jm",), 2, "CAV"),
    )


class VirtualTokenRingTests(unittest.TestCase):
    def test_clockwise_traversal_starts_after_previous_holder(self) -> None:
        order = clockwise_phases_after(paper_phases(), "s_ij")
        self.assertEqual(tuple(phase.station_id for phase in order), ("s_nj", "s_mj", "s_ij"))

    def test_paper_example_prioritizes_hdv_then_descending_weight(self) -> None:
        order = order_token_stations(
            paper_phases(),
            {"p_ij": 1 / 3, "p_nj": 1 / 2, "p_mj": 1 / 6},
            "s_ij",
        )
        self.assertEqual(order, ("s_ij", "s_nj", "s_mj"))
        self.assertEqual(len(order), len(set(order)))

    def test_equal_weights_use_clockwise_order(self) -> None:
        phases = tuple(
            PhaseState(
                phase.phase_id,
                phase.station_id,
                phase.upstream_edge_id,
                phase.downstream_edge_ids,
                phase.clockwise_index,
                "CAV",
            )
            for phase in paper_phases()
        )
        order = order_token_stations(
            phases,
            {"p_ij": 1, "p_nj": 1, "p_mj": 1},
            "s_ij",
        )
        self.assertEqual(order, ("s_nj", "s_mj", "s_ij"))

    def test_zero_weight_non_hdv_station_is_omitted(self) -> None:
        order = order_token_stations(
            paper_phases(),
            {"p_ij": 0, "p_nj": 1, "p_mj": 0},
            "s_ij",
        )
        self.assertEqual(order, ("s_ij", "s_nj"))

    def test_cycle_plan_combines_pressure_duration_and_order(self) -> None:
        roads = {
            "l_ij": RoadState("l_ij", 100, 2, 0),
            "l_nj": RoadState("l_nj", 100, 3, 0),
            "l_mj": RoadState("l_mj", 100, 1, 0),
            "l_jk": RoadState("l_jk", 100, 0, 10),
            "l_jn": RoadState("l_jn", 100, 0, 10),
            "l_jm": RoadState("l_jm", 100, 0, 10),
        }
        plan = build_cycle_plan(paper_phases(), roads, "s_ij", 30, 1)
        self.assertEqual(tuple(slot.station_id for slot in plan), ("s_ij", "s_nj", "s_mj"))
        self.assertEqual(tuple(slot.initial_duration_s for slot in plan), (10, 15, 5))
        self.assertEqual(sum(slot.initial_duration_s for slot in plan), 30)

    def test_duplicate_station_is_rejected(self) -> None:
        phases = paper_phases()
        duplicate = PhaseState("other", "s_ij", "l_mj", ("l_jm",), 3)
        with self.assertRaises(ValueError):
            order_token_stations(
                phases + (duplicate,),
                {"p_ij": 1, "p_nj": 1, "p_mj": 1, "other": 1},
                "s_ij",
            )

    def test_equations_6_and_7_require_one_matching_activation(self) -> None:
        phases = paper_phases()
        validate_single_activation(phases, ("p_nj",), ("s_nj",))
        with self.assertRaises(ValueError):
            validate_single_activation(phases, (), ("s_nj",))
        with self.assertRaises(ValueError):
            validate_single_activation(phases, ("p_nj", "p_mj"), ("s_nj",))
        with self.assertRaises(ValueError):
            validate_single_activation(phases, ("p_nj",), ("s_mj",))


if __name__ == "__main__":
    unittest.main()
