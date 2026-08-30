"""Focused unit and short live gates for the full paper-grid runner."""

from __future__ import annotations

import unittest
from pathlib import Path

from irbp_replica.simulation.paper_grid_runner import (
    PaperGridRunError,
    TripRuntime,
    VehicleSpec,
    load_paper_grid_config,
    run_paper_grid,
    select_hdv_edge,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _FixedRandom:
    def __init__(self, draw: float, choice_index: int = 0) -> None:
        self.draw = draw
        self.choice_index = choice_index
        self.random_calls = 0
        self.randrange_calls = 0

    def random(self) -> float:
        self.random_calls += 1
        return self.draw

    def randrange(self, stop: int) -> int:
        self.randrange_calls += 1
        return self.choice_index % stop


class PaperGridRunnerTests(unittest.TestCase):
    def test_runtime_reconstruction_values_are_explicit(self) -> None:
        config = load_paper_grid_config(PROJECT_ROOT)

        self.assertEqual(config.seed, 1)
        self.assertEqual(config.drain_timeout_s, 3600.0)
        self.assertEqual(config.hard_deadline_s, 10800.0)
        self.assertEqual(config.decision_trigger_distance_m, 30.0)
        self.assertEqual(config.capacity_slot_length_m, 7.5)
        self.assertEqual(config.hdv_alternative_probability, 0.2)
        self.assertEqual(config.hdv_alternative_seed, 1)

    def test_hdv_threshold_and_stable_alternative_choice(self) -> None:
        random_source = _FixedRandom(0.199999999999, choice_index=1)

        selection = select_hdv_edge(
            {"short_b": 100.0, "alt_b": 120.0, "short_a": 100.0, "alt_a": 110.0},
            probability=0.2,
            random_source=random_source,
        )

        self.assertEqual(selection.shortest_edge_ids, ("short_a", "short_b"))
        self.assertEqual(selection.shortest_edge_id, "short_a")
        self.assertEqual(selection.alternative_edge_ids, ("alt_a", "alt_b"))
        self.assertEqual(selection.selected_edge_id, "alt_b")
        self.assertTrue(selection.chose_alternative)
        self.assertEqual(random_source.random_calls, 1)
        self.assertEqual(random_source.randrange_calls, 1)

    def test_hdv_threshold_is_strict_and_no_candidate_consumes_no_rng(self) -> None:
        at_threshold = _FixedRandom(0.2)
        fallback = select_hdv_edge(
            {"short": 100.0, "alt": 101.0},
            probability=0.2,
            random_source=at_threshold,
        )
        no_alternative = _FixedRandom(0.0)
        tied = select_hdv_edge(
            {"b": 100.0, "a": 100.0},
            probability=0.2,
            random_source=no_alternative,
        )

        self.assertFalse(fallback.chose_alternative)
        self.assertEqual(fallback.selected_edge_id, "short")
        self.assertEqual(at_threshold.random_calls, 1)
        self.assertIsNone(tied.random_draw)
        self.assertEqual(tied.selected_edge_id, "a")
        self.assertEqual(no_alternative.random_calls, 0)

    def test_trip_runtime_distinguishes_revisited_edge_encounters(self) -> None:
        spec = VehicleSpec("veh", "cav_14", "CAV", 0.0, "a", "z")
        trip = TripRuntime(spec, (0.0, 0.0), 100.0, 500.0)

        self.assertTrue(trip.observe_external_edge("a", None))
        trip.mark_decided()
        self.assertTrue(trip.observe_external_edge("b", 100.0))
        trip.mark_decided()
        self.assertTrue(trip.observe_external_edge("a", 200.0))

        self.assertTrue(trip.decision_due)
        self.assertEqual(trip.edge_visit_index, 3)
        self.assertEqual(trip.distance_at_current_edge_start_m, 300.0)

    def test_short_live_run_reaches_only_explicit_incomplete_gate(self) -> None:
        with self.assertRaisesRegex(
            PaperGridRunError,
            "possible deadlock/incomplete",
        ) as caught:
            run_paper_grid(PROJECT_ROOT, max_steps=100)

        diagnostics = caught.exception.diagnostics
        self.assertEqual(diagnostics["limit_reason"], "diagnostic step cap")
        self.assertEqual(diagnostics["limit_steps"], 100)
        self.assertEqual(len(diagnostics["controllers"]), 20)
        self.assertEqual(len(diagnostics["source_hashes"]), 10)


if __name__ == "__main__":
    unittest.main()
