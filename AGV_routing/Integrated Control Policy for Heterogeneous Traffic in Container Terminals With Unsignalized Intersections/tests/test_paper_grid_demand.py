"""Acceptance tests for deterministic paper-grid demand reconstruction."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import unittest
from collections import Counter
from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal
from itertools import pairwise
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import build_paper_grid_demand as demand

CONFIG_PATH = PROJECT_ROOT / demand.CONFIG_RELATIVE_PATH
NETWORK_DIR = PROJECT_ROOT / demand.NETWORK_RELATIVE_DIR
DEMAND_DIR = PROJECT_ROOT / demand.DEMAND_RELATIVE_DIR
ROUTE_PATH = DEMAND_DIR / demand.ROUTE_FILE
METADATA_PATH = DEMAND_DIR / demand.METADATA_FILE


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PaperGridDemandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.specification = demand._load_specification(PROJECT_ROOT)
        cls.pools = demand._build_candidate_pools(PROJECT_ROOT, cls.specification)
        cls.generated = demand._generate(PROJECT_ROOT)
        cls.route_text = ROUTE_PATH.read_text(encoding="utf-8")
        cls.metadata_text = METADATA_PATH.read_text(encoding="utf-8")
        cls.route_root = ElementTree.fromstring(cls.route_text)
        cls.vehicles = cls.route_root.findall("vehicle")
        cls.network = demand.sumolib.net.readNet(
            str(NETWORK_DIR / demand.NETWORK_FILE), withInternal=True
        )
        cls.edge_endpoints = {
            edge.get("id", ""): (edge.get("from", ""), edge.get("to", ""))
            for edge in ElementTree.parse(NETWORK_DIR / "paper_grid.edg.xml")
            .getroot()
            .findall("edge")
        }
        cls.connections = demand._connection_pairs(NETWORK_DIR / demand.CONNECTION_FILE)

    def test_paper_loading_levels_have_exact_totals_and_bin_patterns(self) -> None:
        expected = {
            1600: (3200, (133, 133, 134) * 8),
            2000: (4000, (166, 167, 167) * 8),
            2400: (4800, (200,) * 24),
        }

        for rate_vph, (expected_total, expected_quotas) in expected.items():
            total = demand._aggregate_total(rate_vph, self.specification.horizon_s)
            self.assertEqual(total, expected_total)
            self.assertEqual(demand._balanced_quotas(total, 24), expected_quotas)
            self.assertEqual(sum(expected_quotas), expected_total)

        baseline_total = demand._aggregate_total(2000, self.specification.horizon_s)
        for penetration, expected_hdv in (("0.20", 800), ("0.30", 1200), ("0.50", 2000)):
            hdv_total = int(
                (Decimal(baseline_total) * Decimal(penetration)).quantize(
                    Decimal(1),
                    rounding=ROUND_HALF_UP,
                )
            )
            self.assertEqual(hdv_total, expected_hdv)

    def test_baseline_departures_fill_24_ordered_300_second_bins(self) -> None:
        departures = demand._departures(self.specification)
        bin_counts = Counter(bin_index for _, bin_index in departures)

        self.assertEqual(len(departures), 4000)
        self.assertEqual(tuple(bin_counts[index] for index in range(24)), (166, 167, 167) * 8)
        self.assertEqual([*bin_counts], list(range(24)))
        self.assertGreater(float(departures[0][0]), 0.0)
        self.assertLess(float(departures[-1][0]), 7200.0)

    def test_baseline_counts_are_exact_and_seed_controls_byte_output(self) -> None:
        same_seed_route, _ = demand._render_demand(self.specification, self.pools)
        other_seed_route, _ = demand._render_demand(
            replace(self.specification, seed=self.specification.seed + 1),
            self.pools,
        )
        type_counts = Counter(vehicle.get("type", "") for vehicle in self.vehicles)

        self.assertEqual(
            self.generated.counts,
            {"vehicles": 4000, "hdv": 400, "cav": 3600, "vtypes": 5, "bins": 24},
        )
        self.assertEqual(self.generated.route_text, self.route_text)
        self.assertEqual(self.generated.metadata_text, self.metadata_text)
        self.assertEqual(same_seed_route, self.route_text)
        self.assertNotEqual(other_seed_route, self.route_text)
        self.assertEqual(type_counts["cav_14"], 3600)
        self.assertEqual(sum(type_counts[f"hdv_{speed}"] for speed in (9, 10, 11, 12)), 400)
        expected_vtypes = {
            "cav_14": "14",
            "hdv_9": "9",
            "hdv_10": "10",
            "hdv_11": "11",
            "hdv_12": "12",
        }
        actual_vtypes = {vtype.get("id", ""): vtype for vtype in self.route_root.findall("vType")}
        self.assertEqual(set(actual_vtypes), set(expected_vtypes))
        for type_id, maximum_speed in expected_vtypes.items():
            self.assertEqual(actual_vtypes[type_id].get("maxSpeed"), maximum_speed)
            self.assertEqual(actual_vtypes[type_id].get("speedDev"), "0")

    def test_all_od_endpoints_and_route_movements_follow_reconstruction_rules(self) -> None:
        strict_internal = set(self.pools.strict_internal_edges)
        gate_nodes = set(self.specification.gate_nodes)
        shortest_costs: dict[tuple[str, str], float] = {}

        for vehicle in self.vehicles:
            route = vehicle.find("route")
            self.assertIsNotNone(route)
            edges = route.get("edges", "").split() if route is not None else []
            self.assertTrue(edges, msg=vehicle.get("id"))
            origin = edges[0]
            destination = edges[-1]
            self.assertTrue(
                all(pair in self.connections for pair in pairwise(edges)),
                msg=vehicle.get("id"),
            )
            od_pair = (origin, destination)
            if od_pair not in shortest_costs:
                _, shortest_cost = self.network.getOptimalPath(
                    self.network.getEdge(origin),
                    self.network.getEdge(destination),
                    fastest=False,
                    withInternal=False,
                )
                shortest_costs[od_pair] = shortest_cost

            route_edges = [self.network.getEdge(edge_id) for edge_id in edges]
            route_cost = sum(edge.getLength() for edge in route_edges)
            for first, second in pairwise(route_edges):
                internal_path, internal_cost = self.network.getInternalPath(
                    first.getAllowedOutgoing(None).get(second, []),
                    fastest=False,
                )
                if internal_path is not None:
                    route_cost += internal_cost
            self.assertAlmostEqual(route_cost, shortest_costs[od_pair], places=9)

            if vehicle.get("type") == "cav_14":
                self.assertIn(origin, strict_internal)
                self.assertIn(destination, strict_internal)
                self.assertNotEqual(origin, destination)
                continue

            origin_from, _ = self.edge_endpoints[origin]
            _, destination_to = self.edge_endpoints[destination]
            is_inbound = origin_from in gate_nodes and destination in strict_internal
            is_outbound = origin in strict_internal and destination_to in gate_nodes
            self.assertNotEqual(is_inbound, is_outbound, msg=vehicle.get("id"))

    def test_hdv_direction_gate_and_speed_quotas_are_exactly_balanced(self) -> None:
        strict_internal = set(self.pools.strict_internal_edges)
        gate_index = {
            gate_node: f"gate{index}"
            for index, gate_node in enumerate(self.specification.gate_nodes, start=1)
        }
        categories: Counter[str] = Counter()
        speeds: Counter[str] = Counter()

        for vehicle in self.vehicles:
            type_id = vehicle.get("type", "")
            if not type_id.startswith("hdv_"):
                continue
            speeds[type_id.removeprefix("hdv_")] += 1
            route = vehicle.find("route")
            edges = route.get("edges", "").split() if route is not None else []
            origin = edges[0]
            destination = edges[-1]
            origin_from, _ = self.edge_endpoints[origin]
            _, destination_to = self.edge_endpoints[destination]
            if origin_from in gate_index and destination in strict_internal:
                categories[f"{gate_index[origin_from]}_inbound"] += 1
            elif origin in strict_internal and destination_to in gate_index:
                categories[f"{gate_index[destination_to]}_outbound"] += 1
            else:
                self.fail(f"invalid HDV OD: {vehicle.get('id')}")

        self.assertEqual(
            categories,
            {
                "gate1_inbound": 100,
                "gate2_inbound": 100,
                "gate1_outbound": 100,
                "gate2_outbound": 100,
            },
        )
        self.assertEqual(speeds, {"9": 100, "10": 100, "11": 100, "12": 100})

    def test_metadata_hashes_inputs_and_contains_no_machine_specific_state(self) -> None:
        metadata = json.loads(self.metadata_text)
        hashes = metadata["hashes"]
        source_hashes = hashes["source_sha256"]
        paper_facts = metadata["paper_facts"]
        reconstruction = metadata["reconstruction"]

        self.assertEqual(paper_facts["main_comparison_hdv_penetration"], 0.1)
        self.assertEqual(paper_facts["cav_od_rule"], "random_distinct_terminal_road_pair")
        self.assertNotIn("hdv_penetration", paper_facts)
        self.assertEqual(reconstruction["departure_horizon_s"], 7200)
        self.assertNotIn("horizon_s", reconstruction)
        self.assertEqual(
            reconstruction["cav_route_scope_rule"],
            "full_grid_shortest_path_gate_incident_edges_allowed",
        )
        self.assertEqual(
            reconstruction["hdv_route_scope_rule"],
            "full_grid_shortest_path_intermediate_gate_nodes_do_not_exit",
        )
        self.assertEqual(metadata["hdv_od_gate_counts"], {"gate1": 200, "gate2": 200})
        self.assertNotIn("gate_counts", metadata)
        self.assertEqual(
            metadata["hdv_od_direction_counts"],
            {
                "hdv_inbound": 200,
                "hdv_outbound": 200,
                "hdv_categories": {
                    "gate1_inbound": 100,
                    "gate2_inbound": 100,
                    "gate1_outbound": 100,
                    "gate2_outbound": 100,
                },
            },
        )
        self.assertNotIn("direction_counts", metadata)

        self.assertEqual(hashes["config_sha256"], _sha256(CONFIG_PATH))
        self.assertEqual(hashes["network_sha256"], _sha256(NETWORK_DIR / demand.NETWORK_FILE))
        self.assertEqual(
            hashes["route_sha256"], hashlib.sha256(ROUTE_PATH.read_bytes()).hexdigest()
        )
        self.assertEqual(
            source_hashes[demand.GENERATOR_RELATIVE_PATH],
            _sha256(PROJECT_ROOT / demand.GENERATOR_RELATIVE_PATH),
        )
        self.assertEqual(
            source_hashes[demand.LOCK_RELATIVE_PATH], _sha256(PROJECT_ROOT / "uv.lock")
        )
        self.assertEqual(
            metadata["toolchain"],
            {
                "sumo_distribution": "eclipse-sumo",
                "sumo_version": "1.27.1",
                "sumolib_distribution": "sumolib",
                "sumolib_version": "1.27.1",
            },
        )
        for filename in (demand.MANIFEST_FILE, demand.CONNECTION_FILE):
            relative = str(demand.NETWORK_RELATIVE_DIR / filename).replace("\\", "/")
            self.assertEqual(source_hashes[relative], _sha256(NETWORK_DIR / filename))

        combined = (self.route_text + self.metadata_text).lower()
        self.assertNotIn(str(PROJECT_ROOT).lower(), combined)
        self.assertNotRegex(combined, r"(?<![a-z])[a-z]:[\\/]")
        for volatile_marker in ("generated on ", "created_at", "timestamp"):
            self.assertNotIn(volatile_marker, combined)

    def test_build_then_check_succeeds_in_isolated_project(self) -> None:
        required_files = (
            demand.CONFIG_RELATIVE_PATH,
            Path(demand.GENERATOR_RELATIVE_PATH),
            Path(demand.LOCK_RELATIVE_PATH),
            demand.NETWORK_RELATIVE_DIR / demand.NETWORK_FILE,
            demand.NETWORK_RELATIVE_DIR / demand.MANIFEST_FILE,
            demand.NETWORK_RELATIVE_DIR / demand.CONNECTION_FILE,
        )
        with TemporaryDirectory(prefix="irbp-demand-test-") as temporary_dir:
            temporary_root = Path(temporary_dir)
            for relative_path in required_files:
                destination = temporary_root / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(PROJECT_ROOT / relative_path, destination)

            route_path = demand.build_demand(temporary_root)
            self.assertEqual(
                route_path, temporary_root / demand.DEMAND_RELATIVE_DIR / demand.ROUTE_FILE
            )
            self.assertEqual(demand.check_demand(temporary_root), route_path)
            self.assertEqual(route_path.read_bytes(), ROUTE_PATH.read_bytes())


if __name__ == "__main__":
    unittest.main()
