from __future__ import annotations

import unittest
from dataclasses import replace
from math import isfinite

from irbp_replica.domain.models import (
    RoutingCandidateState,
    VehicleRoutingState,
    VehicleState,
)
from irbp_replica.routing.distance import (
    a_star_cost,
    distance_mask,
    euclidean_distance_m,
    minimum_distance_cost,
    relaxed_distance_cost,
)
from irbp_replica.routing.irbp import (
    NoRouteError,
    select_next_edge,
    select_unconstrained_edge,
    update_eta,
)
from irbp_replica.routing.travel_time import (
    estimate_candidate_travel_time,
    evaluate_candidate_travel_time,
    routing_pressure,
    routing_weight,
)


def cav(
    *,
    speed_mps: float = 10,
    destination_edge_id: str = "destination",
) -> VehicleState:
    return VehicleState(
        "cav",
        "CAV",
        "incoming",
        speed_mps,
        0,
        destination_edge_id,
    )


def trip(
    *,
    eta_m: float = 30,
    distance_travelled_m: float = 100,
    destination_edge_id: str = "destination",
    destination_position_m: tuple[float, float] = (0, 0),
) -> VehicleRoutingState:
    return VehicleRoutingState(
        "cav",
        "origin",
        destination_edge_id,
        distance_travelled_m,
        eta_m,
        destination_position_m,
    )


def road_vehicle(
    vehicle_id: str,
    edge_id: str,
    *,
    speed_mps: float,
    remaining_distance_m: float,
) -> VehicleState:
    return VehicleState(
        vehicle_id,
        "HDV",
        edge_id,
        speed_mps,
        remaining_distance_m,
        "other_destination",
    )


def candidate(
    edge_id: str,
    *,
    length_m: float = 100,
    downstream_x_m: float = 100,
    vehicles: tuple[VehicleState, ...] = (),
    is_legal: bool = True,
    destination_reachable: bool = True,
) -> RoutingCandidateState:
    return RoutingCandidateState(
        edge_id,
        f"node_{edge_id}",
        length_m,
        (downstream_x_m, 0),
        vehicles,
        is_legal,
        destination_reachable,
    )


def algorithm_candidates() -> tuple[RoutingCandidateState, ...]:
    return (
        candidate(
            "a",
            downstream_x_m=100,
            vehicles=(
                road_vehicle("a_vehicle", "a", speed_mps=5, remaining_distance_m=0),
            ),
        ),
        candidate(
            "b",
            downstream_x_m=115,
            vehicles=(
                road_vehicle("b_vehicle", "b", speed_mps=10, remaining_distance_m=0),
            ),
        ),
        candidate(
            "c",
            downstream_x_m=150,
            vehicles=(
                road_vehicle("c_vehicle", "c", speed_mps=20, remaining_distance_m=0),
            ),
        ),
    )


