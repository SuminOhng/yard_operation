"""Generate and verify the deterministic 20-intersection paper-grid network."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tomllib
from collections import defaultdict, deque
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
from itertools import combinations, pairwise
from math import hypot
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from xml.etree import ElementTree

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NETWORK_DIR = PROJECT_ROOT / "sumo" / "networks" / "paper_grid"
MANIFEST_FILE = "paper_grid.manifest.toml"
SOURCE_FILES = (
    "paper_grid.nod.xml",
    "paper_grid.edg.xml",
    "paper_grid.con.xml",
    "paper_grid.tll.xml",
)
OUTPUT_FILE = "paper_grid.net.xml"
METADATA_FILE = "paper_grid.metadata.json"
EXPECTED_SUMO_VERSION = "1.27.1"
EXPECTED_CONNECTIONS = 102
CARDINAL_ORDER = ("N", "E", "S", "W")

XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>\n'
XML_NAMESPACES = {
    "nodes": "https://sumo.dlr.de/xsd/nodes_file.xsd",
    "edges": "https://sumo.dlr.de/xsd/edges_file.xsd",
    "connections": "https://sumo.dlr.de/xsd/connections_file.xsd",
    "tlLogics": "https://sumo.dlr.de/xsd/tllogic_file.xsd",
}


@dataclass(frozen=True, slots=True)
class Node:
    node_id: str
    row: int
    column: int
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class Edge:
    edge_id: str
    source: str
    target: str
    length_m: float
    group: str


@dataclass(frozen=True, slots=True)
class Movement:
    junction: str
    incoming_edge: str
    outgoing_edge: str
    approach: str
    departure: str
    link_index: int


@dataclass(frozen=True, slots=True)
class Specification:
    manifest: dict[str, Any]
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    movements: tuple[Movement, ...]
    phases: dict[str, tuple[dict[str, Any], ...]]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _node_id(row: int, column: int) -> str:
    return f"j_{row}_{column}"


def _edge_id(source: str, target: str) -> str:
    return f"e_{source}__{target}"


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            manifest = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise RuntimeError(f"cannot read paper-grid manifest: {path}") from error
    _require(manifest.get("schema_version") == 1, "manifest schema_version must be 1")
    _require(isinstance(manifest.get("paper"), dict), "manifest [paper] table is missing")
    _require(
        isinstance(manifest.get("reconstruction"), dict),
        "manifest [reconstruction] table is missing",
    )
    return manifest


def _direction(source: Node, target: Node) -> str:
    delta_row = target.row - source.row
    delta_column = target.column - source.column
    mapping = {
        (-1, 0): "N",
        (0, 1): "E",
        (1, 0): "S",
        (0, -1): "W",
    }
    try:
        return mapping[(delta_row, delta_column)]
    except KeyError as error:
        raise RuntimeError(
            f"edge endpoints are not adjacent grid nodes: {source.node_id}, {target.node_id}"
        ) from error


def _opposite(direction: str) -> str:
    return {"N": "S", "E": "W", "S": "N", "W": "E"}[direction]


def _build_specification(manifest: dict[str, Any]) -> Specification:
    paper = manifest["paper"]
    reconstruction = manifest["reconstruction"]
    rows = int(paper["rows"])
    columns = int(paper["columns"])
    x_coordinates = tuple(float(value) for value in reconstruction["column_x_m"])
    y_coordinates = tuple(float(value) for value in reconstruction["row_y_m"])
    _require(len(x_coordinates) == columns, "column_x_m count must equal paper columns")
    _require(len(y_coordinates) == rows, "row_y_m count must equal paper rows")
    _require(all(a < b for a, b in pairwise(x_coordinates)), "column_x_m must increase")
    _require(all(a > b for a, b in pairwise(y_coordinates)), "row_y_m must decrease")
    _require(tuple(reconstruction["phase_order"]) == CARDINAL_ORDER, "phase_order must be N,E,S,W")
    _require(
        reconstruction["phase_next_rule"] == "self_loop_until_traci_override",
        "phase_next_rule must preserve each phase until TraCI overrides it",
    )

    nodes = tuple(
        Node(_node_id(row, column), row, column, x_coordinates[column], y_coordinates[row])
        for row in range(rows)
        for column in range(columns)
    )
    node_by_id = {node.node_id: node for node in nodes}

    edges: list[Edge] = []

    def add_edge(source: str, target: str, group: str) -> None:
        source_node = node_by_id[source]
        target_node = node_by_id[target]
        length_m = abs(target_node.x - source_node.x) + abs(target_node.y - source_node.y)
        edges.append(Edge(_edge_id(source, target), source, target, length_m, group))

    for row in range(rows - 1):
        for column in range(columns):
            top = _node_id(row, column)
            bottom = _node_id(row + 1, column)
            add_edge(top, bottom, "vertical_bidirectional")
            add_edge(bottom, top, "vertical_bidirectional")

    bidirectional_rows = {int(row) for row in reconstruction["bidirectional_horizontal_rows"]}
    eastbound_rows = {int(row) for row in reconstruction["eastbound_horizontal_rows"]}
    _require(not bidirectional_rows & eastbound_rows, "horizontal row groups must be disjoint")
    _require(bidirectional_rows | eastbound_rows == set(range(rows)), "every row needs a horizontal rule")
    for row in range(rows):
        for column in range(columns - 1):
            west = _node_id(row, column)
            east = _node_id(row, column + 1)
            if row in bidirectional_rows:
                add_edge(west, east, "horizontal_bidirectional")
                add_edge(east, west, "horizontal_bidirectional")
            else:
                add_edge(west, east, "horizontal_eastbound")

    incoming_by_node: dict[str, list[Edge]] = defaultdict(list)
    outgoing_by_node: dict[str, list[Edge]] = defaultdict(list)
    for edge in edges:
        incoming_by_node[edge.target].append(edge)
        outgoing_by_node[edge.source].append(edge)

    direction_rank = {direction: index for index, direction in enumerate(CARDINAL_ORDER)}
    movements: list[Movement] = []
    phases: dict[str, tuple[dict[str, Any], ...]] = {}
    for junction in nodes:
        incoming_edges = sorted(
            incoming_by_node[junction.node_id],
            key=lambda edge: direction_rank[
                _direction(junction, node_by_id[edge.source])
            ],
        )
        outgoing_edges = sorted(
            outgoing_by_node[junction.node_id],
            key=lambda edge: direction_rank[
                _direction(junction, node_by_id[edge.target])
            ],
        )
        junction_movements: list[Movement] = []
        for incoming in incoming_edges:
            approach = _direction(junction, node_by_id[incoming.source])
            for outgoing in outgoing_edges:
                if outgoing.target == incoming.source:
                    continue
                departure = _direction(junction, node_by_id[outgoing.target])
                junction_movements.append(
                    Movement(
                        junction=junction.node_id,
                        incoming_edge=incoming.edge_id,
                        outgoing_edge=outgoing.edge_id,
                        approach=approach,
                        departure=departure,
                        link_index=len(junction_movements),
                    )
                )
        movements.extend(junction_movements)
        phase_records: list[dict[str, Any]] = []
        for phase_index, incoming in enumerate(incoming_edges):
            approach = _direction(junction, node_by_id[incoming.source])
            controlled_indices = [
                movement.link_index
                for movement in junction_movements
                if movement.incoming_edge == incoming.edge_id
            ]
            _require(controlled_indices, f"{junction.node_id} approach {approach} has no legal movement")
            state = "".join(
                "G" if movement.incoming_edge == incoming.edge_id else "r"
                for movement in junction_movements
            )
            phase_records.append(
                {
                    "phase_index": phase_index,
                    "name": f"approach_{approach}",
                    "incoming_edge": incoming.edge_id,
                    "approach": approach,
                    "state": state,
                    "link_indices": controlled_indices,
                }
            )
        phases[junction.node_id] = tuple(phase_records)

    return Specification(manifest, nodes, tuple(edges), tuple(movements), phases)


def _validate_specification(specification: Specification) -> None:
    paper = specification.manifest["paper"]
    reconstruction = specification.manifest["reconstruction"]
    node_ids = {node.node_id for node in specification.nodes}
    edge_ids = {edge.edge_id for edge in specification.edges}
    _require(len(specification.nodes) == int(paper["intersections"]) == 20, "expected 20 nodes")
    _require(len(node_ids) == len(specification.nodes), "node IDs must be unique")
    _require(len(specification.edges) == int(paper["directed_roads"]) == 54, "expected 54 edges")
    _require(len(edge_ids) == len(specification.edges), "edge IDs must be unique")
    _require(
        paper["road_lane_statement"] == "most_roads_single_lane",
        "paper road-lane statement must remain separate from the reconstruction",
    )
    _require(
        int(reconstruction["lanes_per_road"]) == 1,
        "reconstructed paper-grid roads must have one lane",
    )
    minimum = float(paper["road_length_min_m"])
    maximum = float(paper["road_length_max_m"])
    _require(
        all(minimum <= edge.length_m <= maximum for edge in specification.edges),
        "all reconstructed source lengths must be within the paper's 45-300 m range",
    )

    group_counts: dict[str, int] = defaultdict(int)
    pairs = {(edge.source, edge.target) for edge in specification.edges}
    node_by_id = {node.node_id: node for node in specification.nodes}
    bidirectional_rows = {
        int(row) for row in reconstruction["bidirectional_horizontal_rows"]
    }
    eastbound_rows = {int(row) for row in reconstruction["eastbound_horizontal_rows"]}
    for edge in specification.edges:
        group_counts[edge.group] += 1
        source = node_by_id[edge.source]
        target = node_by_id[edge.target]
        _require(
            abs(source.row - target.row) + abs(source.column - target.column) == 1,
            f"edge is not between adjacent grid nodes: {edge.edge_id}",
        )
        _require(
            edge.length_m + 1e-9 >= hypot(target.x - source.x, target.y - source.y),
            f"edge violates Euclidean heuristic admissibility: {edge.edge_id}",
        )
        if source.row != target.row:
            _require(edge.group == "vertical_bidirectional", f"wrong vertical group: {edge.edge_id}")
            _require((edge.target, edge.source) in pairs, f"vertical edge lacks reverse: {edge.edge_id}")
        elif edge.group == "horizontal_bidirectional":
            _require(source.row in bidirectional_rows, f"wrong bidirectional row: {edge.edge_id}")
            _require((edge.target, edge.source) in pairs, f"horizontal edge lacks reverse: {edge.edge_id}")
        elif edge.group == "horizontal_eastbound":
            _require(source.row in eastbound_rows, f"wrong eastbound row: {edge.edge_id}")
            _require(source.column < target.column, f"eastbound edge points west: {edge.edge_id}")
            _require((edge.target, edge.source) not in pairs, f"eastbound edge has reverse: {edge.edge_id}")
        else:
            raise RuntimeError(f"unknown edge group: {edge.group}")
    _require(group_counts["vertical_bidirectional"] == 30, "expected 30 vertical edges")
    _require(group_counts["horizontal_bidirectional"] == 16, "expected 16 bidirectional horizontal edges")
    _require(group_counts["horizontal_eastbound"] == 8, "expected 8 eastbound horizontal edges")

    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    reverse_adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for edge in specification.edges:
        adjacency[edge.source].add(edge.target)
        reverse_adjacency[edge.target].add(edge.source)

    def reachable(graph: dict[str, set[str]], start: str) -> set[str]:
        seen = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for neighbour in graph[current]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append(neighbour)
        return seen

    root = specification.nodes[0].node_id
    _require(reachable(adjacency, root) == node_ids, "directed grid is not strongly connected")
    _require(reachable(reverse_adjacency, root) == node_ids, "directed grid is not strongly connected")
    gate_nodes = tuple(str(node) for node in reconstruction["gate_nodes"])
    _require(len(gate_nodes) == int(paper["gate_count"]) == 2, "expected two gate nodes")
    _require(set(gate_nodes) <= node_ids, "gate node is outside the grid")
    for gate_node in gate_nodes:
        _require(reachable(adjacency, gate_node) == node_ids, f"gate cannot reach grid: {gate_node}")
        _require(reachable(reverse_adjacency, gate_node) == node_ids, f"grid cannot reach gate: {gate_node}")

    _require(len(specification.movements) == EXPECTED_CONNECTIONS, "expected 102 legal movements")
    movement_keys = {
        (movement.incoming_edge, movement.outgoing_edge) for movement in specification.movements
    }
    _require(len(movement_keys) == len(specification.movements), "movements must be unique")
    edge_by_id = {edge.edge_id: edge for edge in specification.edges}
    expected_movement_keys = {
        (incoming.edge_id, outgoing.edge_id)
        for incoming in specification.edges
        for outgoing in specification.edges
        if incoming.target == outgoing.source and incoming.source != outgoing.target
    }
    _require(movement_keys == expected_movement_keys, "legal non-U-turn movements are incomplete")
    for movement in specification.movements:
        incoming = edge_by_id[movement.incoming_edge]
        outgoing = edge_by_id[movement.outgoing_edge]
        _require(incoming.target == movement.junction, "movement incoming edge misses junction")
        _require(outgoing.source == movement.junction, "movement outgoing edge misses junction")
        _require(incoming.source != outgoing.target, "U-turn movement found")

    _require(set(specification.phases) == node_ids, "every junction needs virtual phases")
    for junction, phases in specification.phases.items():
        junction_movements = [
            movement for movement in specification.movements if movement.junction == junction
        ]
        _require(phases, f"junction has no phase: {junction}")
        covered: list[int] = []
        for phase in phases:
            active = [index for index, state in enumerate(phase["state"]) if state == "G"]
            _require(active == phase["link_indices"], f"phase mapping differs at {junction}")
            _require(
                all(state in {"G", "r"} for state in phase["state"]),
                f"invalid phase state at {junction}",
            )
            _require(
                len(phase["state"]) == len(junction_movements),
                f"phase state length differs at {junction}",
            )
            incoming_edges = {
                junction_movements[index].incoming_edge for index in phase["link_indices"]
            }
            _require(len(incoming_edges) == 1, f"phase is not single-approach at {junction}")
            covered.extend(phase["link_indices"])
        _require(
            sorted(covered) == list(range(len(junction_movements))),
            f"phases do not partition controlled links at {junction}",
        )


def _format_number(value: float) -> str:
    return f"{value:.1f}"


def _xml_root(tag: str) -> ElementTree.Element:
    return ElementTree.Element(
        tag,
        {
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:noNamespaceSchemaLocation": XML_NAMESPACES[tag],
        },
    )


def _serialize_xml(root: ElementTree.Element) -> str:
    ElementTree.indent(root, space="    ")
    return XML_DECLARATION + ElementTree.tostring(root, encoding="unicode", short_empty_elements=True) + "\n"


def _render_sources(specification: Specification) -> dict[str, str]:
    reconstruction = specification.manifest["reconstruction"]

    nodes_root = _xml_root("nodes")
    for node in specification.nodes:
        ElementTree.SubElement(
            nodes_root,
            "node",
            {
                "id": node.node_id,
                "x": _format_number(node.x),
                "y": _format_number(node.y),
                "type": "traffic_light",
                "tl": node.node_id,
                "tlType": "static",
            },
        )

    edges_root = _xml_root("edges")
    for edge in specification.edges:
        ElementTree.SubElement(
            edges_root,
            "edge",
            {
                "id": edge.edge_id,
                "from": edge.source,
                "to": edge.target,
                "numLanes": str(reconstruction["lanes_per_road"]),
                "speed": _format_number(float(reconstruction["speed_m_per_s"])),
                "length": _format_number(edge.length_m),
                "priority": "1",
            },
        )

    connections_root = _xml_root("connections")
    for movement in specification.movements:
        ElementTree.SubElement(
            connections_root,
            "connection",
            {
                "from": movement.incoming_edge,
                "to": movement.outgoing_edge,
                "fromLane": "0",
                "toLane": "0",
            },
        )

    tls_root = _xml_root("tlLogics")
    duration = _format_number(float(reconstruction["phase_duration_s"]))
    movements_by_junction: dict[str, list[Movement]] = defaultdict(list)
    for movement in specification.movements:
        movements_by_junction[movement.junction].append(movement)
    for node in specification.nodes:
        logic = ElementTree.SubElement(
            tls_root,
            "tlLogic",
            {"id": node.node_id, "type": "static", "programID": "virtual", "offset": "0"},
        )
        for phase in specification.phases[node.node_id]:
            ElementTree.SubElement(
                logic,
                "phase",
                {
                    "duration": duration,
                    "state": phase["state"],
                    "name": phase["name"],
                    # Virtual actuators change phase only through TraCI. A self-loop
                    # prevents an autonomous cycle and its physical-signal yellow warning.
                    "next": str(phase["phase_index"]),
                },
            )
    for node in specification.nodes:
        for movement in movements_by_junction[node.node_id]:
            ElementTree.SubElement(
                tls_root,
                "connection",
                {
                    "from": movement.incoming_edge,
                    "to": movement.outgoing_edge,
                    "fromLane": "0",
                    "toLane": "0",
                    "tl": movement.junction,
                    "linkIndex": str(movement.link_index),
                },
            )

    return {
        SOURCE_FILES[0]: _serialize_xml(nodes_root),
        SOURCE_FILES[1]: _serialize_xml(edges_root),
        SOURCE_FILES[2]: _serialize_xml(connections_root),
        SOURCE_FILES[3]: _serialize_xml(tls_root),
    }


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _metadata(specification: Specification, source_text: dict[str, str], manifest_path: Path) -> str:
    group_counts: dict[str, int] = defaultdict(int)
    for edge in specification.edges:
        group_counts[edge.group] += 1
    phase_count = sum(len(phases) for phases in specification.phases.values())
    metadata = {
        "schema_version": 1,
        "generator": "scripts/build_paper_grid_network.py",
        "manifest_sha256": _sha256(manifest_path.read_bytes()),
        "paper_facts": specification.manifest["paper"],
        "reconstruction": specification.manifest["reconstruction"],
        "counts": {
            "nodes": len(specification.nodes),
            "edges": len(specification.edges),
            "connections": len(specification.movements),
            "controlled_links": len(specification.movements),
            "tls": len(specification.phases),
            "phases": phase_count,
        },
        "edge_groups": dict(sorted(group_counts.items())),
        "gate_nodes": list(specification.manifest["reconstruction"]["gate_nodes"]),
        "tls": {
            junction: [dict(phase) for phase in phases]
            for junction, phases in specification.phases.items()
        },
        "source_sha256": {
            name: _sha256(content.encode("utf-8")) for name, content in source_text.items()
        },
    }
    return json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _wheel_sumo_home() -> Path:
    try:
        installed = distribution("eclipse-sumo")
    except PackageNotFoundError as error:
        raise RuntimeError(
            "eclipse-sumo is not installed; run `uv sync --frozen --extra dev`"
        ) from error
    if installed.version != EXPECTED_SUMO_VERSION:
        raise RuntimeError(
            f"eclipse-sumo {EXPECTED_SUMO_VERSION} required; found {installed.version}"
        )
    package_root = Path(installed.locate_file("sumo")).resolve()
    if not package_root.is_dir():
        raise RuntimeError(f"eclipse-sumo distribution has no SUMO directory: {package_root}")
    return package_root


def _run_netconvert(network_dir: Path, output_path: Path) -> None:
    sumo_home = _wheel_sumo_home()
    binary_name = "netconvert.exe" if os.name == "nt" else "netconvert"
    netconvert = sumo_home / "bin" / binary_name
    if not netconvert.is_file():
        raise RuntimeError(f"wheel-bundled netconvert not found: {netconvert}")
    command = [
        str(netconvert),
        "--node-files",
        SOURCE_FILES[0],
        "--edge-files",
        SOURCE_FILES[1],
        "--connection-files",
        SOURCE_FILES[2],
        "--tllogic-files",
        SOURCE_FILES[3],
        "--output-file",
        str(output_path),
        "--no-turnarounds",
        "true",
        "--junctions.corner-detail",
        "0",
    ]
    child_env = os.environ.copy()
    child_env["SUMO_HOME"] = str(sumo_home)
    child_env["PATH"] = os.pathsep.join((str(sumo_home / "bin"), child_env.get("PATH", "")))
    completed = subprocess.run(
        command,
        cwd=network_dir,
        env=child_env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        details = "\n".join(
            part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
        )
        raise RuntimeError(f"netconvert failed with exit code {completed.returncode}\n{details}")
    _require(output_path.is_file() and output_path.stat().st_size > 0, "netconvert produced no network")
    _normalize_netconvert_output(output_path)


def _normalize_netconvert_output(path: Path) -> None:
    """Remove netconvert's volatile timestamp/config comment and normalize line endings."""

    content = path.read_text(encoding="utf-8")
    marker = "<!-- generated on "
    comment_start = content.find(marker)
    _require(comment_start >= 0, "netconvert output lacks its generated-header marker")
    comment_end = content.find("-->", comment_start)
    _require(comment_end >= 0, "netconvert output has an unterminated generated header")
    before = content[:comment_start].rstrip()
    after = content[comment_end + len("-->") :].lstrip()
    path.write_text(f"{before}\n\n{after}", encoding="utf-8", newline="\n")


