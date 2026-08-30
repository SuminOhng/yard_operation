"""Reusable TraCI boundary helpers for live IR-BP simulations.

This module owns SUMO discovery, subscribed-state observations, immutable
snapshot construction, signal commands, and transactional route mutation.
Policy equations remain in :mod:`irbp_replica.control` and
:mod:`irbp_replica.routing`.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from importlib.metadata import distribution, version
from math import hypot
from pathlib import Path
from typing import Any

import traci
from traci import constants as tc

from irbp_replica.control.vtr import validate_single_activation
from irbp_replica.domain.models import (
    PhaseState,
    RoadState,
    RoutingCandidateState,
    VehicleKind,
    VehicleState,
)

__all__ = (
    "TraCIAdapterError",
    "candidate_snapshot",
    "commit_route",
    "controlled_link_indexes",
    "edge_lane_ids",
    "edge_length",
    "outgoing_edges",
    "queue_leader_kind",
    "queue_vehicle_ids",
    "reachable_stage",
    "remaining_capacity_slots",
    "restore_environment",
    "road_snapshot",
    "signal_state",
    "subscribe_normal_lanes",
    "sumo_installation",
    "validate_lane_subscriptions",
    "validate_server_version",
    "validate_vehicle_subscriptions",
    "vehicle_kind",
    "vehicle_subscription_value",
    "vehicles_on_edge",
)


class TraCIAdapterError(RuntimeError):
    """Raised when a live TraCI boundary invariant fails."""


ErrorType = type[RuntimeError]


def sumo_installation(
    expected_version: str,
    *,
    error_type: ErrorType = TraCIAdapterError,
) -> tuple[Path, Path]:
    """Return wheel-owned SUMO home and binary after exact-version validation."""

    package_version = version("eclipse-sumo")
    if package_version != expected_version:
        raise error_type(f"eclipse-sumo {expected_version} required; found {package_version}")
    sumo_home = Path(distribution("eclipse-sumo").locate_file("sumo")).resolve()
    binary_name = "sumo.exe" if os.name == "nt" else "sumo"
    binary = sumo_home / "bin" / binary_name
    if not binary.is_file():
        raise error_type(f"wheel SUMO executable not found: {binary}")
    return sumo_home, binary


def validate_server_version(
    connection: Any,
    expected_sumo_version: str,
    expected_traci_protocol: int,
    *,
    error_type: ErrorType = TraCIAdapterError,
) -> tuple[int, str]:
    """Validate client/server protocol and exact SUMO server version."""

    protocol, server_version = connection.getVersion()
    if protocol != expected_traci_protocol or protocol != tc.TRACI_VERSION:
        raise error_type(
            "TraCI protocol mismatch: "
            f"expected {expected_traci_protocol}, client {tc.TRACI_VERSION}, "
            f"server {protocol}"
        )
    if server_version != f"SUMO {expected_sumo_version}":
        raise error_type(f"SUMO server {expected_sumo_version} required; found {server_version}")
    return protocol, server_version


def restore_environment(name: str, old_value: str | None) -> None:
    """Restore one process environment variable to its previous value."""

    if old_value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = old_value


def edge_lane_ids(network: Any, edge_id: str) -> tuple[str, ...]:
    """Return stable lane IDs for one SUMO edge."""

    return tuple(lane.getID() for lane in network.getEdge(edge_id).getLanes())


def vehicle_subscription_value(
    connection: Any,
    vehicle_id: str,
    variable: int,
    *,
    error_type: ErrorType = TraCIAdapterError,
) -> Any:
    """Read one required cached vehicle subscription value."""

    results = connection.vehicle.getSubscriptionResults(vehicle_id)
    if results is None or variable not in results:
        raise error_type(f"vehicle subscription variable {variable} unavailable: {vehicle_id}")
    return results[variable]


def vehicle_kind(
    connection: Any,
    vehicle_id: str,
    vehicle_kind_by_type_id: Mapping[str, VehicleKind],
    *,
    error_type: ErrorType = TraCIAdapterError,
) -> VehicleKind:
    """Map one subscribed SUMO type ID to the policy vehicle kind."""

    type_id = str(
        vehicle_subscription_value(
            connection,
            vehicle_id,
            tc.VAR_TYPE,
            error_type=error_type,
        )
    )
    try:
        return vehicle_kind_by_type_id[type_id]
    except KeyError as exc:
        raise error_type(f"unknown vehicle type for kind mapping: {type_id}") from exc


def vehicles_on_edge(
    connection: Any,
    network: Any,
    edge_id: str,
    *,
    error_type: ErrorType = TraCIAdapterError,
) -> tuple[str, ...]:
    """Return sorted vehicle IDs observed through lane subscriptions."""

    vehicle_ids: set[str] = set()
    for lane_id in edge_lane_ids(network, edge_id):
        results = connection.lane.getSubscriptionResults(lane_id)
        if results is None or tc.LAST_STEP_VEHICLE_ID_LIST not in results:
            raise error_type(f"lane vehicle-ID subscription unavailable: {lane_id}")
        vehicle_ids.update(results[tc.LAST_STEP_VEHICLE_ID_LIST])
    return tuple(sorted(vehicle_ids))


def queue_vehicle_ids(
    connection: Any,
    network: Any,
    edge_id: str,
    queue_speed_threshold_mps: float,
    *,
    error_type: ErrorType = TraCIAdapterError,
) -> tuple[str, ...]:
    """Return subscribed vehicles at or below the configured queue threshold."""

    return tuple(
        vehicle_id
        for vehicle_id in vehicles_on_edge(
            connection,
            network,
            edge_id,
            error_type=error_type,
        )
        if float(
            vehicle_subscription_value(
                connection,
                vehicle_id,
                tc.VAR_SPEED,
                error_type=error_type,
            )
        )
        <= queue_speed_threshold_mps
    )


def queue_leader_kind(
    connection: Any,
    network: Any,
    edge_id: str,
    vehicle_kind_by_type_id: Mapping[str, VehicleKind],
    queue_speed_threshold_mps: float,
    *,
    error_type: ErrorType = TraCIAdapterError,
) -> VehicleKind | None:
    """Return kind of the queued vehicle closest to the edge end."""

    queued = queue_vehicle_ids(
        connection,
        network,
        edge_id,
        queue_speed_threshold_mps,
        error_type=error_type,
    )
    if not queued:
        return None
    leader_id = min(
        queued,
        key=lambda vehicle_id: (
            -float(
                vehicle_subscription_value(
                    connection,
                    vehicle_id,
                    tc.VAR_LANEPOSITION,
                    error_type=error_type,
                )
            ),
            vehicle_id,
        ),
    )
    return vehicle_kind(
        connection,
        leader_id,
        vehicle_kind_by_type_id,
        error_type=error_type,
    )


def edge_length(
    connection: Any,
    network: Any,
    edge_id: str,
    *,
    error_type: ErrorType = TraCIAdapterError,
) -> float:
    """Return maximum lane length for one normal edge."""

    lane_ids = edge_lane_ids(network, edge_id)
    if not lane_ids:
        raise error_type(f"edge has no lanes: {edge_id}")
    return max(float(connection.lane.getLength(lane_id)) for lane_id in lane_ids)


def remaining_capacity_slots(
    connection: Any,
    network: Any,
    edge_id: str,
    vehicle_slot_m: float,
    *,
    error_type: ErrorType = TraCIAdapterError,
) -> float:
    """Return unoccupied vehicle-equivalent slots across all edge lanes."""

    lane_ids = edge_lane_ids(network, edge_id)
    total_slots = sum(
        int(float(connection.lane.getLength(lane_id)) // vehicle_slot_m) for lane_id in lane_ids
    )
    occupied = 0
    for lane_id in lane_ids:
        results = connection.lane.getSubscriptionResults(lane_id)
        if results is None or tc.LAST_STEP_VEHICLE_NUMBER not in results:
            raise error_type(f"lane vehicle-count subscription unavailable: {lane_id}")
        occupied += int(results[tc.LAST_STEP_VEHICLE_NUMBER])
    return float(max(total_slots - occupied, 0))


def road_snapshot(
    connection: Any,
    network: Any,
    phases: Iterable[PhaseState],
    *,
    vehicle_slot_m: float,
    queue_speed_threshold_mps: float,
    error_type: ErrorType = TraCIAdapterError,
) -> dict[str, RoadState]:
    """Build immutable road inputs required by the pure BP controller."""

    phases = tuple(phases)
    edge_ids = {
        edge_id
        for phase in phases
        for edge_id in (phase.upstream_edge_id, *phase.downstream_edge_ids)
    }
    roads: dict[str, RoadState] = {}
    upstream_ids = {phase.upstream_edge_id for phase in phases}
    for edge_id in sorted(edge_ids):
        roads[edge_id] = RoadState(
            edge_id=edge_id,
            length_m=edge_length(
                connection,
                network,
                edge_id,
                error_type=error_type,
            ),
            queue_vehicles=float(
                len(
                    queue_vehicle_ids(
                        connection,
                        network,
                        edge_id,
                        queue_speed_threshold_mps,
                        error_type=error_type,
                    )
                )
                if edge_id in upstream_ids
                else 0
            ),
            remaining_capacity_vehicles=remaining_capacity_slots(
                connection,
                network,
                edge_id,
                vehicle_slot_m,
                error_type=error_type,
            ),
        )
    return roads


def controlled_link_indexes(
    connection: Any,
    tls_id: str,
    required_incoming_edge_ids: Iterable[str],
    *,
    error_type: ErrorType = TraCIAdapterError,
) -> tuple[dict[str, tuple[int, ...]], int]:
    """Discover controlled-link indexes grouped by incoming normal edge."""

    groups = tuple(connection.trafficlight.getControlledLinks(tls_id))
    if not groups:
        raise error_type(f"traffic light has no controlled links: {tls_id}")
    indexes: dict[str, list[int]] = {}
    for link_index, group in enumerate(groups):
        if not group:
            continue
        incoming_edges = {connection.lane.getEdgeID(link[0]) for link in group}
        if len(incoming_edges) != 1:
            raise error_type(f"controlled link index {link_index} has multiple incoming edges")
        incoming_edge = incoming_edges.pop()
        indexes.setdefault(incoming_edge, []).append(link_index)
    missing = sorted(set(required_incoming_edge_ids) - set(indexes))
    if missing:
        raise error_type(f"traffic light omits controlled incoming edges: {missing}")
    return (
        {edge_id: tuple(values) for edge_id, values in sorted(indexes.items())},
        len(groups),
    )


def subscribe_normal_lanes(
    connection: Any,
    network: Any,
    *,
    error_type: ErrorType = TraCIAdapterError,
    empty_network_message: str = "network has no normal lanes",
) -> tuple[str, ...]:
    """Subscribe lane vehicle IDs and counts for every non-internal edge."""

    lane_ids = tuple(
        sorted(
            lane.getID()
            for edge in network.getEdges(withInternal=False)
            for lane in edge.getLanes()
        )
    )
    if not lane_ids:
        raise error_type(empty_network_message)
    for lane_id in lane_ids:
        connection.lane.subscribe(
            lane_id,
            (
                tc.LAST_STEP_VEHICLE_ID_LIST,
                tc.LAST_STEP_VEHICLE_NUMBER,
            ),
        )
    return lane_ids


def validate_lane_subscriptions(
    connection: Any,
    lane_ids: Iterable[str],
    *,
    error_type: ErrorType = TraCIAdapterError,
) -> None:
    """Verify cached lane observations against direct TraCI reads."""

    for lane_id in lane_ids:
        results = connection.lane.getSubscriptionResults(lane_id)
        if results is None:
            raise error_type(f"missing lane subscription result: {lane_id}")
        if tc.LAST_STEP_VEHICLE_ID_LIST not in results:
            raise error_type(f"lane vehicle-ID subscription missing: {lane_id}")
        if tc.LAST_STEP_VEHICLE_NUMBER not in results:
            raise error_type(f"lane vehicle-count subscription missing: {lane_id}")
        subscribed_ids = tuple(sorted(results[tc.LAST_STEP_VEHICLE_ID_LIST]))
        direct_ids = tuple(sorted(connection.lane.getLastStepVehicleIDs(lane_id)))
        subscribed_count = int(results[tc.LAST_STEP_VEHICLE_NUMBER])
        direct_count = int(connection.lane.getLastStepVehicleNumber(lane_id))
        if subscribed_ids != direct_ids:
            raise error_type(f"lane vehicle-ID subscription mismatch: {lane_id}")
        if subscribed_count != direct_count or subscribed_count != len(subscribed_ids):
            raise error_type(f"lane vehicle-count subscription mismatch: {lane_id}")


def validate_vehicle_subscriptions(
    connection: Any,
    vehicle_ids: Iterable[str],
    *,
    error_type: ErrorType = TraCIAdapterError,
) -> int:
    """Verify cached vehicle observations against direct TraCI reads."""

    vehicle_ids = tuple(sorted(vehicle_ids))
    for vehicle_id in vehicle_ids:
        expected = {
            tc.VAR_ROAD_ID: connection.vehicle.getRoadID(vehicle_id),
            tc.VAR_SPEED: connection.vehicle.getSpeed(vehicle_id),
            tc.VAR_LANEPOSITION: connection.vehicle.getLanePosition(vehicle_id),
            tc.VAR_TYPE: connection.vehicle.getTypeID(vehicle_id),
            tc.VAR_LANE_ID: connection.vehicle.getLaneID(vehicle_id),
        }
        for variable, direct_value in expected.items():
            subscribed_value = vehicle_subscription_value(
                connection,
                vehicle_id,
                variable,
                error_type=error_type,
            )
            if subscribed_value != direct_value:
                raise error_type(
                    f"vehicle subscription mismatch for {vehicle_id}, variable {variable}"
                )
    return len(vehicle_ids)


def signal_state(
    active_phase_id: str | None,
    phases: Iterable[PhaseState],
    link_indexes: Mapping[str, tuple[int, ...]],
    state_length: int,
    *,
    error_type: ErrorType = TraCIAdapterError,
) -> str:
    """Render one mutually exclusive VTR activation as a SUMO TLS state."""

    states = ["r"] * state_length
    if active_phase_id is None:
        return "".join(states)
    phases = tuple(phases)
    phase_by_id = {phase.phase_id: phase for phase in phases}
    try:
        phase = phase_by_id[active_phase_id]
    except KeyError as exc:
        raise error_type(f"unknown active phase: {active_phase_id}") from exc
    validate_single_activation(phases, (active_phase_id,), (phase.station_id,))
    for link_index in link_indexes[phase.upstream_edge_id]:
        states[link_index] = "G"
    return "".join(states)


def outgoing_edges(network: Any, current_edge_id: str) -> tuple[Any, ...]:
    """Return sorted non-internal outgoing edges from one current edge."""

    current_edge = network.getEdge(current_edge_id)
    return tuple(
        sorted(
            (edge for edge in current_edge.getOutgoing() if not edge.getID().startswith(":")),
            key=lambda edge: edge.getID(),
        )
    )


def reachable_stage(
    connection: Any,
    candidate_edge_id: str,
    destination_edge_id: str,
    vehicle_type_id: str,
    simulation_time_s: float,
    arrival_position_m: float,
) -> Any | None:
    """Return a SUMO route stage only when it spans candidate to destination."""

    try:
        stage = connection.simulation.findRoute(
            candidate_edge_id,
            destination_edge_id,
            vType=vehicle_type_id,
            depart=simulation_time_s,
            departPos=0.0,
            arrivalPos=arrival_position_m,
        )
    except traci.TraCIException:
        return None
    edges = tuple(stage.edges)
    if not edges or edges[0] != candidate_edge_id or edges[-1] != destination_edge_id:
        return None
    return stage


def candidate_snapshot(
    connection: Any,
    network: Any,
    routing_vehicle_id: str,
    candidate_edge: Any,
    simulation_time_s: float,
    destination_edge_id: str,
    arrival_position_m: float,
    destination_position_m: tuple[float, float],
    vehicle_kind_by_type_id: Mapping[str, VehicleKind],
    *,
    heuristic_tolerance_m: float = 1e-6,
    error_type: ErrorType = TraCIAdapterError,
) -> tuple[RoutingCandidateState, Any | None]:
    """Build one Algorithm 3 candidate and its reachable SUMO suffix."""

    edge_id = candidate_edge.getID()
    lane_ids = edge_lane_ids(network, edge_id)
    length_m = max(float(connection.lane.getLength(lane_id)) for lane_id in lane_ids)
    observed_vehicles: list[VehicleState] = []
    for vehicle_id in vehicles_on_edge(
        connection,
        network,
        edge_id,
        error_type=error_type,
    ):
        lane_id = str(
            vehicle_subscription_value(
                connection,
                vehicle_id,
                tc.VAR_LANE_ID,
                error_type=error_type,
            )
        )
        remaining_m = max(
            float(connection.lane.getLength(lane_id))
            - float(
                vehicle_subscription_value(
                    connection,
                    vehicle_id,
                    tc.VAR_LANEPOSITION,
                    error_type=error_type,
                )
            ),
            0.0,
        )
        observed_vehicles.append(
            VehicleState(
                vehicle_id=vehicle_id,
                vehicle_kind=vehicle_kind(
                    connection,
                    vehicle_id,
                    vehicle_kind_by_type_id,
                    error_type=error_type,
                ),
                edge_id=edge_id,
                speed_mps=max(
                    float(
                        vehicle_subscription_value(
                            connection,
                            vehicle_id,
                            tc.VAR_SPEED,
                            error_type=error_type,
                        )
                    ),
                    0.0,
                ),
                remaining_distance_m=min(remaining_m, length_m),
                destination_edge_id=connection.vehicle.getRoute(vehicle_id)[-1],
            )
        )
    vehicle_type_id = str(
        vehicle_subscription_value(
            connection,
            routing_vehicle_id,
            tc.VAR_TYPE,
            error_type=error_type,
        )
    )
    stage = reachable_stage(
        connection,
        edge_id,
        destination_edge_id,
        vehicle_type_id,
        simulation_time_s,
        arrival_position_m,
    )
    downstream_node = candidate_edge.getToNode()
    downstream_position_m = tuple(float(value) for value in downstream_node.getCoord())
    if stage is not None:
        heuristic_m = hypot(
            destination_position_m[0] - downstream_position_m[0],
            destination_position_m[1] - downstream_position_m[1],
        )
        reachable_suffix_m = max(float(stage.length) - length_m, 0.0)
        if heuristic_m > reachable_suffix_m + heuristic_tolerance_m:
            raise error_type(
                f"Euclidean heuristic exceeds reachable suffix for {edge_id}: "
                f"{heuristic_m} > {reachable_suffix_m}"
            )
    candidate = RoutingCandidateState(
        edge_id=edge_id,
        downstream_node_id=downstream_node.getID(),
        length_m=length_m,
        downstream_position_m=downstream_position_m,
        vehicles=tuple(observed_vehicles),
        is_legal=True,
        destination_reachable=stage is not None,
    )
    return candidate, stage


def commit_route(
    connection: Any,
    vehicle_id: str,
    current_edge_id: str,
    selected_edge_id: str,
    suffix_edges: Iterable[str],
    *,
    vehicle_label: str = "vehicle",
    error_type: ErrorType = TraCIAdapterError,
) -> tuple[str, ...]:
    """Apply and verify a current-edge-first route as one transaction boundary."""

    new_route = (current_edge_id, *tuple(suffix_edges))
    connection.vehicle.setRoute(vehicle_id, new_route)
    committed_route = tuple(connection.vehicle.getRoute(vehicle_id))
    route_index = int(connection.vehicle.getRouteIndex(vehicle_id))
    if route_index < 0 or committed_route[route_index] != current_edge_id:
        raise error_type(f"SUMO did not retain the {vehicle_label} on its current edge")
    committed_remaining_route = committed_route[route_index:]
    if committed_remaining_route != new_route:
        raise error_type(
            "SUMO remaining-route verification failed: "
            f"expected {new_route}, got {committed_remaining_route} "
            f"within full route {committed_route}"
        )
    if route_index + 1 >= len(committed_route):
        raise error_type("committed route has no next edge")
    if committed_route[route_index + 1] != selected_edge_id:
        raise error_type("committed route does not contain selected next edge")
    return committed_route