class TravelTimeEquationTests(unittest.TestCase):
    def test_equation_8_literal_remaining_distance_matches_hand_calculation(
        self,
    ) -> None:
        edge = candidate(
            "edge",
            vehicles=(
                road_vehicle(
                    "leader",
                    "edge",
                    speed_mps=5,
                    remaining_distance_m=60,
                ),
            ),
        )
        travel_time = estimate_candidate_travel_time(
            cav(),
            edge,
            empty_road_speed_mps=14,
            speed_floor_mps=0.1,
        )
        self.assertEqual(travel_time, 14)

    def test_equation_8_uses_maximum_independent_of_vehicle_order(self) -> None:
        slower = road_vehicle(
            "slower",
            "edge",
            speed_mps=5,
            remaining_distance_m=60,
        )
        faster = road_vehicle(
            "faster",
            "edge",
            speed_mps=8,
            remaining_distance_m=20,
        )
        estimates = []
        for vehicles in ((slower, faster), (faster, slower)):
            estimates.append(
                evaluate_candidate_travel_time(
                    cav(),
                    candidate("edge", vehicles=vehicles),
                    empty_road_speed_mps=14,
                    speed_floor_mps=0.1,
                )
            )
        self.assertEqual(
            [estimate.travel_time_s for estimate in estimates],
            [14, 14],
        )
        self.assertEqual(
            [estimate.controlling_vehicle_id for estimate in estimates],
            ["slower", "slower"],
        )

    def test_empty_road_uses_configured_free_flow_speed(self) -> None:
        travel_time = estimate_candidate_travel_time(
            cav(),
            candidate("empty"),
            empty_road_speed_mps=20,
            speed_floor_mps=0.1,
        )
        self.assertEqual(travel_time, 5)

    def test_equation_8_applies_speed_floor_to_both_vehicles(self) -> None:
        edge = candidate(
            "edge",
            vehicles=(
                road_vehicle(
                    "stopped",
                    "edge",
                    speed_mps=0,
                    remaining_distance_m=50,
                ),
            ),
        )
        travel_time = estimate_candidate_travel_time(
            cav(speed_mps=0),
            edge,
            empty_road_speed_mps=14,
            speed_floor_mps=0.1,
        )
        self.assertEqual(travel_time, 1000)

    def test_remaining_distance_uses_tolerance_then_rejects_large_error(self) -> None:
        within_tolerance = candidate(
            "edge",
            vehicles=(
                road_vehicle(
                    "near_boundary",
                    "edge",
                    speed_mps=5,
                    remaining_distance_m=100 + 5e-10,
                ),
            ),
        )
        self.assertEqual(
            estimate_candidate_travel_time(
                cav(),
                within_tolerance,
                empty_road_speed_mps=14,
                speed_floor_mps=0.1,
            ),
            10,
        )
        outside_tolerance = candidate(
            "edge",
            vehicles=(
                road_vehicle(
                    "outside",
                    "edge",
                    speed_mps=5,
                    remaining_distance_m=100.01,
                ),
            ),
        )
        with self.assertRaises(ValueError):
            estimate_candidate_travel_time(
                cav(),
                outside_tolerance,
                empty_road_speed_mps=14,
                speed_floor_mps=0.1,
            )

    def test_equations_9_and_10_match_hand_calculation(self) -> None:
        pressure = routing_pressure(100, 20)
        self.assertEqual(pressure, 5)
        self.assertEqual(routing_weight(pressure), 5)

    def test_empty_road_rejects_floating_point_underflow_and_overflow(self) -> None:
        with self.assertRaises(ValueError):
            estimate_candidate_travel_time(
                cav(),
                candidate("tiny", length_m=5e-324),
                empty_road_speed_mps=14,
                speed_floor_mps=0.1,
            )
        with self.assertRaises(ValueError):
            estimate_candidate_travel_time(
                cav(),
                candidate("overflow"),
                empty_road_speed_mps=5e-324,
                speed_floor_mps=0.1,
            )


class DistanceEquationTests(unittest.TestCase):
    def test_equations_12_to_15_match_hand_calculation(self) -> None:
        heuristic = euclidean_distance_m((0, 0), (3, 4))
        self.assertEqual(heuristic, 5)
        self.assertEqual(a_star_cost(130, heuristic), 135)
        minimum = minimum_distance_cost({"a": 135, "b": 140})
        self.assertEqual(minimum, 135)
        relaxed = relaxed_distance_cost(minimum, 15)
        self.assertEqual(relaxed, 150)
        self.assertEqual(distance_mask(150, relaxed), 1)
        self.assertEqual(distance_mask(151, relaxed), 0)

    def test_equation_15_keeps_tolerance_boundary_eligible(self) -> None:
        self.assertEqual(
            distance_mask(
                130 + 5e-10,
                130,
                absolute_tolerance_m=1e-9,
            ),
            1,
        )

    def test_equation_17_depletes_eta_without_going_negative(self) -> None:
        self.assertEqual(update_eta(15, 140, 135), 10)
        self.assertEqual(update_eta(3, 140, 135), 0)
        self.assertEqual(update_eta(15, 135, 135), 15)