def _parse_xml(path: Path) -> ElementTree.Element:
    try:
        return ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError) as error:
        raise RuntimeError(f"cannot parse XML: {path}") from error


def _requests_are_foes(
    requests: dict[int, ElementTree.Element],
    first: int,
    second: int,
    junction_id: str,
) -> bool:
    foes = requests[first].get("foes", "")
    _require(len(foes) == len(requests), f"invalid foes vector: {junction_id}")
    # SUMO writes request index 0 at the rightmost position of the bit vector.
    return foes[len(foes) - 1 - second] == "1"


def _validate_net_xml(path: Path, specification: Specification) -> None:
    root = _parse_xml(path)
    external_edges = [edge for edge in root.findall("edge") if edge.get("function") != "internal"]
    junctions = [junction for junction in root.findall("junction") if not junction.get("id", "").startswith(":")]
    controlled = [connection for connection in root.findall("connection") if connection.get("tl")]
    logics = root.findall("tlLogic")
    _require(len(external_edges) == 54, f"generated network has {len(external_edges)} external edges")
    _require(len(junctions) == 20, f"generated network has {len(junctions)} junctions")
    _require(len(controlled) == EXPECTED_CONNECTIONS, "generated controlled-link count differs")
    _require(len(logics) == 20, f"generated network has {len(logics)} TLS programs")

    source_edges = {edge.edge_id: edge for edge in specification.edges}
    for edge in external_edges:
        edge_id = edge.get("id", "")
        _require(edge_id in source_edges, f"unexpected generated edge: {edge_id}")
        lanes = edge.findall("lane")
        _require(len(lanes) == 1, f"generated edge is not one lane: {edge_id}")
        length = float(lanes[0].get("length", "nan"))
        _require(abs(length - source_edges[edge_id].length_m) < 1e-6, f"edge length drift: {edge_id}")

    expected_mapping = {
        (movement.incoming_edge, movement.outgoing_edge, movement.junction, movement.link_index)
        for movement in specification.movements
    }
    actual_mapping = {
        (
            connection.get("from", ""),
            connection.get("to", ""),
            connection.get("tl", ""),
            int(connection.get("linkIndex", "-1")),
        )
        for connection in controlled
    }
    _require(actual_mapping == expected_mapping, "generated controlled-link mapping differs")
    for logic in logics:
        junction = logic.get("id", "")
        _require(junction in specification.phases, f"unexpected TLS program: {junction}")
        actual_phases = [
            (phase.get("name"), phase.get("state"), phase.get("next"))
            for phase in logic.findall("phase")
        ]
        expected_phases = [
            (phase["name"], phase["state"], str(phase["phase_index"]))
            for phase in specification.phases[junction]
        ]
        _require(actual_phases == expected_phases, f"generated TLS phases differ: {junction}")

    junction_by_id = {junction.get("id", ""): junction for junction in junctions}
    connections_by_tls: dict[str, list[ElementTree.Element]] = defaultdict(list)
    for connection in controlled:
        connections_by_tls[connection.get("tl", "")].append(connection)
    for junction_id, phases in specification.phases.items():
        junction = junction_by_id[junction_id]
        internal_lanes = junction.get("intLanes", "").split()
        requests = {
            int(request.get("index", "-1")): request for request in junction.findall("request")
        }
        _require(len(requests) == len(internal_lanes), f"request mapping differs: {junction_id}")
        request_by_link: dict[int, int] = {}
        for connection in connections_by_tls[junction_id]:
            link_index = int(connection.get("linkIndex", "-1"))
            via = connection.get("via", "")
            _require(via in internal_lanes, f"controlled link has unknown via lane: {junction_id}")
            request_by_link[link_index] = internal_lanes.index(via)
        _require(
            set(request_by_link) == set(range(len(requests))),
            f"controlled-link/request mapping differs: {junction_id}",
        )

        for phase in phases:
            active_requests = [request_by_link[index] for index in phase["link_indices"]]
            for first, second in combinations(active_requests, 2):
                _require(
                    not _requests_are_foes(requests, first, second, junction_id)
                    and not _requests_are_foes(requests, second, first, junction_id),
                    f"SUMO foes conflict in {junction_id} {phase['name']}: {first}, {second}",
                )


