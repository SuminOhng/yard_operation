"""Structural acceptance tests for the reconstructed paper-scale SUMO grid."""

from __future__ import annotations

import heapq
import json
import math
import subprocess
import sys
import tomllib
import unittest
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NETWORK_DIR = PROJECT_ROOT / "sumo" / "networks" / "paper_grid"


def _parse_xml(name: str) -> ElementTree.Element:
    return ElementTree.parse(NETWORK_DIR / name).getroot()


def _node_indexes(node_id: str) -> tuple[int, int]:
    prefix, row, column = node_id.split("_")
    if prefix != "j":
        raise ValueError(f"unexpected paper-grid node id: {node_id}")
    return int(row), int(column)


class PaperGridNetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with (NETWORK_DIR / "paper_grid.manifest.toml").open("rb") as stream:
            cls.manifest = tomllib.load(stream)
        cls.nodes_root = _parse_xml("paper_grid.nod.xml")
        cls.edges_root = _parse_xml("paper_grid.edg.xml")
        cls.connections_root = _parse_xml("paper_grid.con.xml")
        cls.tll_root = _parse_xml("paper_grid.tll.xml")
        cls.network_root = _parse_xml("paper_grid.net.xml")
        cls.nodes = {
            node.attrib["id"]: (float(node.attrib["x"]), float(node.attrib["y"]))
            for node in cls.nodes_root.findall("node")
        }
        cls.edges = {
            edge.attrib["id"]: (
                edge.attrib["from"],
                edge.attrib["to"],
                float(edge.attrib["length"]),
            )
            for edge in cls.edges_root.findall("edge")
        }

    def test_committed_network_rebuilds_from_plainxml(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/build_paper_grid_network.py", "--check"],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg="\n".join(part for part in (completed.stdout, completed.stderr) if part),
        )

    def test_compiled_network_omits_volatile_netconvert_header(self) -> None:
        content = (NETWORK_DIR / "paper_grid.net.xml").read_text("utf-8")
        self.assertNotIn("<!-- generated on ", content)
        self.assertNotIn("<netconvertConfiguration", content)
        self.assertNotIn("paper_grid_stage", content)

    def test_paper_counts_geometry_and_direction_pattern(self) -> None:
        self.assertEqual(len(self.nodes), 20)
        self.assertEqual(len(self.edges), 54)
        self.assertEqual(
            {node.attrib.get("type") for node in self.nodes_root.findall("node")},
            {"traffic_light"},
        )

        directed_pairs = {(source, destination) for source, destination, _ in self.edges.values()}
        vertical_count = 0
        horizontal_count = 0
        for edge in self.edges_root.findall("edge"):
            self.assertEqual(edge.attrib.get("numLanes"), "1")
            source, destination, length_m = self.edges[edge.attrib["id"]]
            source_row, source_column = _node_indexes(source)
            destination_row, destination_column = _node_indexes(destination)
            self.assertGreaterEqual(length_m, 45.0)
            self.assertLessEqual(length_m, 300.0)

            if source_column == destination_column:
                vertical_count += 1
                self.assertEqual(abs(source_row - destination_row), 1)
                self.assertIn((destination, source), directed_pairs)
            else:
                horizontal_count += 1
                self.assertEqual(source_row, destination_row)
                self.assertEqual(abs(source_column - destination_column), 1)
                if source_row in {0, 3}:
                    self.assertIn((destination, source), directed_pairs)
                else:
                    self.assertEqual(destination_column, source_column + 1)
                    self.assertNotIn((destination, source), directed_pairs)

        self.assertEqual(vertical_count, 30)
        self.assertEqual(horizontal_count, 24)

    def test_graph_is_strongly_connected_and_gate_portals_add_no_edges(self) -> None:
        adjacency: dict[str, set[str]] = defaultdict(set)
        for source, destination, _ in self.edges.values():
            adjacency[source].add(destination)

        for start in self.nodes:
            visited = {start}
            frontier = [start]
            while frontier:
                current = frontier.pop()
                for destination in adjacency[current] - visited:
                    visited.add(destination)
                    frontier.append(destination)
            self.assertEqual(visited, set(self.nodes), msg=f"unreachable from {start}")

        reconstruction = self.manifest["reconstruction"]
        self.assertEqual(reconstruction["gate_nodes"], ["j_0_1", "j_0_3"])
        self.assertEqual(self.manifest["paper"]["gate_count"], 2)
        self.assertIn("add no edges", reconstruction["count_convention"].lower())

    def test_all_legal_non_uturn_movements_have_one_controlled_link(self) -> None:
        physical = [
            (
                connection.attrib["from"],
                connection.attrib["to"],
                int(connection.attrib["fromLane"]),
                int(connection.attrib["toLane"]),
            )
            for connection in self.connections_root.findall("connection")
        ]
        controlled = [
            (
                connection.attrib["from"],
                connection.attrib["to"],
                int(connection.attrib["fromLane"]),
                int(connection.attrib["toLane"]),
            )
            for connection in self.tll_root.findall("connection")
        ]
        self.assertEqual(len(physical), 102)
        self.assertEqual(len(physical), len(set(physical)))
        self.assertCountEqual(physical, controlled)

        for incoming_id, outgoing_id, _, _ in physical:
            incoming_source, junction, _ = self.edges[incoming_id]
            outgoing_source, outgoing_destination, _ = self.edges[outgoing_id]
            self.assertEqual(junction, outgoing_source)
            self.assertNotEqual(incoming_source, outgoing_destination)

    def test_virtual_phases_partition_links_by_incoming_approach(self) -> None:
        controlled_by_tls: dict[str, dict[int, str]] = defaultdict(dict)
        for connection in self.tll_root.findall("connection"):
            tls_id = connection.attrib["tl"]
            link_index = int(connection.attrib["linkIndex"])
            self.assertNotIn(link_index, controlled_by_tls[tls_id])
            controlled_by_tls[tls_id][link_index] = connection.attrib["from"]

        logics = {logic.attrib["id"]: logic for logic in self.tll_root.findall("tlLogic")}
        self.assertEqual(set(logics), set(self.nodes))
        self.assertEqual(sum(len(logic.findall("phase")) for logic in logics.values()), 54)

        for tls_id, logic in logics.items():
            links = controlled_by_tls[tls_id]
            self.assertEqual(set(links), set(range(len(links))))
            green_count = [0] * len(links)
            phase_names = []
            for phase in logic.findall("phase"):
                state = phase.attrib["state"]
                phase_names.append(phase.attrib["name"])
                self.assertEqual(len(state), len(links))
                green_indexes = [index for index, signal in enumerate(state) if signal == "G"]
                self.assertTrue(green_indexes)
                self.assertEqual(set(state), {"r", "G"})
                self.assertEqual(len({links[index] for index in green_indexes}), 1)
                for index in green_indexes:
                    green_count[index] += 1
            self.assertEqual(green_count, [1] * len(links))
            expected_order = [
                approach for approach in ("N", "E", "S", "W")
                if any(name == f"approach_{approach}" for name in phase_names)
            ]
            self.assertEqual(phase_names, [f"approach_{name}" for name in expected_order])

    def test_each_virtual_phase_is_conflict_free_in_generated_sumo_network(self) -> None:
        request_foes: dict[str, dict[int, str]] = {}
        for junction in self.network_root.findall("junction"):
            junction_id = junction.attrib["id"]
            if junction_id in self.nodes:
                request_foes[junction_id] = {
                    int(request.attrib["index"]): request.attrib["foes"]
                    for request in junction.findall("request")
                }

        request_by_link: dict[str, dict[int, int]] = defaultdict(dict)
        for connection in self.network_root.findall("connection"):
            tls_id = connection.attrib.get("tl")
            if tls_id is None:
                continue
            _, request_index, _ = connection.attrib["via"].rsplit("_", 2)
            request_by_link[tls_id][int(connection.attrib["linkIndex"])] = int(request_index)

        for logic in self.network_root.findall("tlLogic"):
            tls_id = logic.attrib["id"]
            for phase in logic.findall("phase"):
                active_links = [
                    index for index, signal in enumerate(phase.attrib["state"]) if signal == "G"
                ]
                active_requests = [request_by_link[tls_id][index] for index in active_links]
                for request_index in active_requests:
                    foes = request_foes[tls_id][request_index]
                    for other_index in active_requests:
                        if request_index != other_index:
                            self.assertEqual(
                                foes[-(other_index + 1)],
                                "0",
                                msg=f"conflicting phase at {tls_id}: {phase.attrib['name']}",
                            )

    def test_generated_lane_lengths_stay_within_published_range(self) -> None:
        network_edges = [
            edge for edge in self.network_root.findall("edge") if edge.attrib.get("function") is None
        ]
        self.assertEqual(len(network_edges), 54)
        lengths = []
        for edge in network_edges:
            lanes = edge.findall("lane")
            self.assertEqual(len(lanes), 1)
            lengths.append(float(lanes[0].attrib["length"]))
        self.assertGreaterEqual(min(lengths), 45.0)
        self.assertLessEqual(max(lengths), 300.0)

    def test_euclidean_heuristic_is_admissible_for_all_node_pairs(self) -> None:
        adjacency: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for source, destination, length_m in self.edges.values():
            adjacency[source].append((destination, length_m))

        for start in self.nodes:
            distances = {node_id: math.inf for node_id in self.nodes}
            distances[start] = 0.0
            heap = [(0.0, start)]
            while heap:
                cost, node_id = heapq.heappop(heap)
                if cost > distances[node_id]:
                    continue
                for destination, edge_length_m in adjacency[node_id]:
                    candidate = cost + edge_length_m
                    if candidate < distances[destination]:
                        distances[destination] = candidate
                        heapq.heappush(heap, (candidate, destination))

            start_x, start_y = self.nodes[start]
            for destination, shortest_distance_m in distances.items():
                destination_x, destination_y = self.nodes[destination]
                heuristic_m = math.hypot(destination_x - start_x, destination_y - start_y)
                self.assertLessEqual(heuristic_m, shortest_distance_m + 1e-9)

    def test_metadata_records_counts_and_source_hashes(self) -> None:
        metadata = json.loads((NETWORK_DIR / "paper_grid.metadata.json").read_text("utf-8"))
        self.assertEqual(
            metadata["counts"],
            {
                "connections": 102,
                "controlled_links": 102,
                "edges": 54,
                "nodes": 20,
                "phases": 54,
                "tls": 20,
            },
        )
        self.assertEqual(
            set(metadata["source_sha256"]),
            {
                "paper_grid.con.xml",
                "paper_grid.edg.xml",
                "paper_grid.nod.xml",
                "paper_grid.tll.xml",
            },
        )
        self.assertEqual(len(metadata["manifest_sha256"]), 64)

    def test_experiment_config_matches_network_manifest(self) -> None:
        with (PROJECT_ROOT / "experiments" / "configs" / "paper_baseline.toml").open(
            "rb"
        ) as stream:
            baseline = tomllib.load(stream)

        network = baseline["network"]
        reconstruction = network["reconstruction"]
        manifest_reconstruction = self.manifest["reconstruction"]
        self.assertEqual(network["intersections"], self.manifest["paper"]["intersections"])
        self.assertEqual(network["directed_roads"], self.manifest["paper"]["directed_roads"])
        self.assertEqual(
            network["reported_lane_pattern"], self.manifest["paper"]["road_lane_statement"]
        )
        self.assertEqual(
            reconstruction["lanes_per_road"], manifest_reconstruction["lanes_per_road"]
        )
        self.assertEqual(reconstruction["column_x_m"], manifest_reconstruction["column_x_m"])
        self.assertEqual(reconstruction["row_y_m"], manifest_reconstruction["row_y_m"])
        self.assertEqual(
            reconstruction["bidirectional_horizontal_rows"],
            manifest_reconstruction["bidirectional_horizontal_rows"],
        )
        self.assertEqual(
            reconstruction["eastbound_horizontal_rows"],
            manifest_reconstruction["eastbound_horizontal_rows"],
        )
        self.assertEqual(reconstruction["gate_nodes"], manifest_reconstruction["gate_nodes"])
        self.assertEqual(reconstruction["edge_speed_mps"], manifest_reconstruction["speed_m_per_s"])
        self.assertEqual(
            reconstruction["phase_clockwise_order"], manifest_reconstruction["phase_order"]
        )
        self.assertEqual(
            reconstruction["bootstrap_phase_duration_s"],
            manifest_reconstruction["phase_duration_s"],
        )
        self.assertEqual(
            reconstruction["bootstrap_phase_next_rule"],
            manifest_reconstruction["phase_next_rule"],
        )


if __name__ == "__main__":
    unittest.main()