class AlgorithmThreeTests(unittest.TestCase):
    def test_equation_11_uses_stable_edge_id_tie_break(self) -> None:
        self.assertEqual(select_unconstrained_edge({"z": 5, "a": 5}), "a")

    def test_algorithm_3_masks_ineligible_high_pressure_and_updates_eta(self) -> None:
        decision = select_next_edge(
            cav(),
            trip(eta_m=30),
            algorithm_candidates(),
            empty_road_speed_mps=14,
            speed_floor_mps=0.1,
        )
        self.assertEqual(decision.selected_edge_id, "b")
        self.assertEqual(decision.minimum_distance_cost_m, 300)
        self.assertEqual(decision.relaxed_distance_cost_m, 330)
        self.assertEqual(decision.updated_eta_m, 15)
        scores = {score.edge_id: score for score in decision.scores}
        self.assertTrue(scores["a"].eligible)
        self.assertTrue(scores["b"].eligible)
        self.assertFalse(scores["c"].eligible)
        self.assertEqual(scores["a"].controlling_vehicle_id, "a_vehicle")
        self.assertEqual(scores["b"].controlling_vehicle_id, "b_vehicle")
        self.assertEqual(scores["c"].status, "distance_ineligible")
        self.assertEqual(scores["c"].exclusion_reason, "detour_exceeds_eta")
        self.assertEqual(scores["a"].g_cost_m, 200)
        self.assertEqual(scores["a"].h_cost_m, 100)
        self.assertEqual(scores["a"].distance_cost_m, 300)
        self.assertEqual(scores["a"].eligibility_mask, 1)
        self.assertEqual(scores["b"].distance_cost_m, 315)
        self.assertEqual(scores["c"].distance_cost_m, 350)
        self.assertEqual(scores["c"].eligibility_mask, 0)
        self.assertEqual(scores["c"].masked_weight_mps, 0)
        for score in decision.scores:
            self.assertTrue(
                all(
                    isfinite(value)
                    for value in (
                        score.travel_time_s,
                        score.pressure_weight_mps,
                        score.g_cost_m,
                        score.h_cost_m,
                        score.distance_cost_m,
                        score.detour_excess_m,
                        score.masked_weight_mps,
                    )
                )
            )

    def test_eta_zero_keeps_at_least_shortest_candidate_eligible(self) -> None:
        decision = select_next_edge(
            cav(),
            trip(eta_m=0),
            algorithm_candidates(),
            empty_road_speed_mps=14,
            speed_floor_mps=0.1,
        )
        self.assertEqual(decision.selected_edge_id, "a")
        self.assertEqual(decision.updated_eta_m, 0)
        self.assertEqual(
            tuple(score.edge_id for score in decision.scores if score.eligible),
            ("a",),
        )

    def test_candidate_order_does_not_change_tied_decision(self) -> None:
        candidates = (
            candidate("z", downstream_x_m=100),
            candidate("a", downstream_x_m=100),
        )
        selected = []
        for ordered in (candidates, tuple(reversed(candidates))):
            selected.append(
                select_next_edge(
                    cav(),
                    trip(),
                    ordered,
                    empty_road_speed_mps=14,
                    speed_floor_mps=0.1,
                ).selected_edge_id
            )
        self.assertEqual(selected, ["a", "a"])

    def test_common_distance_travelled_does_not_change_selection_or_eta(self) -> None:
        decisions = []
        for travelled in (100, 1_000_000_000):
            decisions.append(
                select_next_edge(
                    cav(),
                    trip(eta_m=30, distance_travelled_m=travelled),
                    algorithm_candidates(),
                    empty_road_speed_mps=14,
                    speed_floor_mps=0.1,
                )
            )
        self.assertEqual(
            tuple(decision.selected_edge_id for decision in decisions),
            ("b", "b"),
        )
        self.assertEqual(
            tuple(decision.updated_eta_m for decision in decisions),
            (15, 15),
        )

    def test_eta_is_committed_once_across_intersection_decisions(self) -> None:
        state = trip(eta_m=30)
        decision = select_next_edge(
            cav(),
            state,
            algorithm_candidates(),
            empty_road_speed_mps=14,
            speed_floor_mps=0.1,
        )
        self.assertEqual(state.eta_remaining_m, 30)
        committed = replace(state, eta_remaining_m=decision.updated_eta_m)
        self.assertEqual(committed.eta_remaining_m, 15)
        next_decision = select_next_edge(
            cav(),
            committed,
            algorithm_candidates(),
            empty_road_speed_mps=14,
            speed_floor_mps=0.1,
        )
        self.assertEqual(next_decision.updated_eta_m, 0)
        self.assertLessEqual(next_decision.updated_eta_m, committed.eta_remaining_m)
        self.assertEqual(trip(eta_m=30).eta_remaining_m, 30)

    def test_illegal_and_unreachable_candidates_are_never_selected(self) -> None:
        usable = candidate("usable", downstream_x_m=100)
        illegal = candidate("illegal", downstream_x_m=0, is_legal=False)
        unreachable = candidate(
            "unreachable",
            downstream_x_m=0,
            destination_reachable=False,
        )
        decision = select_next_edge(
            cav(),
            trip(),
            (illegal, unreachable, usable),
            empty_road_speed_mps=14,
            speed_floor_mps=0.1,
        )
        self.assertEqual(decision.selected_edge_id, "usable")
        self.assertEqual(
            tuple(score.edge_id for score in decision.scores),
            ("illegal", "unreachable", "usable"),
        )
        scores = {score.edge_id: score for score in decision.scores}
        self.assertEqual(scores["illegal"].status, "illegal")
        self.assertEqual(
            scores["illegal"].exclusion_reason,
            "candidate_is_not_legal",
        )
        self.assertEqual(
            scores["unreachable"].status,
            "destination_unreachable",
        )
        self.assertEqual(
            scores["unreachable"].exclusion_reason,
            "destination_is_not_reachable",
        )
        self.assertIsNone(scores["illegal"].travel_time_s)
        self.assertEqual(scores["illegal"].eligibility_mask, 0)

    def test_missing_usable_route_raises_no_route_error(self) -> None:
        with self.assertRaises(NoRouteError) as empty_error:
            select_next_edge(
                cav(),
                trip(),
                (),
                empty_road_speed_mps=14,
                speed_floor_mps=0.1,
            )
        self.assertEqual(empty_error.exception.scores, ())
        with self.assertRaises(NoRouteError) as blocked_error:
            select_next_edge(
                cav(),
                trip(),
                (candidate("blocked", is_legal=False),),
                empty_road_speed_mps=14,
                speed_floor_mps=0.1,
            )
        self.assertEqual(len(blocked_error.exception.scores), 1)
        self.assertEqual(blocked_error.exception.scores[0].status, "illegal")
        with self.assertRaises(NoRouteError) as unreachable_error:
            select_next_edge(
                cav(),
                trip(),
                (candidate("unreachable", destination_reachable=False),),
                empty_road_speed_mps=14,
                speed_floor_mps=0.1,
            )
        self.assertEqual(len(unreachable_error.exception.scores), 1)
        self.assertEqual(
            unreachable_error.exception.scores[0].status,
            "destination_unreachable",
        )

    def test_failed_precheck_trace_preserves_combined_exclusion(self) -> None:
        with self.assertRaises(NoRouteError) as error:
            select_next_edge(
                cav(),
                trip(),
                (
                    candidate(
                        "blocked",
                        is_legal=False,
                        destination_reachable=False,
                    ),
                ),
                empty_road_speed_mps=14,
                speed_floor_mps=0.1,
            )
        score = error.exception.scores[0]
        self.assertEqual(
            score.status,
            "illegal_and_destination_unreachable",
        )
        self.assertEqual(
            score.exclusion_reason,
            "candidate_is_not_legal_and_destination_is_not_reachable",
        )

    def test_duplicate_candidate_edges_are_rejected(self) -> None:
        duplicate = candidate("same")
        with self.assertRaises(ValueError):
            select_next_edge(
                cav(),
                trip(),
                (duplicate, duplicate),
                empty_road_speed_mps=14,
                speed_floor_mps=0.1,
            )

    def test_trip_destination_mismatch_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            select_next_edge(
                cav(destination_edge_id="first"),
                trip(destination_edge_id="second"),
                (candidate("edge"),),
                empty_road_speed_mps=14,
                speed_floor_mps=0.1,
            )

    def test_duplicate_observed_vehicle_ids_are_rejected(self) -> None:
        duplicate = road_vehicle(
            "same_vehicle",
            "edge",
            speed_mps=5,
            remaining_distance_m=10,
        )
        with self.assertRaises(ValueError):
            candidate("edge", vehicles=(duplicate, duplicate))

    def test_position_and_cost_tolerances_are_independent(self) -> None:
        candidates = (
            candidate("a", downstream_x_m=100),
            candidate(
                "b",
                downstream_x_m=100.05,
                vehicles=(
                    road_vehicle(
                        "near_edge_end",
                        "b",
                        speed_mps=10,
                        remaining_distance_m=100.05,
                    ),
                ),
            ),
        )
        strict_cost = select_next_edge(
            cav(),
            trip(eta_m=0),
            candidates,
            empty_road_speed_mps=14,
            speed_floor_mps=0.1,
            position_absolute_tolerance_m=0.1,
            cost_absolute_tolerance_m=0,
        )
        relaxed_cost = select_next_edge(
            cav(),
            trip(eta_m=0),
            candidates,
            empty_road_speed_mps=14,
            speed_floor_mps=0.1,
            position_absolute_tolerance_m=0.1,
            cost_absolute_tolerance_m=0.1,
        )
        strict_scores = {score.edge_id: score for score in strict_cost.scores}
        relaxed_scores = {score.edge_id: score for score in relaxed_cost.scores}
        self.assertFalse(strict_scores["b"].eligible)
        self.assertTrue(relaxed_scores["b"].eligible)

    def test_destination_heuristic_uses_actual_trip_arrival_position(self) -> None:
        candidates = (
            candidate("a", downstream_x_m=100),
            candidate("b", downstream_x_m=150),
        )
        decision = select_next_edge(
            cav(),
            trip(eta_m=0, destination_position_m=(200, 0)),
            candidates,
            empty_road_speed_mps=14,
            speed_floor_mps=0.1,
        )
        self.assertEqual(decision.selected_edge_id, "b")
        scores = {score.edge_id: score for score in decision.scores}
        self.assertEqual(scores["a"].h_cost_m, 100)
        self.assertEqual(scores["b"].h_cost_m, 50)

    def test_invalid_numeric_state_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            cav(speed_mps=float("nan"))
        with self.assertRaises(ValueError):
            cav(speed_mps=-1)
        with self.assertRaises(ValueError):
            VehicleRoutingState(
                "cav",
                "origin",
                "destination",
                0,
                float("inf"),
                (0, 0),
            )
        with self.assertRaises(ValueError):
            candidate("zero_length", length_m=0)
        with self.assertRaises(ValueError):
            estimate_candidate_travel_time(
                cav(),
                candidate("edge"),
                empty_road_speed_mps=0,
                speed_floor_mps=0.1,
            )


if __name__ == "__main__":
    unittest.main()