def validate_artifacts(network_dir: Path = NETWORK_DIR) -> dict[str, int]:
    """Validate committed manifest, PlainXML, metadata, and compiled network."""

    manifest_path = network_dir / MANIFEST_FILE
    specification = _build_specification(_load_manifest(manifest_path))
    _validate_specification(specification)
    expected_sources = _render_sources(specification)
    for name, expected in expected_sources.items():
        path = network_dir / name
        _require(path.is_file(), f"missing generated source: {path}")
        _require(path.read_text(encoding="utf-8") == expected, f"generated source is stale: {path}")
    expected_metadata = _metadata(specification, expected_sources, manifest_path)
    metadata_path = network_dir / METADATA_FILE
    _require(metadata_path.is_file(), f"missing metadata: {metadata_path}")
    _require(
        metadata_path.read_text(encoding="utf-8") == expected_metadata,
        f"metadata is stale: {metadata_path}",
    )
    network_path = network_dir / OUTPUT_FILE
    _require(network_path.is_file(), f"missing compiled network: {network_path}")
    _validate_net_xml(network_path, specification)
    return {
        "nodes": len(specification.nodes),
        "edges": len(specification.edges),
        "connections": len(specification.movements),
        "tls": len(specification.phases),
        "phases": sum(len(phases) for phases in specification.phases.values()),
    }


