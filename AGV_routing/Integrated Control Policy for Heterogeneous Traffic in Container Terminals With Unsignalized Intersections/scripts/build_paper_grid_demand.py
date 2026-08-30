"""Generate and verify deterministic baseline demand for the paper-grid network."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext
from importlib.metadata import PackageNotFoundError, distribution
from itertools import pairwise
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from xml.etree import ElementTree

import sumolib

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_RELATIVE_PATH = Path("experiments/configs/paper_baseline.toml")
NETWORK_RELATIVE_DIR = Path("sumo/networks/paper_grid")
NETWORK_FILE = "paper_grid.net.xml"
MANIFEST_FILE = "paper_grid.manifest.toml"
CONNECTION_FILE = "paper_grid.con.xml"
DEMAND_RELATIVE_DIR = Path("sumo/demand")
ROUTE_FILE = "paper_baseline.rou.xml"
METADATA_FILE = "paper_baseline.metadata.json"
GENERATOR_RELATIVE_PATH = "scripts/build_paper_grid_demand.py"
LOCK_RELATIVE_PATH = "uv.lock"
EXPECTED_SUMO_VERSION = "1.27.1"
EXPECTED_SUMOLIB_VERSION = "1.27.1"
EXPECTED_PAPER_LEVELS = (1600, 2000, 2400)
EXPECTED_LOADING_INTERVAL_S = 300
EXPECTED_HORIZON_S = 7200
EXPECTED_STRICT_INTERNAL_EDGES = 42
EXPECTED_BASELINE_TOTAL = 4000
EXPECTED_BASELINE_HDV = 400
EXPECTED_BASELINE_CAV = 3600
XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>\n'


@dataclass(frozen=True, slots=True)
class DemandSpecification:
    config: dict[str, Any]
    manifest: dict[str, Any]
    seed: int
    horizon_s: int
    interval_s: int
    loading_levels_vph: tuple[int, ...]
    baseline_vph: int
    hdv_fraction: Decimal
    cav_speed_mps: int
    hdv_speeds_mps: tuple[int, ...]
    departure_decimal_places: int
    gate_nodes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RouteCandidate:
    origin_edge: str
    destination_edge: str
    route_edges: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CandidatePools:
    strict_internal_edges: tuple[str, ...]
    cav: tuple[RouteCandidate, ...]
    hdv: dict[str, tuple[RouteCandidate, ...]]
    candidate_counts: dict[str, Any]


@dataclass(frozen=True, slots=True)
class GeneratedDemand:
    route_text: str
    metadata_text: str
    counts: dict[str, int]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _load_toml(path: Path, description: str) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            value = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise RuntimeError(f"cannot read {description}: {path}") from error
    return value


def _load_specification(project_root: Path) -> DemandSpecification:
    config_path = project_root / CONFIG_RELATIVE_PATH
    manifest_path = project_root / NETWORK_RELATIVE_DIR / MANIFEST_FILE
    config = _load_toml(config_path, "paper baseline config")
    manifest = _load_toml(manifest_path, "paper-grid manifest")

    try:
        simulation = config["simulation"]
        demand = config["demand"]
        reconstruction = demand["reconstruction"]
        cav = config["vehicles"]["cav"]
        hdv = config["vehicles"]["hdv"]
        gates = manifest["reconstruction"]["gate_nodes"]
        seed = int(simulation["random_seed"])
        horizon_s = int(reconstruction["departure_horizon_s"])
        interval_s = int(demand["loading_interval_s"])
        loading_levels = tuple(
            int(value) for value in demand["paper_loading_levels_vehicles_per_hour"]
        )
        baseline_vph = int(demand["baseline_vehicles_per_hour"])
        hdv_fraction = Decimal(str(demand["hdv_penetration"]))
        cav_speed_mps = int(cav["maximum_speed_mps"])
        hdv_speeds_mps = tuple(int(value) for value in hdv["maximum_speed_choices_mps"])
        departure_decimal_places = int(reconstruction["departure_decimal_places"])
        gate_nodes = tuple(str(value) for value in gates)
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("paper baseline demand config is incomplete or invalid") from error

    _require(loading_levels == EXPECTED_PAPER_LEVELS, "paper loading levels must be 1600/2000/2400")
    _require(baseline_vph == 2000, "paper baseline loading level must be 2000 veh/h")
    _require(interval_s == EXPECTED_LOADING_INTERVAL_S, "paper loading interval must be 300 s")
    _require(
        horizon_s == EXPECTED_HORIZON_S,
        "reconstructed departure horizon must be 7200 s",
    )
    _require(seed >= 0, "random seed must be non-negative")
    _require(
        horizon_s % interval_s == 0,
        "departure horizon must contain whole loading intervals",
    )
    _require(hdv_fraction == Decimal("0.10"), "baseline HDV penetration must be 10%")
    _require(cav_speed_mps == 14, "paper CAV maximum speed must be 14 m/s")
    _require(hdv_speeds_mps == (9, 10, 11, 12), "HDV speed choices must be 9/10/11/12 m/s")
    _require(cav["speed_deviation"] == 0, "CAV speedDev reconstruction must be zero")
    _require(hdv["speed_deviation"] == 0, "HDV speedDev reconstruction must be zero")
    _require(
        hdv["maximum_speed_distribution"] == "uniform_discrete_balanced",
        "HDV speed distribution must be balanced discrete",
    )
    _require(
        Decimal(str(hdv["alternative_route_probability"])) == Decimal("0.20"),
        "paper HDV alternative-route probability must be 20%",
    )
    _require(
        hdv["alternative_route_application"] == "runtime_per_intersection_only",
        "HDV alternative routing must remain runtime-only",
    )
    _require(
        not reconstruction["static_hdv_alternative_routes"], "static HDV alternatives forbidden"
    )
    _require(
        reconstruction["aggregate_total_rounding"] == "decimal_half_up",
        "aggregate total rounding must be decimal half-up",
    )
    _require(
        reconstruction["bin_quota_rule"] == "cumulative_floor",
        "bin quota rule must be cumulative floor",
    )
    _require(
        reconstruction["departure_rule"] == "evenly_spaced_bin_midpoints",
        "departure rule must use evenly spaced bin midpoints",
    )
    _require(
        reconstruction["strict_internal_edge_rule"] == "both_endpoints_are_non_gate_nodes",
        "strict internal edge rule differs",
    )
    _require(
        reconstruction["pair_sampling_rule"] == "uniform_over_reachable_pairs",
        "OD sampling must be uniform over reachable pairs",
    )
    _require(
        reconstruction["cav_route_scope_rule"]
        == "full_grid_shortest_path_gate_incident_edges_allowed",
        "CAV route scope differs",
    )
    _require(
        reconstruction["hdv_route_scope_rule"]
        == "full_grid_shortest_path_intermediate_gate_nodes_do_not_exit",
        "HDV route scope differs",
    )
    _require(
        reconstruction["initial_route_rule"] == "sumolib_shortest_distance_no_internal_edges",
        "initial routes must use SUMO shortest distance",
    )
    _require(1 <= departure_decimal_places <= 12, "departure precision must be 1-12 places")
    _require(len(gate_nodes) == 2 and len(set(gate_nodes)) == 2, "manifest must define two gates")

    return DemandSpecification(
        config=config,
        manifest=manifest,
        seed=seed,
        horizon_s=horizon_s,
        interval_s=interval_s,
        loading_levels_vph=loading_levels,
        baseline_vph=baseline_vph,
        hdv_fraction=hdv_fraction,
        cav_speed_mps=cav_speed_mps,
        hdv_speeds_mps=hdv_speeds_mps,
        departure_decimal_places=departure_decimal_places,
        gate_nodes=gate_nodes,
    )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _validate_sumolib_distribution() -> None:
    try:
        installed = distribution("sumolib")
    except PackageNotFoundError as error:
        raise RuntimeError(
            "sumolib is not installed; run `uv sync --frozen --extra dev`"
        ) from error
    _require(
        installed.version == EXPECTED_SUMOLIB_VERSION,
        f"sumolib {EXPECTED_SUMOLIB_VERSION} required; found {installed.version}",
    )
    installed_root = Path(installed.locate_file("sumolib")).resolve()
    imported_root = Path(sumolib.__file__).resolve().parent
    _require(
        imported_root == installed_root,
        "imported sumolib does not belong to the validated sumolib distribution",
    )


def _aggregate_total(rate_vph: int, horizon_s: int) -> int:
    total = Decimal(rate_vph) * Decimal(horizon_s) / Decimal(3600)
    return int(total.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _balanced_quotas(total: int, group_count: int) -> tuple[int, ...]:
    _require(total >= 0 and group_count > 0, "invalid balanced-quota inputs")
    return tuple(
        ((index + 1) * total) // group_count - (index * total) // group_count
        for index in range(group_count)
    )


def _balanced_labels(labels: tuple[Any, ...], total: int) -> list[Any]:
    quotas = _balanced_quotas(total, len(labels))
    return [label for label, quota in zip(labels, quotas, strict=True) for _ in range(quota)]


def _connection_pairs(path: Path) -> set[tuple[str, str]]:
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError) as error:
        raise RuntimeError(f"cannot parse paper-grid connections: {path}") from error
    pairs = {
        (connection.get("from", ""), connection.get("to", ""))
        for connection in root.findall("connection")
    }
    _require(len(pairs) == 102, "paper-grid connection source must contain 102 movements")
    return pairs


def _shortest_candidate(
    network: Any,
    origin_edge: Any,
    destination_edge: Any,
    connections: set[tuple[str, str]],
) -> RouteCandidate | None:
    result = network.getOptimalPath(
        origin_edge,
        destination_edge,
        fastest=False,
        withInternal=False,
    )
    if result is None or result[0] is None:
        return None
    route_edges = tuple(edge.getID() for edge in result[0])
    origin_id = origin_edge.getID()
    destination_id = destination_edge.getID()
    _require(route_edges, f"empty shortest route: {origin_id} -> {destination_id}")
    _require(route_edges[0] == origin_id, f"shortest route misses origin: {origin_id}")
    _require(
        route_edges[-1] == destination_id, f"shortest route misses destination: {destination_id}"
    )
    for first, second in pairwise(route_edges):
        _require(
            (first, second) in connections,
            f"shortest route uses movement absent from paper_grid.con.xml: {first} -> {second}",
        )
    return RouteCandidate(origin_id, destination_id, route_edges)


def _reachable_pairs(
    network: Any,
    origins: tuple[Any, ...],
    destinations: tuple[Any, ...],
    connections: set[tuple[str, str]],
    *,
    distinct: bool,
) -> tuple[RouteCandidate, ...]:
    candidates: list[RouteCandidate] = []
    for origin in origins:
        for destination in destinations:
            if distinct and origin.getID() == destination.getID():
                continue
            candidate = _shortest_candidate(network, origin, destination, connections)
            if candidate is not None:
                candidates.append(candidate)
    return tuple(candidates)


def _build_candidate_pools(
    project_root: Path, specification: DemandSpecification
) -> CandidatePools:
    _validate_sumolib_distribution()
    network_path = project_root / NETWORK_RELATIVE_DIR / NETWORK_FILE
    connection_path = project_root / NETWORK_RELATIVE_DIR / CONNECTION_FILE
    _require(network_path.is_file(), f"paper-grid network is missing: {network_path}")
    connections = _connection_pairs(connection_path)
    try:
        network = sumolib.net.readNet(str(network_path), withInternal=True)
    except Exception as error:
        raise RuntimeError(
            f"cannot load paper-grid network with sumolib: {network_path}"
        ) from error

    external_edges = tuple(
        sorted(network.getEdges(withInternal=False), key=lambda edge: edge.getID())
    )
    _require(len(external_edges) == 54, "paper-grid network must have 54 external edges")
    gate_set = set(specification.gate_nodes)
    network_nodes = {node.getID() for node in network.getNodes()}
    _require(gate_set <= network_nodes, "manifest gate node is missing from network")
    strict_edges = tuple(
        edge
        for edge in external_edges
        if edge.getFromNode().getID() not in gate_set and edge.getToNode().getID() not in gate_set
    )
    _require(
        len(strict_edges) == EXPECTED_STRICT_INTERNAL_EDGES,
        f"expected 42 strict internal edges, found {len(strict_edges)}",
    )

    cav_pairs = _reachable_pairs(
        network,
        strict_edges,
        strict_edges,
        connections,
        distinct=True,
    )
    cav_possible = len(strict_edges) * (len(strict_edges) - 1)
    _require(cav_pairs, "no reachable CAV OD pairs")

    category_order = tuple(
        str(value)
        for value in specification.config["demand"]["reconstruction"]["hdv_category_order"]
    )
    expected_categories = (
        "gate1_inbound",
        "gate2_inbound",
        "gate1_outbound",
        "gate2_outbound",
    )
    _require(category_order == expected_categories, "HDV category order differs")

    hdv_pairs: dict[str, tuple[RouteCandidate, ...]] = {}
    hdv_candidate_counts: dict[str, dict[str, int]] = {}
    for gate_index, gate_node in enumerate(specification.gate_nodes, start=1):
        gate_origins = tuple(
            edge for edge in external_edges if edge.getFromNode().getID() == gate_node
        )
        gate_destinations = tuple(
            edge for edge in external_edges if edge.getToNode().getID() == gate_node
        )
        _require(gate_origins and gate_destinations, f"gate lacks entry/exit roads: {gate_node}")
        category_specs = (
            (f"gate{gate_index}_inbound", gate_origins, strict_edges),
            (f"gate{gate_index}_outbound", strict_edges, gate_destinations),
        )
        for name, origins, destinations in category_specs:
            reachable = _reachable_pairs(
                network,
                origins,
                destinations,
                connections,
                distinct=False,
            )
            _require(reachable, f"no reachable HDV OD pairs for {name}")
            hdv_pairs[name] = reachable
            hdv_candidate_counts[name] = {
                "origin_edges": len(origins),
                "destination_edges": len(destinations),
                "possible_pairs": len(origins) * len(destinations),
                "reachable_pairs": len(reachable),
            }
    _require(set(hdv_pairs) == set(category_order), "HDV candidate categories differ")

    candidate_counts = {
        "external_edges": len(external_edges),
        "strict_internal_edges": len(strict_edges),
        "cav": {
            "origin_edges": len(strict_edges),
            "destination_edges": len(strict_edges),
            "possible_distinct_pairs": cav_possible,
            "reachable_pairs": len(cav_pairs),
        },
        "hdv": {name: hdv_candidate_counts[name] for name in category_order},
    }
    return CandidatePools(
        strict_internal_edges=tuple(edge.getID() for edge in strict_edges),
        cav=cav_pairs,
        hdv={name: hdv_pairs[name] for name in category_order},
        candidate_counts=candidate_counts,
    )


def _format_decimal(value: Decimal, places: int) -> str:
    quantum = Decimal(1).scaleb(-places)
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    rendered = format(rounded, "f").rstrip("0").rstrip(".")
    return rendered or "0"


def _departures(specification: DemandSpecification) -> tuple[tuple[str, int], ...]:
    total = _aggregate_total(specification.baseline_vph, specification.horizon_s)
    bin_count = specification.horizon_s // specification.interval_s
    quotas = _balanced_quotas(total, bin_count)
    departures: list[tuple[str, int]] = []
    with localcontext() as context:
        context.prec = 40
        width = Decimal(specification.interval_s)
        for bin_index, quota in enumerate(quotas):
            start = Decimal(bin_index * specification.interval_s)
            for position in range(quota):
                departure = start + (Decimal(position) + Decimal("0.5")) * width / Decimal(quota)
                departures.append(
                    (
                        _format_decimal(departure, specification.departure_decimal_places),
                        bin_index,
                    )
                )
    _require(len(departures) == total, "departure generation changed aggregate total")
    _require(
        all(Decimal(first[0]) <= Decimal(second[0]) for first, second in pairwise(departures)),
        "departures are not time ordered",
    )
    _require(
        Decimal(departures[-1][0]) < specification.horizon_s,
        "departure exceeds departure horizon",
    )
    return tuple(departures)


def _serialize_xml(root: ElementTree.Element) -> str:
    ElementTree.indent(root, space="    ")
    xml = ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)
    return XML_DECLARATION + xml + "\n"


def _render_demand(
    specification: DemandSpecification,
    pools: CandidatePools,
) -> tuple[str, dict[str, Any]]:
    total = _aggregate_total(specification.baseline_vph, specification.horizon_s)
    hdv_total = int(
        (Decimal(total) * specification.hdv_fraction).quantize(
            Decimal(1),
            rounding=ROUND_HALF_UP,
        )
    )
    cav_total = total - hdv_total
    _require(
        (total, hdv_total, cav_total)
        == (EXPECTED_BASELINE_TOTAL, EXPECTED_BASELINE_HDV, EXPECTED_BASELINE_CAV),
        "baseline totals must be 4000/400/3600",
    )

    rng = random.Random(specification.seed)
    vehicle_classes = ["hdv"] * hdv_total + ["cav"] * cav_total
    rng.shuffle(vehicle_classes)
    category_order = tuple(pools.hdv)
    hdv_categories = _balanced_labels(category_order, hdv_total)
    rng.shuffle(hdv_categories)
    speed_labels = _balanced_labels(specification.hdv_speeds_mps, hdv_total)
    rng.shuffle(speed_labels)
    category_iterator = iter(hdv_categories)
    speed_iterator = iter(speed_labels)

    root = ElementTree.Element(
        "routes",
        {
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:noNamespaceSchemaLocation": "https://sumo.dlr.de/xsd/routes_file.xsd",
        },
    )
    ElementTree.SubElement(
        root,
        "vType",
        {
            "id": f"cav_{specification.cav_speed_mps}",
            "maxSpeed": str(specification.cav_speed_mps),
            "speedDev": "0",
        },
    )
    for speed in specification.hdv_speeds_mps:
        ElementTree.SubElement(
            root,
            "vType",
            {"id": f"hdv_{speed}", "maxSpeed": str(speed), "speedDev": "0"},
        )

    direction_counts: Counter[str] = Counter()
    gate_counts: Counter[str] = Counter()
    speed_counts: Counter[str] = Counter()
    class_counts: Counter[str] = Counter()
    bin_class_counts: dict[int, Counter[str]] = {}
    route_length_counts: Counter[int] = Counter()
    departures = _departures(specification)
    for vehicle_index, ((departure, bin_index), vehicle_class) in enumerate(
        zip(departures, vehicle_classes, strict=True)
    ):
        class_counts[vehicle_class] += 1
        bin_class_counts.setdefault(bin_index, Counter())[vehicle_class] += 1
        if vehicle_class == "hdv":
            category = next(category_iterator)
            speed = next(speed_iterator)
            candidate = rng.choice(pools.hdv[category])
            type_id = f"hdv_{speed}"
            direction = "inbound" if category.endswith("_inbound") else "outbound"
            gate = category.split("_", maxsplit=1)[0]
            direction_counts[direction] += 1
            gate_counts[gate] += 1
            speed_counts[str(speed)] += 1
        else:
            candidate = rng.choice(pools.cav)
            type_id = f"cav_{specification.cav_speed_mps}"
            speed_counts[str(specification.cav_speed_mps)] += 1
        route_length_counts[len(candidate.route_edges)] += 1
        vehicle = ElementTree.SubElement(
            root,
            "vehicle",
            {
                "id": f"veh_{vehicle_index:04d}",
                "type": type_id,
                "depart": departure,
                "departLane": "best",
                "departPos": "base",
                "departSpeed": "max",
                "arrivalPos": "max",
            },
        )
        ElementTree.SubElement(vehicle, "route", {"edges": " ".join(candidate.route_edges)})

    try:
        next(category_iterator)
    except StopIteration:
        pass
    else:
        raise RuntimeError("unused HDV category labels remain")
    try:
        next(speed_iterator)
    except StopIteration:
        pass
    else:
        raise RuntimeError("unused HDV speed labels remain")

    expected_category_counts = dict(
        zip(category_order, _balanced_quotas(hdv_total, 4), strict=True)
    )
    actual_category_counts = Counter(hdv_categories)
    _require(
        dict(actual_category_counts) == expected_category_counts, "HDV categories are not balanced"
    )
    _require(
        all(speed_counts[str(speed)] == hdv_total // 4 for speed in specification.hdv_speeds_mps),
        "HDV maximum-speed types are not balanced",
    )
    _require(class_counts == {"hdv": hdv_total, "cav": cav_total}, "vehicle class counts differ")

    details = {
        "counts": {
            "vehicles": total,
            "hdv": hdv_total,
            "cav": cav_total,
            "vtypes": 5,
            "bins": len(bin_class_counts),
        },
        "hdv_od_direction_counts": {
            "hdv_inbound": direction_counts["inbound"],
            "hdv_outbound": direction_counts["outbound"],
            "hdv_categories": {name: actual_category_counts[name] for name in category_order},
        },
        "hdv_od_gate_counts": {name: gate_counts[name] for name in ("gate1", "gate2")},
        "speed_counts": {
            "cav_14": class_counts["cav"],
            "hdv": {
                str(speed): Counter(speed_labels)[speed] for speed in specification.hdv_speeds_mps
            },
        },
        "route_edge_count_distribution": {
            str(length): count for length, count in sorted(route_length_counts.items())
        },
        "bin_class_counts": {
            index: {
                "vehicles": counts["cav"] + counts["hdv"],
                "cav": counts["cav"],
                "hdv": counts["hdv"],
            }
            for index, counts in sorted(bin_class_counts.items())
        },
    }
    return _serialize_xml(root), details


def _bin_metadata(
    specification: DemandSpecification, details: dict[str, Any]
) -> list[dict[str, Any]]:
    bin_count = specification.horizon_s // specification.interval_s
    level_quotas = {
        str(rate): _balanced_quotas(
            _aggregate_total(rate, specification.horizon_s),
            bin_count,
        )
        for rate in specification.loading_levels_vph
    }
    bins = []
    for index in range(bin_count):
        class_counts = details["bin_class_counts"][index]
        bins.append(
            {
                "index": index,
                "start_s": index * specification.interval_s,
                "end_s": (index + 1) * specification.interval_s,
                "quota_by_loading_level_vph": {
                    rate: quotas[index] for rate, quotas in level_quotas.items()
                },
                "baseline_class_counts": class_counts,
            }
        )
    return bins


def _render_metadata(
    project_root: Path,
    specification: DemandSpecification,
    pools: CandidatePools,
    route_text: str,
    details: dict[str, Any],
) -> str:
    config_path = project_root / CONFIG_RELATIVE_PATH
    network_dir = project_root / NETWORK_RELATIVE_DIR
    generator_path = project_root / GENERATOR_RELATIVE_PATH
    config_reconstruction = specification.config["demand"]["reconstruction"]
    hdv = specification.config["vehicles"]["hdv"]
    metadata = {
        "schema_version": 1,
        "generator": GENERATOR_RELATIVE_PATH,
        "toolchain": {
            "sumo_distribution": "eclipse-sumo",
            "sumo_version": EXPECTED_SUMO_VERSION,
            "sumolib_distribution": "sumolib",
            "sumolib_version": EXPECTED_SUMOLIB_VERSION,
        },
        "paper_facts": {
            "loading_levels_vehicles_per_hour": list(specification.loading_levels_vph),
            "loading_interval_s": specification.interval_s,
            "hdv_od_rule": specification.config["demand"]["paper_hdv_od_rule"],
            "cav_od_rule": specification.config["demand"]["paper_cav_od_rule"],
            "main_comparison_hdv_penetration": float(specification.hdv_fraction),
            "cav_maximum_speed_mps": specification.cav_speed_mps,
            "hdv_maximum_speed_range_mps": [
                min(specification.hdv_speeds_mps),
                max(specification.hdv_speeds_mps),
            ],
            "hdv_alternative_route_probability": float(hdv["alternative_route_probability"]),
        },
        "reconstruction": {
            "baseline_vehicles_per_hour": specification.baseline_vph,
            "random_seed": specification.seed,
            **config_reconstruction,
        },
        "assumptions": [
            "The 7200 s departure horizon is inferred from figure axes, not published as a parameter.",
            "CAV endpoints are strict-internal; shortest routes may use gate-incident grid roads because the reconstructed gates add no external connectors.",
            "HDV gate counts describe OD categories; crossing an intermediate gate-labeled junction does not exit because this reconstruction has no gate connector edges.",
            "HDV maximum speeds use four exactly balanced discrete types at 9, 10, 11, and 12 m/s.",
            "Unpublished vehicle dynamics retain SUMO defaults.",
            "Static routes are distance-shortest; HDV 20% alternatives belong to the runtime controller.",
        ],
        "counts": details["counts"],
        "bins": _bin_metadata(specification, details),
        "gate_nodes": list(specification.gate_nodes),
        "hdv_od_direction_counts": details["hdv_od_direction_counts"],
        "hdv_od_gate_counts": details["hdv_od_gate_counts"],
        "speed_counts": details["speed_counts"],
        "candidate_counts": pools.candidate_counts,
        "route_edge_count_distribution": details["route_edge_count_distribution"],
        "hdv_alternative_route": {
            "probability": float(hdv["alternative_route_probability"]),
            "application": "runtime_per_intersection_only",
            "baked_into_static_routes": False,
        },
        "hashes": {
            "config_sha256": _sha256(config_path.read_bytes()),
            "network_sha256": _sha256((network_dir / NETWORK_FILE).read_bytes()),
            "route_sha256": _sha256(route_text.encode("utf-8")),
            "source_sha256": {
                GENERATOR_RELATIVE_PATH: _sha256(generator_path.read_bytes()),
                LOCK_RELATIVE_PATH: _sha256((project_root / LOCK_RELATIVE_PATH).read_bytes()),
                str(NETWORK_RELATIVE_DIR / MANIFEST_FILE).replace("\\", "/"): _sha256(
                    (network_dir / MANIFEST_FILE).read_bytes()
                ),
                str(NETWORK_RELATIVE_DIR / CONNECTION_FILE).replace("\\", "/"): _sha256(
                    (network_dir / CONNECTION_FILE).read_bytes()
                ),
            },
        },
    }
    return json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _generate(project_root: Path) -> GeneratedDemand:
    specification = _load_specification(project_root)
    pools = _build_candidate_pools(project_root, specification)
    route_text, details = _render_demand(specification, pools)
    metadata_text = _render_metadata(
        project_root,
        specification,
        pools,
        route_text,
        details,
    )
    return GeneratedDemand(route_text, metadata_text, details["counts"])


def _validate_route_xml(route_text: str, project_root: Path) -> dict[str, int]:
    try:
        root = ElementTree.fromstring(route_text)
    except ElementTree.ParseError as error:
        raise RuntimeError("generated demand XML is invalid") from error
    vtypes = root.findall("vType")
    vehicles = root.findall("vehicle")
    _require(len(vtypes) == 5, "demand must define five deterministic vTypes")
    expected_vtypes = {
        "cav_14": ("14", "0"),
        "hdv_9": ("9", "0"),
        "hdv_10": ("10", "0"),
        "hdv_11": ("11", "0"),
        "hdv_12": ("12", "0"),
    }
    actual_vtypes = {
        vtype.get("id", ""): (vtype.get("maxSpeed", ""), vtype.get("speedDev", ""))
        for vtype in vtypes
    }
    _require(actual_vtypes == expected_vtypes, "demand vType speeds or deviations differ")
    _require(len(vehicles) == EXPECTED_BASELINE_TOTAL, "demand must contain 4000 vehicles")
    ids = [vehicle.get("id", "") for vehicle in vehicles]
    _require(len(ids) == len(set(ids)), "vehicle IDs must be unique")
    departures = [Decimal(vehicle.get("depart", "nan")) for vehicle in vehicles]
    _require(
        all(first <= second for first, second in pairwise(departures)),
        "vehicles must be time ordered",
    )
    connections = _connection_pairs(project_root / NETWORK_RELATIVE_DIR / CONNECTION_FILE)
    for vehicle in vehicles:
        route = vehicle.find("route")
        _require(route is not None, f"vehicle lacks inline route: {vehicle.get('id')}")
        edges = route.get("edges", "").split()
        _require(edges, f"vehicle route is empty: {vehicle.get('id')}")
        for first, second in pairwise(edges):
            _require(
                (first, second) in connections,
                f"vehicle route uses illegal movement: {first} -> {second}",
            )
    return {"vehicles": len(vehicles), "vtypes": len(vtypes)}


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
    _require(
        package_root.is_dir(), f"eclipse-sumo distribution has no SUMO directory: {package_root}"
    )
    return package_root


def _validate_sumo_load(network_path: Path, route_path: Path) -> None:
    """Ask SUMO to parse every route; this does not simulate departures or completion."""

    sumo_home = _wheel_sumo_home()
    binary_name = "sumo.exe" if os.name == "nt" else "sumo"
    binary = sumo_home / "bin" / binary_name
    _require(binary.is_file(), f"wheel-bundled SUMO not found: {binary}")
    command = [
        str(binary),
        "--net-file",
        str(network_path),
        "--route-files",
        str(route_path),
        "--begin",
        "0",
        "--end",
        "0",
        "--route-steps",
        "0",
        "--no-warnings",
        "true",
        "--no-step-log",
        "true",
        "--duration-log.disable",
        "true",
    ]
    child_env = os.environ.copy()
    child_env["SUMO_HOME"] = str(sumo_home)
    child_env["PATH"] = os.pathsep.join((str(sumo_home / "bin"), child_env.get("PATH", "")))
    completed = subprocess.run(
        command,
        cwd=project_root_for(network_path),
        env=child_env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        details = "\n".join(
            part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
        )
        raise RuntimeError(
            f"SUMO demand load failed with exit code {completed.returncode}\n{details}"
        )


def project_root_for(network_path: Path) -> Path:
    """Return a stable existing working directory for SUMO validation."""

    return network_path.resolve().parents[3]


def validate_artifacts(project_root: Path = PROJECT_ROOT) -> dict[str, int]:
    """Validate committed demand assets against config, network, and generator."""

    generated = _generate(project_root)
    demand_dir = project_root / DEMAND_RELATIVE_DIR
    route_path = demand_dir / ROUTE_FILE
    metadata_path = demand_dir / METADATA_FILE
    _require(route_path.is_file(), f"committed demand is missing: {route_path}")
    _require(metadata_path.is_file(), f"committed demand metadata is missing: {metadata_path}")
    _require(
        route_path.read_text(encoding="utf-8") == generated.route_text, "demand route is stale"
    )
    _require(
        metadata_path.read_text(encoding="utf-8") == generated.metadata_text,
        "demand metadata is stale",
    )
    xml_counts = _validate_route_xml(generated.route_text, project_root)
    return {**generated.counts, **xml_counts}


def build_demand(project_root: Path = PROJECT_ROOT) -> Path:
    """Build committed route and metadata files from the baseline TOML config."""

    generated = _generate(project_root)
    demand_dir = project_root / DEMAND_RELATIVE_DIR
    demand_dir.mkdir(parents=True, exist_ok=True)
    route_path = demand_dir / ROUTE_FILE
    metadata_path = demand_dir / METADATA_FILE
    route_path.write_text(generated.route_text, encoding="utf-8", newline="")
    metadata_path.write_text(generated.metadata_text, encoding="utf-8", newline="")
    counts = validate_artifacts(project_root)
    _validate_sumo_load(project_root / NETWORK_RELATIVE_DIR / NETWORK_FILE, route_path)
    print(f"built {route_path} ({counts})")
    return route_path


def check_demand(project_root: Path = PROJECT_ROOT) -> Path:
    """Check committed demand, deterministic rebuild, and static SUMO parseability."""

    route_path = project_root / DEMAND_RELATIVE_DIR / ROUTE_FILE
    committed_counts = validate_artifacts(project_root)
    generated = _generate(project_root)
    with TemporaryDirectory(prefix="irbp-paper-demand-") as temporary_dir:
        rebuilt_dir = Path(temporary_dir)
        rebuilt_route = rebuilt_dir / ROUTE_FILE
        rebuilt_metadata = rebuilt_dir / METADATA_FILE
        rebuilt_route.write_text(generated.route_text, encoding="utf-8", newline="")
        rebuilt_metadata.write_text(generated.metadata_text, encoding="utf-8", newline="")
        _require(
            route_path.read_bytes() == rebuilt_route.read_bytes(),
            "route rebuild is not byte-stable",
        )
        committed_metadata = project_root / DEMAND_RELATIVE_DIR / METADATA_FILE
        _require(
            committed_metadata.read_bytes() == rebuilt_metadata.read_bytes(),
            "metadata rebuild is not byte-stable",
        )
        _validate_sumo_load(
            project_root / NETWORK_RELATIVE_DIR / NETWORK_FILE,
            rebuilt_route,
        )
    print(f"checked {route_path} ({committed_counts})")
    return route_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify committed generated demand without rewriting repository files",
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        arguments = _parse_args()
        check_demand() if arguments.check else build_demand()
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
