"""Live deterministic integration tests for SUMO 1.27.1 and TraCI."""

from __future__ import annotations

import unittest
from pathlib import Path

from irbp_replica.simulation.traci_smoke import (
    EXPECTED_SUMO_VERSION,
    EXPECTED_TRACI_PROTOCOL,
    run_sumo_smoke,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TraCISmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.first = run_sumo_smoke(PROJECT_ROOT)
        cls.second = run_sumo_smoke(PROJECT_ROOT)

    def test_real_sumo_contract_and_safe_completion(self) -> None:
        result = self.first

        self.assertEqual(result.sumo_package_version, EXPECTED_SUMO_VERSION)
        self.assertEqual(result.sumo_server_version, f"SUMO {EXPECTED_SUMO_VERSION}")
        self.assertEqual(result.traci_protocol, EXPECTED_TRACI_PROTOCOL)
        self.assertEqual(result.seed, 42)
        self.assertEqual(result.step_length_s, 1.0)
        self.assertEqual(result.effective_slot_length_m, 7.5)
        self.assertEqual(len(result.input_hashes), 3)
        self.assertEqual(
            {item.incoming_edge_id: item.link_indexes for item in result.controlled_link_indexes},
            {"w_in": (0,), "s_in": (1,)},
        )
        self.assertIn("w_in_0", result.subscribed_lane_ids)
        self.assertIn("s_in_0", result.subscribed_lane_ids)
        self.assertEqual(result.subscribed_vehicle_ids, result.expected_vehicle_ids)
        self.assertGreater(result.validated_vehicle_subscription_observations, 0)
        self.assertLessEqual(result.steps, 180)
        self.assertEqual(result.minimum_expected_remaining, 0)
        self.assertEqual(result.expected_vehicle_ids, result.departed_vehicle_ids)
        self.assertEqual(result.expected_vehicle_ids, result.arrived_vehicle_ids)
        self.assertEqual(result.teleported_vehicle_ids, ())
        self.assertEqual(result.starting_teleport_vehicle_ids, ())
        self.assertEqual(result.ending_teleport_vehicle_ids, ())
        self.assertEqual(result.colliding_vehicle_ids, ())

    def test_irbp_route_mutation_is_transactional_and_unique(self) -> None:
        result = self.first

        self.assertEqual(result.route_update_count, 1)
        self.assertEqual(result.route.vehicle_id, "cav_0")
        self.assertEqual(result.route.source_edge_id, "cav_src")
        self.assertEqual(result.route.destination_edge_id, "cav_dst")
        self.assertEqual(result.route.arrival_position_m, 42.8)
        self.assertEqual(result.route.destination_position_m, (300.0, 198.4))
        self.assertEqual(result.route.selected_edge_id, "bypass_w")
        self.assertEqual(result.route.route_after[0], "cav_src")
        self.assertEqual(result.route.route_after[1], "bypass_w")
        self.assertEqual(result.route.route_after[-1], "cav_dst")
        self.assertLess(result.route.eta_after_m, result.route.eta_before_m)
        self.assertEqual(
            tuple(score.edge_id for score in result.route.scores),
            ("bypass_w", "w_in"),
        )
        score_by_edge = {score.edge_id: score for score in result.route.scores}
        self.assertGreater(
            score_by_edge["bypass_w"].pressure_weight_mps,
            score_by_edge["w_in"].pressure_weight_mps,
        )
        self.assertEqual(score_by_edge["w_in"].controlling_vehicle_id, "blocker_0")
        selected_detour_m = score_by_edge["bypass_w"].detour_excess_m
        self.assertIsNotNone(selected_detour_m)
        self.assertAlmostEqual(
            result.route.eta_after_m,
            max(result.route.eta_before_m - selected_detour_m, 0.0),
            places=5,
        )

    def test_vtr_commands_only_one_conflict_free_phase(self) -> None:
        result = self.first

        self.assertTrue(result.cycle_plans)
        self.assertEqual(
            [plan.cycle_index for plan in result.cycle_plans],
            list(range(1, len(result.cycle_plans) + 1)),
        )
        self.assertTrue(any(run.active_phase_id is not None for run in result.signal_runs))
        self.assertTrue(result.boundary_events)
        self.assertEqual(result.signal_runs[0].start_time_s, 0.0)
        self.assertEqual(result.signal_runs[0].state, "rr")
        self.assertIsNone(result.signal_runs[0].active_phase_id)
        self.assertEqual(
            {run.active_phase_id for run in result.signal_runs if run.active_phase_id is not None},
            {"west_phase", "south_phase"},
        )
        for run in result.signal_runs:
            self.assertEqual(len(run.state), 2)
            self.assertLessEqual(run.state.count("G"), 1)
            self.assertEqual(set(run.state) - {"r", "G"}, set())
            if run.active_phase_id is None:
                self.assertEqual(run.state, "rr")
            else:
                self.assertEqual(run.state.count("G"), 1)

    def test_normalized_trace_is_reproducible(self) -> None:
        self.assertEqual(self.first.to_dict(), self.second.to_dict())
        self.assertEqual(self.first.normalized_digest, self.second.normalized_digest)


if __name__ == "__main__":
    unittest.main()