def _generate_into(network_dir: Path, manifest_path: Path) -> Specification:
    specification = _build_specification(_load_manifest(manifest_path))
    _validate_specification(specification)
    source_text = _render_sources(specification)
    network_dir.mkdir(parents=True, exist_ok=True)
    for name, content in source_text.items():
        (network_dir / name).write_text(content, encoding="utf-8", newline="")
    (network_dir / METADATA_FILE).write_text(
        _metadata(specification, source_text, manifest_path),
        encoding="utf-8",
        newline="",
    )
    _run_netconvert(network_dir, network_dir / OUTPUT_FILE)
    _validate_net_xml(network_dir / OUTPUT_FILE, specification)
    return specification


def build_network() -> Path:
    manifest_path = NETWORK_DIR / MANIFEST_FILE
    _generate_into(NETWORK_DIR, manifest_path)
    counts = validate_artifacts(NETWORK_DIR)
    print(f"built {NETWORK_DIR / OUTPUT_FILE} ({counts})")
    return NETWORK_DIR / OUTPUT_FILE


def check_network() -> Path:
    committed_path = NETWORK_DIR / OUTPUT_FILE
    committed_counts = validate_artifacts(NETWORK_DIR)
    with TemporaryDirectory(prefix="irbp-paper-grid-") as temporary_dir:
        rebuilt_dir = Path(temporary_dir)
        rebuilt_manifest = rebuilt_dir / MANIFEST_FILE
        rebuilt_manifest.write_bytes((NETWORK_DIR / MANIFEST_FILE).read_bytes())
        _generate_into(rebuilt_dir, rebuilt_manifest)
        for name in (*SOURCE_FILES, METADATA_FILE, OUTPUT_FILE):
            _require(
                (NETWORK_DIR / name).read_bytes() == (rebuilt_dir / name).read_bytes(),
                f"committed {name} differs from deterministic rebuild",
            )
    print(f"checked {committed_path} ({committed_counts})")
    return committed_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify committed generated assets without rewriting repository files",
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        arguments = _parse_args()
        check_network() if arguments.check else build_network()
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
