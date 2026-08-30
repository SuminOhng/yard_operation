"""Acceptance tests for full-run reconstruction settings and SUMO inputs."""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path
from xml.etree import ElementTree

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_CONFIG = PROJECT_ROOT / "experiments" / "configs" / "paper_baseline.toml"
SUMO_CONFIG = PROJECT_ROOT / "sumo" / "config" / "paper_baseline.sumocfg"


def _option(root: ElementTree.Element, section: str, name: str) -> str:
    element = root.find(f"./{section}/{name}")
    if element is None or "value" not in element.attrib:
        raise AssertionError(f"missing SUMO option: {section}.{name}")
    return element.attrib["value"]


class PaperBaselineConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with BASELINE_CONFIG.open("rb") as stream:
            cls.baseline = tomllib.load(stream)
        cls.sumo_root = ElementTree.parse(SUMO_CONFIG).getroot()

    def test_full_runner_reconstruction_assumptions_are_explicit(self) -> None:
        simulation = self.baseline["simulation"]
        routing = self.baseline["routing"]
        control = self.baseline["control"]
        hdv = self.baseline["vehicles"]["hdv"]

        self.assertEqual(simulation["drain_timeout_s"], 3600)
        self.assertEqual(routing["decision_trigger_distance_m"], 30.0)
        self.assertEqual(
            routing["destination_position_rule"],
            "destination_edge_downstream_intersection",
        )
        self.assertEqual(control["capacity_slot_length_m"], 7.5)
        self.assertEqual(hdv["alternative_route_probability"], 0.20)
        self.assertEqual(hdv["alternative_route_application"], "runtime_per_intersection_only")
        self.assertEqual(
            hdv["alternative_route_candidate_rule"],
            "legal_destination_reachable_non_uturn_outgoing_excluding_all_shortest_ties",
        )
        self.assertEqual(
            hdv["alternative_route_draw_rule"],
            "independent_uniform_per_eligible_intersection_choose_when_draw_lt_probability",
        )
        self.assertEqual(
            hdv["alternative_route_choice_rule"],
            "uniform_over_stable_edge_id_sorted_candidates",
        )
        self.assertEqual(
            hdv["alternative_route_fallback_rule"],
            "stable_edge_id_shortest_distance",
        )
        self.assertEqual(hdv["alternative_route_random_seed"], 1)
        self.assertEqual(
            hdv["alternative_route_random_stream"],
            "dedicated_runtime_hdv_time_then_vehicle_id",
        )
        self.assertNotIn("simulation.drain_timeout_s", self.baseline["unresolved"]["items"])

    def test_sumo_config_uses_baseline_assets_and_hard_end(self) -> None:
        network_relative = _option(self.sumo_root, "input", "net-file")
        demand_relative = _option(self.sumo_root, "input", "route-files")
        self.assertEqual(network_relative, "../networks/paper_grid/paper_grid.net.xml")
        self.assertEqual(demand_relative, "../demand/paper_baseline.rou.xml")
        self.assertEqual(
            (SUMO_CONFIG.parent / network_relative).resolve(),
            (PROJECT_ROOT / "sumo" / "networks" / "paper_grid" / "paper_grid.net.xml").resolve(),
        )
        self.assertEqual(
            (SUMO_CONFIG.parent / demand_relative).resolve(),
            (PROJECT_ROOT / "sumo" / "demand" / "paper_baseline.rou.xml").resolve(),
        )
        self.assertTrue((SUMO_CONFIG.parent / network_relative).is_file())
        self.assertTrue((SUMO_CONFIG.parent / demand_relative).is_file())

        simulation = self.baseline["simulation"]
        departure_horizon_s = self.baseline["demand"]["reconstruction"]["departure_horizon_s"]
        self.assertEqual(float(_option(self.sumo_root, "time", "begin")), 0.0)
        self.assertEqual(
            float(_option(self.sumo_root, "time", "end")),
            departure_horizon_s + simulation["drain_timeout_s"],
        )
        self.assertEqual(
            float(_option(self.sumo_root, "time", "step-length")),
            simulation["step_length_s"],
        )
        self.assertEqual(
            int(_option(self.sumo_root, "random_number", "seed")),
            simulation["random_seed"],
        )

    def test_sumo_config_exposes_collision_and_deadlock_failures(self) -> None:
        self.assertEqual(_option(self.sumo_root, "processing", "threads"), "1")
        self.assertEqual(_option(self.sumo_root, "processing", "collision.action"), "warn")
        self.assertEqual(
            _option(self.sumo_root, "processing", "collision.check-junctions"),
            "true",
        )
        self.assertEqual(_option(self.sumo_root, "processing", "time-to-teleport"), "-1")
        self.assertEqual(_option(self.sumo_root, "report", "no-step-log"), "true")
        self.assertEqual(_option(self.sumo_root, "report", "duration-log.disable"), "true")


if __name__ == "__main__":
    unittest.main()
