"""Full 20-intersection SUMO/TraCI runner for the paper-grid baseline.

The policy equations stay in the pure ``control`` and ``routing`` packages.
This module owns only live-state sampling, per-intersection controller state,
transactional route mutation, safety checks, and reproducible run evidence.
"""

from __future__ import annotations

import json
import os
import platform
import random
import subprocess
import tomllib
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from importlib.metadata import version
from math import isclose
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree

import sumolib
import traci
from traci import constants as tc

from irbp_replica.control.execution import VTRCycleExecutor
from irbp_replica.control.vtr import build_cycle_plan
from irbp_replica.domain.models import PhaseState, VehicleRoutingState, VehicleState
from irbp_replica.routing.irbp import select_next_edge
from irbp_replica.simulation.traci_adapter import (
    candidate_snapshot,
    commit_route,
    controlled_link_indexes,
    outgoing_edges,
    queue_leader_kind,
    queue_vehicle_ids,
    reachable_stage,
    remaining_capacity_slots,
    restore_environment,
    road_snapshot,
    signal_state,
    subscribe_normal_lanes,
    sumo_installation,
    validate_server_version,
    vehicle_subscription_value,
    vehicles_on_edge,
)

EXPECTED_SUMO_VERSION = "1.27.1"
EXPECTED_TRACI_PROTOCOL = 22
VEHICLE_VARIABLES = (
    tc.VAR_ROAD_ID,
    tc.VAR_SPEED,
    tc.VAR_LANEPOSITION,
    tc.VAR_TYPE,
    tc.VAR_LANE_ID,
)
VEHICLE_KIND_BY_TYPE_ID = {
    "cav_14": "CAV",
    "hdv_9": "HDV",
    "hdv_10": "HDV",
    "hdv_11": "HDV",
    "hdv_12": "HDV",
}


class PaperGridRunError(RuntimeError):
    """Raised when a full-run invariant fails."""

    def __init__(
        self,
        message: str,
        *,
        diagnostics: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = dict(diagnostics or {})


@dataclass(frozen=True, slots=True)
class PaperGridConfig:
    seed: int
    step_length_s: float
    drain_timeout_s: float
    departure_horizon_s: float
    cycle_length_s: float
    extension_increment_s: float
    duration_resolution_s: float
    clearance_time_s: float
    capacity_slot_length_m: float
    queue_speed_threshold_mps: float
    initial_eta_m: float
    decision_trigger_distance_m: float
    empty_road_speed_mps: float
    speed_floor_mps: float
    position_absolute_tolerance_m: float
    cost_absolute_tolerance_m: float
    pressure_absolute_tolerance_mps: float
    relative_tolerance: float
    hdv_alternative_probability: float
    hdv_alternative_seed: int
    loading_interval_s: float

    @property
    def hard_deadline_s(self) -> float:
        return self.departure_horizon_s + self.drain_timeout_s


@dataclass(frozen=True, slots=True)
class VehicleSpec:
    vehicle_id: str
    type_id: str
    kind: str
    depart_s: float
    origin_edge_id: str
    destination_edge_id: str


@dataclass(slots=True)
class TripRuntime:
    spec: VehicleSpec
    destination_position_m: tuple[float, float]
    destination_arrival_position_m: float
    eta_remaining_m: float
    current_external_edge_id: str | None = None
    distance_at_current_edge_start_m: float = 0.0
    edge_visit_index: int = 0
    last_decided_visit_index: int = -1
    eligible_encounter_count: int = 0
    decision_count: int = 0
    eta_nonincrease_violations: int = 0

    def observe_external_edge(self, edge_id: str, previous_edge_length_m: float | None) -> bool:
        """Record a new external-edge encounter and its completed distance."""

        if edge_id == self.current_external_edge_id:
            return False
        if self.current_external_edge_id is not None:
            if previous_edge_length_m is None:
                raise ValueError("previous_edge_length_m is required after the origin edge")
            self.distance_at_current_edge_start_m += previous_edge_length_m
        self.current_external_edge_id = edge_id
        self.edge_visit_index += 1
        return True

    @property
    def decision_due(self) -> bool:
        return self.edge_visit_index != self.last_decided_visit_index

    def mark_decided(self) -> None:
        if not self.decision_due:
            raise RuntimeError("vehicle encounter was already decided")
        self.last_decided_visit_index = self.edge_visit_index
        self.decision_count += 1


@dataclass(frozen=True, slots=True)
class HDVSelection:
    shortest_edge_id: str
    shortest_edge_ids: tuple[str, ...]
    alternative_edge_ids: tuple[str, ...]
    random_draw: float | None
    selected_edge_id: str
    chose_alternative: bool


@dataclass(frozen=True, slots=True)
class HDVDecisionTrace:
    time_s: float
    vehicle_id: str
    encounter_index: int
    source_edge_id: str
    destination_edge_id: str
    candidate_lengths_m: tuple[tuple[str, float], ...]
    shortest_edge_ids: tuple[str, ...]
    alternative_edge_ids: tuple[str, ...]
    random_draw: float | None
    selected_edge_id: str
    chose_alternative: bool
    route_before: tuple[str, ...]
    route_after: tuple[str, ...]


@dataclass(slots=True)
class IntersectionRuntime:
    tls_id: str
    base_phases: tuple[PhaseState, ...]
    link_indexes: dict[str, tuple[int, ...]]
    state_length: int
    last_station_id: str
    executor: VTRCycleExecutor | None = None
    cycle_count: int = 0
    completed_cycle_count: int = 0
    active_steps: int = 0
    idle_steps: int = 0
    extension_count: int = 0
    boundary_counts: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True, slots=True)
class PaperGridRunResult:
    environment: dict[str, Any]
    source_commit: str
    source_dirty: bool | None
    source_hashes: dict[str, str]
    resolved_config: dict[str, Any]
    input_hashes: dict[str, str]
    topology: dict[str, int]
    termination: dict[str, Any]
    vehicle_counts: dict[str, int]
    id_digests: dict[str, str]
    observed_departure_bins: tuple[dict[str, int], ...]
    delayed_departures_after_horizon: int
    controllers: tuple[dict[str, Any], ...]
    cav_routing: dict[str, Any]
    hdv_routing: dict[str, Any]
    hdv_decisions: tuple[HDVDecisionTrace, ...]
    safety: dict[str, tuple[str, ...]]
    event_digest: str

    def normalized_payload(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def normalized_digest(self) -> str:
        encoded = json.dumps(
            self.normalized_payload(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        payload = self.normalized_payload()
        payload["normalized_digest"] = self.normalized_digest
        return payload


class _EventDigest:
    def __init__(self) -> None:
        self._hash = sha256()

    def add(self, event: str, **payload: Any) -> None:
        record = {"event": event, **payload}
        encoded = json.dumps(
            record,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        self._hash.update(encoded)
        self._hash.update(b"\n")

    @property
    def hexdigest(self) -> str:
        return self._hash.hexdigest()


def default_project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PaperGridRunError(f"cannot load baseline config: {path}") from exc


def load_paper_grid_config(project_root: str | Path | None = None) -> PaperGridConfig:
    """Load and validate every runtime reconstruction parameter."""

    root = Path(project_root).resolve() if project_root is not None else default_project_root()
    raw = _load_toml(root / "experiments" / "configs" / "paper_baseline.toml")
    try:
        simulation = raw["simulation"]
        demand = raw["demand"]
        demand_reconstruction = demand["reconstruction"]
        routing = raw["routing"]
        control = raw["control"]
        hdv = raw["vehicles"]["hdv"]
        config = PaperGridConfig(
            seed=int(simulation["random_seed"]),
            step_length_s=float(simulation["step_length_s"]),
            drain_timeout_s=float(simulation["drain_timeout_s"]),
            departure_horizon_s=float(demand_reconstruction["departure_horizon_s"]),
            cycle_length_s=float(control["cycle_length_s"]),
            extension_increment_s=float(control["hdv_extension_increment_s"]),
            duration_resolution_s=float(control["duration_resolution_s"]),
            clearance_time_s=float(control["clearance_time_s"]),
            capacity_slot_length_m=float(control["capacity_slot_length_m"]),
            queue_speed_threshold_mps=float(control["queue_speed_threshold_mps"]),
            initial_eta_m=float(routing["initial_eta_m"]),
            decision_trigger_distance_m=float(routing["decision_trigger_distance_m"]),
            empty_road_speed_mps=float(routing["empty_road_speed_mps"]),
            speed_floor_mps=float(routing["speed_floor_mps"]),
            position_absolute_tolerance_m=float(routing["position_absolute_tolerance_m"]),
            cost_absolute_tolerance_m=float(routing["cost_absolute_tolerance_m"]),
            pressure_absolute_tolerance_mps=float(routing["pressure_absolute_tolerance_mps"]),
            relative_tolerance=float(routing["relative_tolerance"]),
            hdv_alternative_probability=float(hdv["alternative_route_probability"]),
            hdv_alternative_seed=int(hdv["alternative_route_random_seed"]),
            loading_interval_s=float(demand["loading_interval_s"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PaperGridRunError(f"invalid baseline runtime config: {exc}") from exc

    positive = {
        "step_length_s": config.step_length_s,
        "drain_timeout_s": config.drain_timeout_s,
        "departure_horizon_s": config.departure_horizon_s,
        "cycle_length_s": config.cycle_length_s,
        "extension_increment_s": config.extension_increment_s,
        "duration_resolution_s": config.duration_resolution_s,
        "capacity_slot_length_m": config.capacity_slot_length_m,
        "decision_trigger_distance_m": config.decision_trigger_distance_m,
        "empty_road_speed_mps": config.empty_road_speed_mps,
        "speed_floor_mps": config.speed_floor_mps,
        "loading_interval_s": config.loading_interval_s,
    }
    if any(value <= 0 for value in positive.values()):
        raise PaperGridRunError(f"runtime config values must be positive: {positive}")
    if config.clearance_time_s < 0 or config.queue_speed_threshold_mps < 0:
        raise PaperGridRunError("clearance and queue threshold must be non-negative")
    if not 0 <= config.hdv_alternative_probability <= 1:
        raise PaperGridRunError("HDV alternative probability must be in [0, 1]")
    if not isclose(
        config.duration_resolution_s,
        config.step_length_s,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise PaperGridRunError("duration resolution must equal simulation step length")
    return config


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PaperGridRunError(f"cannot load JSON artifact: {path}") from exc


def _read_vehicle_specs(route_path: Path) -> dict[str, VehicleSpec]:
    root = ElementTree.parse(route_path).getroot()
    specs: dict[str, VehicleSpec] = {}
    for element in root.findall("vehicle"):
        vehicle_id = element.attrib["id"]
        type_id = element.attrib["type"]
        try:
            kind = VEHICLE_KIND_BY_TYPE_ID[type_id]
        except KeyError as exc:
            raise PaperGridRunError(f"unknown demand vehicle type: {type_id}") from exc
        route = element.find("route")
        if route is None:
            raise PaperGridRunError(f"vehicle has no inline route: {vehicle_id}")
        edges = tuple(route.attrib.get("edges", "").split())
        if not edges:
            raise PaperGridRunError(f"vehicle has an empty route: {vehicle_id}")
        specs[vehicle_id] = VehicleSpec(
            vehicle_id=vehicle_id,
            type_id=type_id,
            kind=kind,
            depart_s=float(element.attrib["depart"]),
            origin_edge_id=edges[0],
            destination_edge_id=edges[-1],
        )
    if len(specs) != len(root.findall("vehicle")):
        raise PaperGridRunError("demand vehicle IDs must be unique")
    return specs


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _id_digest(vehicle_ids: set[str]) -> str:
    return sha256("\n".join(sorted(vehicle_ids)).encode("utf-8")).hexdigest()


def _source_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    return result.stdout.strip() or "unavailable"


def _source_dirty(root: Path) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(result.stdout.strip())


def select_hdv_edge(
    candidate_lengths_m: Mapping[str, float],
    *,
    probability: float,
    random_source: random.Random,
    distance_tolerance_m: float = 1e-9,
) -> HDVSelection:
    """Apply the documented seeded reconstruction of the unpublished 20% rule."""

    if not candidate_lengths_m:
        raise ValueError("candidate_lengths_m must not be empty")
    if not 0 <= probability <= 1:
        raise ValueError("probability must be in [0, 1]")
    if distance_tolerance_m < 0:
        raise ValueError("distance_tolerance_m must be non-negative")
    ordered = tuple(
        sorted((edge_id, float(length)) for edge_id, length in candidate_lengths_m.items())
    )
    if any(not edge_id or length < 0 for edge_id, length in ordered):
        raise ValueError("candidate edge IDs and lengths must be valid")
    minimum = min(length for _, length in ordered)
    shortest = tuple(
        edge_id for edge_id, length in ordered if length <= minimum + distance_tolerance_m
    )
    alternatives = tuple(edge_id for edge_id, _ in ordered if edge_id not in shortest)
    fallback = min(shortest)
    if not alternatives:
        return HDVSelection(
            shortest_edge_id=fallback,
            shortest_edge_ids=shortest,
            alternative_edge_ids=(),
            random_draw=None,
            selected_edge_id=fallback,
            chose_alternative=False,
        )

    draw = random_source.random()
    chose_alternative = draw < probability
    selected = fallback
    if chose_alternative:
        selected = alternatives[random_source.randrange(len(alternatives))]
    return HDVSelection(
        shortest_edge_id=fallback,
        shortest_edge_ids=shortest,
        alternative_edge_ids=alternatives,
        random_draw=draw,
        selected_edge_id=selected,
        chose_alternative=chose_alternative,
    )


def _normal_outgoing_edges(network: Any, current_edge_id: str) -> tuple[Any, ...]:
    current = network.getEdge(current_edge_id)
    reverse_destination = current.getFromNode().getID()
    return tuple(
        edge
        for edge in outgoing_edges(network, current_edge_id)
        if edge.getToNode().getID() != reverse_destination
    )


def _phase_snapshot(
    connection: Any,
    network: Any,
    runtime: IntersectionRuntime,
    config: PaperGridConfig,
) -> tuple[PhaseState, ...]:
    return tuple(
        PhaseState(
            phase_id=phase.phase_id,
            station_id=phase.station_id,
            upstream_edge_id=phase.upstream_edge_id,
            downstream_edge_ids=phase.downstream_edge_ids,
            clockwise_index=phase.clockwise_index,
            head_vehicle_kind=queue_leader_kind(
                connection,
                network,
                phase.upstream_edge_id,
                VEHICLE_KIND_BY_TYPE_ID,
                config.queue_speed_threshold_mps,
                error_type=PaperGridRunError,
            ),
        )
        for phase in runtime.base_phases
    )


def _discover_intersections(
    connection: Any,
    network: Any,
    metadata: dict[str, Any],
) -> dict[str, IntersectionRuntime]:
    counts = metadata.get("counts", {})
    if counts != {
        "connections": 102,
        "controlled_links": 102,
        "edges": 54,
        "nodes": 20,
        "phases": 54,
        "tls": 20,
    }:
        raise PaperGridRunError(f"paper-grid metadata counts changed: {counts}")
    tls_metadata = metadata.get("tls")
    if not isinstance(tls_metadata, dict):
        raise PaperGridRunError("paper-grid metadata has no TLS map")
    runtime_tls_ids = tuple(sorted(connection.trafficlight.getIDList()))
    if runtime_tls_ids != tuple(sorted(tls_metadata)):
        raise PaperGridRunError(f"runtime TLS IDs disagree with metadata: {runtime_tls_ids}")

    runtimes: dict[str, IntersectionRuntime] = {}
    phase_total = 0
    controlled_link_total = 0
    for tls_id in runtime_tls_ids:
        entries = tuple(tls_metadata[tls_id])
        entries = tuple(sorted(entries, key=lambda entry: int(entry["phase_index"])))
        required_incoming = tuple(str(entry["incoming_edge"]) for entry in entries)
        indexes, state_length = controlled_link_indexes(
            connection,
            tls_id,
            required_incoming,
            error_type=PaperGridRunError,
        )
        expected_indexes = {
            str(entry["incoming_edge"]): tuple(int(value) for value in entry["link_indices"])
            for entry in entries
        }
        if indexes != expected_indexes:
            raise PaperGridRunError(
                f"runtime controlled links disagree with metadata for {tls_id}: "
                f"expected {expected_indexes}, got {indexes}"
            )

        phases: list[PhaseState] = []
        for clockwise_index, entry in enumerate(entries):
            incoming_edge_id = str(entry["incoming_edge"])
            downstream_edge_ids = tuple(
                edge.getID() for edge in _normal_outgoing_edges(network, incoming_edge_id)
            )
            if not downstream_edge_ids:
                raise PaperGridRunError(
                    f"phase has no legal downstream roads: {tls_id}/{incoming_edge_id}"
                )
            phases.append(
                PhaseState(
                    phase_id=f"{tls_id}:{entry['name']}",
                    station_id=f"{tls_id}:{incoming_edge_id}",
                    upstream_edge_id=incoming_edge_id,
                    downstream_edge_ids=downstream_edge_ids,
                    clockwise_index=clockwise_index,
                )
            )
        runtime = IntersectionRuntime(
            tls_id=tls_id,
            base_phases=tuple(phases),
            link_indexes=indexes,
            state_length=state_length,
            last_station_id=phases[-1].station_id,
        )
        runtimes[tls_id] = runtime
        phase_total += len(phases)
        controlled_link_total += state_length

    if (len(runtimes), phase_total, controlled_link_total) != (20, 54, 102):
        raise PaperGridRunError(
            "runtime topology must contain 20 TLS, 54 phases, and 102 controlled links"
        )
    return runtimes


def _build_executor(
    connection: Any,
    network: Any,
    runtime: IntersectionRuntime,
    config: PaperGridConfig,
    simulation_time_s: float,
    event_digest: _EventDigest,
) -> None:
    phases = _phase_snapshot(connection, network, runtime, config)
    roads = road_snapshot(
        connection,
        network,
        phases,
        vehicle_slot_m=config.capacity_slot_length_m,
        queue_speed_threshold_mps=config.queue_speed_threshold_mps,
        error_type=PaperGridRunError,
    )
    plan = build_cycle_plan(
        phases,
        roads,
        last_station_id=runtime.last_station_id,
        cycle_length_s=config.cycle_length_s,
        resolution_s=config.duration_resolution_s,
    )
    if not plan:
        runtime.executor = None
        return
    runtime.executor = VTRCycleExecutor(
        plan,
        previous_station_id=runtime.last_station_id,
        step_length_s=config.step_length_s,
        extension_increment_s=config.extension_increment_s,
        maximum_extension_s=None,
        clearance_time_s=config.clearance_time_s,
    )
    runtime.cycle_count += 1
    event_digest.add(
        "cycle_start",
        time_s=round(simulation_time_s, 6),
        tls_id=runtime.tls_id,
        cycle_index=runtime.cycle_count,
        stations=[slot.station_id for slot in plan],
        durations_s=[round(slot.initial_duration_s, 6) for slot in plan],
        weights=[round(slot.weight, 12) for slot in plan],
    )


def _destination_geometry(
    network: Any, destination_edge_id: str
) -> tuple[float, tuple[float, float]]:
    edge = network.getEdge(destination_edge_id)
    lanes = tuple(edge.getLanes())
    if not lanes:
        raise PaperGridRunError(f"destination edge has no lanes: {destination_edge_id}")
    arrival_position_m = max(float(lane.getLength()) for lane in lanes)
    destination_node = edge.getToNode()
    return arrival_position_m, tuple(float(value) for value in destination_node.getCoord())


def _lane_remaining_m(connection: Any, network: Any, vehicle_id: str) -> float:
    lane_id = str(
        vehicle_subscription_value(
            connection,
            vehicle_id,
            tc.VAR_LANE_ID,
            error_type=PaperGridRunError,
        )
    )
    return max(
        float(network.getLane(lane_id).getLength())
        - float(
            vehicle_subscription_value(
                connection,
                vehicle_id,
                tc.VAR_LANEPOSITION,
                error_type=PaperGridRunError,
            )
        ),
        0.0,
    )


def _observe_trip_edge(
    connection: Any,
    network: Any,
    trip: TripRuntime,
) -> tuple[str | None, bool]:
    edge_id = str(
        vehicle_subscription_value(
            connection,
            trip.spec.vehicle_id,
            tc.VAR_ROAD_ID,
            error_type=PaperGridRunError,
        )
    )
    if not edge_id or edge_id.startswith(":"):
        return None, False
    previous_length = None
    if trip.current_external_edge_id is not None and edge_id != trip.current_external_edge_id:
        previous_length = float(network.getEdge(trip.current_external_edge_id).getLength())
    changed = trip.observe_external_edge(edge_id, previous_length)
    if changed and edge_id != trip.spec.destination_edge_id:
        trip.eligible_encounter_count += 1
    return edge_id, changed


def _route_cav(
    connection: Any,
    network: Any,
    trip: TripRuntime,
    config: PaperGridConfig,
    simulation_time_s: float,
    event_digest: _EventDigest,
) -> bool:
    vehicle_id = trip.spec.vehicle_id
    current_edge_id, _ = _observe_trip_edge(connection, network, trip)
    if current_edge_id is None or current_edge_id == trip.spec.destination_edge_id:
        return False
    if not trip.decision_due:
        return False
    remaining_m = _lane_remaining_m(connection, network, vehicle_id)
    if remaining_m > config.decision_trigger_distance_m + 1e-9:
        return False

    current_edge = network.getEdge(current_edge_id)
    candidates_edges = _normal_outgoing_edges(network, current_edge_id)
    if not candidates_edges:
        raise PaperGridRunError(f"CAV has no legal candidates from {current_edge_id}")
    speed_mps = max(
        float(
            vehicle_subscription_value(
                connection,
                vehicle_id,
                tc.VAR_SPEED,
                error_type=PaperGridRunError,
            )
        ),
        0.0,
    )
    cav = VehicleState(
        vehicle_id=vehicle_id,
        vehicle_kind="CAV",
        edge_id=current_edge_id,
        speed_mps=speed_mps,
        remaining_distance_m=remaining_m,
        destination_edge_id=trip.spec.destination_edge_id,
    )
    routing_state = VehicleRoutingState(
        vehicle_id=vehicle_id,
        origin_edge_id=trip.spec.origin_edge_id,
        destination_edge_id=trip.spec.destination_edge_id,
        distance_travelled_m=(
            trip.distance_at_current_edge_start_m + float(current_edge.getLength())
        ),
        eta_remaining_m=trip.eta_remaining_m,
        destination_position_m=trip.destination_position_m,
    )

    candidates = []
    stages: dict[str, Any] = {}
    for edge in candidates_edges:
        candidate, stage = candidate_snapshot(
            connection,
            network,
            vehicle_id,
            edge,
            simulation_time_s,
            trip.spec.destination_edge_id,
            trip.destination_arrival_position_m,
            trip.destination_position_m,
            VEHICLE_KIND_BY_TYPE_ID,
            heuristic_tolerance_m=config.position_absolute_tolerance_m,
            error_type=PaperGridRunError,
        )
        candidates.append(candidate)
        if stage is not None:
            stages[candidate.edge_id] = stage

    decision = select_next_edge(
        cav,
        routing_state,
        candidates,
        empty_road_speed_mps=config.empty_road_speed_mps,
        speed_floor_mps=config.speed_floor_mps,
        position_absolute_tolerance_m=config.position_absolute_tolerance_m,
        cost_absolute_tolerance_m=config.cost_absolute_tolerance_m,
        pressure_absolute_tolerance_mps=config.pressure_absolute_tolerance_mps,
        relative_tolerance=config.relative_tolerance,
    )
    selected_stage = stages.get(decision.selected_edge_id)
    if selected_stage is None:
        raise PaperGridRunError(
            f"CAV selected an unreachable road: {vehicle_id}/{decision.selected_edge_id}"
        )
    route_before = tuple(connection.vehicle.getRoute(vehicle_id))
    committed = commit_route(
        connection,
        vehicle_id,
        current_edge_id,
        decision.selected_edge_id,
        tuple(selected_stage.edges),
        error_type=PaperGridRunError,
    )
    if decision.updated_eta_m > trip.eta_remaining_m + 1e-9:
        trip.eta_nonincrease_violations += 1
        raise PaperGridRunError(f"CAV eta increased: {vehicle_id}")
    eta_before = trip.eta_remaining_m
    trip.eta_remaining_m = decision.updated_eta_m
    trip.mark_decided()
    event_digest.add(
        "cav_decision",
        time_s=round(simulation_time_s, 6),
        vehicle_id=vehicle_id,
        encounter_index=trip.edge_visit_index,
        source_edge_id=current_edge_id,
        selected_edge_id=decision.selected_edge_id,
        eta_before_m=round(eta_before, 6),
        eta_after_m=round(trip.eta_remaining_m, 6),
        route_before=list(route_before),
        route_after=list(committed),
        scores=[
            {
                "edge_id": score.edge_id,
                "status": score.status,
                "controlling_vehicle_id": score.controlling_vehicle_id,
                "travel_time_s": (
                    None if score.travel_time_s is None else round(score.travel_time_s, 6)
                ),
                "pressure_weight_mps": (
                    None
                    if score.pressure_weight_mps is None
                    else round(score.pressure_weight_mps, 12)
                ),
                "distance_cost_m": (
                    None if score.distance_cost_m is None else round(score.distance_cost_m, 6)
                ),
                "detour_excess_m": (
                    None if score.detour_excess_m is None else round(score.detour_excess_m, 6)
                ),
            }
            for score in decision.scores
        ],
    )
    return True


def _route_hdv(
    connection: Any,
    network: Any,
    trip: TripRuntime,
    config: PaperGridConfig,
    simulation_time_s: float,
    random_source: random.Random,
    event_digest: _EventDigest,
) -> HDVDecisionTrace | None:
    vehicle_id = trip.spec.vehicle_id
    current_edge_id, _ = _observe_trip_edge(connection, network, trip)
    if current_edge_id is None or current_edge_id == trip.spec.destination_edge_id:
        return None
    if not trip.decision_due:
        return None
    if (
        _lane_remaining_m(connection, network, vehicle_id)
        > config.decision_trigger_distance_m + 1e-9
    ):
        return None

    vehicle_type_id = str(
        vehicle_subscription_value(
            connection,
            vehicle_id,
            tc.VAR_TYPE,
            error_type=PaperGridRunError,
        )
    )
    stages: dict[str, Any] = {}
    lengths: dict[str, float] = {}
    for edge in _normal_outgoing_edges(network, current_edge_id):
        stage = reachable_stage(
            connection,
            edge.getID(),
            trip.spec.destination_edge_id,
            vehicle_type_id,
            simulation_time_s,
            trip.destination_arrival_position_m,
        )
        if stage is not None:
            stages[edge.getID()] = stage
            lengths[edge.getID()] = float(stage.length)
    if not stages:
        raise PaperGridRunError(f"HDV has no destination-reachable road: {vehicle_id}")

    selection = select_hdv_edge(
        lengths,
        probability=config.hdv_alternative_probability,
        random_source=random_source,
        distance_tolerance_m=config.cost_absolute_tolerance_m,
    )
    route_before = tuple(connection.vehicle.getRoute(vehicle_id))
    selected_stage = stages[selection.selected_edge_id]
    committed = commit_route(
        connection,
        vehicle_id,
        current_edge_id,
        selection.selected_edge_id,
        tuple(selected_stage.edges),
        error_type=PaperGridRunError,
    )
    trip.mark_decided()
    trace = HDVDecisionTrace(
        time_s=round(simulation_time_s, 6),
        vehicle_id=vehicle_id,
        encounter_index=trip.edge_visit_index,
        source_edge_id=current_edge_id,
        destination_edge_id=trip.spec.destination_edge_id,
        candidate_lengths_m=tuple(
            (edge_id, round(length, 6)) for edge_id, length in sorted(lengths.items())
        ),
        shortest_edge_ids=selection.shortest_edge_ids,
        alternative_edge_ids=selection.alternative_edge_ids,
        random_draw=(None if selection.random_draw is None else round(selection.random_draw, 15)),
        selected_edge_id=selection.selected_edge_id,
        chose_alternative=selection.chose_alternative,
        route_before=route_before,
        route_after=committed,
    )
    event_digest.add("hdv_decision", **asdict(trace))
    return trace


def _command_intersections(
    connection: Any,
    network: Any,
    runtimes: Mapping[str, IntersectionRuntime],
    config: PaperGridConfig,
    simulation_time_s: float,
    event_digest: _EventDigest,
) -> dict[str, tuple[tuple[PhaseState, ...], str | None]]:
    commanded: dict[str, tuple[tuple[PhaseState, ...], str | None]] = {}
    for tls_id in sorted(runtimes):
        runtime = runtimes[tls_id]
        if runtime.executor is None:
            _build_executor(
                connection,
                network,
                runtime,
                config,
                simulation_time_s,
                event_digest,
            )
        phases = runtime.base_phases
        snapshot = runtime.executor.snapshot() if runtime.executor is not None else None
        active_phase_id = (
            snapshot.active_phase_id if snapshot is not None and snapshot.mode == "ACTIVE" else None
        )
        state = signal_state(
            active_phase_id,
            phases,
            runtime.link_indexes,
            runtime.state_length,
            error_type=PaperGridRunError,
        )
        active_green_count = 0
        if active_phase_id is not None:
            active_phase = next(phase for phase in phases if phase.phase_id == active_phase_id)
            active_green_count = len(runtime.link_indexes[active_phase.upstream_edge_id])
        if state.count("G") != active_green_count or set(state) - {"r", "G"}:
            raise PaperGridRunError(f"unsafe signal command for {tls_id}: {state}")
        connection.trafficlight.setRedYellowGreenState(tls_id, state)
        if connection.trafficlight.getRedYellowGreenState(tls_id) != state:
            raise PaperGridRunError(f"SUMO rejected signal command for {tls_id}")
        if active_phase_id is None:
            runtime.idle_steps += 1
        else:
            runtime.active_steps += 1
        commanded[tls_id] = (phases, active_phase_id)
    if len(commanded) != 20:
        raise PaperGridRunError("every global tick must command all 20 intersections")
    return commanded


def _advance_intersections(
    connection: Any,
    network: Any,
    runtimes: Mapping[str, IntersectionRuntime],
    commanded: Mapping[str, tuple[tuple[PhaseState, ...], str | None]],
    config: PaperGridConfig,
    simulation_time_s: float,
    event_digest: _EventDigest,
) -> None:
    for tls_id in sorted(runtimes):
        runtime = runtimes[tls_id]
        executor = runtime.executor
        if executor is None:
            continue
        phases, active_phase_id = commanded[tls_id]
        leader_kind = None
        if active_phase_id is not None:
            active_phase = next(phase for phase in phases if phase.phase_id == active_phase_id)
            leader_kind = queue_leader_kind(
                connection,
                network,
                active_phase.upstream_edge_id,
                VEHICLE_KIND_BY_TYPE_ID,
                config.queue_speed_threshold_mps,
                error_type=PaperGridRunError,
            )
        snapshot = executor.advance_after_step(post_step_queue_leader=leader_kind)
        if snapshot.boundary_outcome is not None:
            runtime.boundary_counts[snapshot.boundary_outcome] += 1
            if snapshot.boundary_outcome == "extended":
                runtime.extension_count += 1
            event_digest.add(
                "controller_boundary",
                time_s=round(simulation_time_s, 6),
                tls_id=tls_id,
                cycle_index=runtime.cycle_count,
                phase_id=snapshot.boundary_phase_id,
                station_id=snapshot.boundary_station_id,
                outcome=snapshot.boundary_outcome,
            )
        if executor.is_complete:
            runtime.last_station_id = executor.last_completed_station_id
            runtime.completed_cycle_count += 1
            event_digest.add(
                "cycle_complete",
                time_s=round(simulation_time_s, 6),
                tls_id=tls_id,
                cycle_index=runtime.cycle_count,
                duration_s=round(executor.actual_cycle_duration_s or 0.0, 6),
            )
            runtime.executor = None


def _required_assets(root: Path) -> dict[str, Path]:
    return {
        "baseline_config": root / "experiments" / "configs" / "paper_baseline.toml",
        "sumo_config": root / "sumo" / "config" / "paper_baseline.sumocfg",
        "network": root / "sumo" / "networks" / "paper_grid" / "paper_grid.net.xml",
        "network_metadata": (
            root / "sumo" / "networks" / "paper_grid" / "paper_grid.metadata.json"
        ),
        "demand": root / "sumo" / "demand" / "paper_baseline.rou.xml",
        "demand_metadata": root / "sumo" / "demand" / "paper_baseline.metadata.json",
    }


def _resolved_config_payload(config: PaperGridConfig) -> dict[str, Any]:
    payload = asdict(config)
    payload["hard_deadline_s"] = config.hard_deadline_s
    payload["hdv_extension_limit_mode"] = "unbounded"
    payload["hdv_alternative_candidate_rule"] = (
        "legal_destination_reachable_non_uturn_excluding_all_shortest_ties"
    )
    payload["hdv_alternative_draw_rule"] = "independent_uniform_per_eligible_encounter"
    payload["decision_trigger_basis"] = "unpublished_30m_reconstruction"
    payload["capacity_slot_basis"] = "unpublished_7.5m_reconstruction"
    return payload


def _observed_bins(
    config: PaperGridConfig,
    bin_counters: list[Counter[str]],
) -> tuple[dict[str, int], ...]:
    return tuple(
        {
            "index": index,
            "start_s": round(index * config.loading_interval_s),
            "end_s": round((index + 1) * config.loading_interval_s),
            "vehicles": counter["vehicles"],
            "cav": counter["CAV"],
            "hdv": counter["HDV"],
        }
        for index, counter in enumerate(bin_counters)
    )


def _controller_summaries(
    runtimes: Mapping[str, IntersectionRuntime],
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "tls_id": tls_id,
            "phase_count": len(runtime.base_phases),
            "controlled_link_count": runtime.state_length,
            "cycles_started": runtime.cycle_count,
            "cycles_completed": runtime.completed_cycle_count,
            "active_steps": runtime.active_steps,
            "idle_steps": runtime.idle_steps,
            "extensions": runtime.extension_count,
            "boundary_counts": dict(sorted(runtime.boundary_counts.items())),
            "last_station_id": runtime.last_station_id,
        }
        for tls_id, runtime in sorted(runtimes.items())
    )


def _validate_complete_run(
    specs: Mapping[str, VehicleSpec],
    trips: Mapping[str, TripRuntime],
    departed_ids: set[str],
    arrived_ids: set[str],
    minimum_expected_remaining: int,
    incomplete_diagnostics: Mapping[str, Any],
    limit_reason: str,
) -> None:
    expected_ids = set(specs)
    if minimum_expected_remaining != 0:
        raise PaperGridRunError(
            "possible deadlock/incomplete: "
            f"{limit_reason} reached with minExpected={minimum_expected_remaining}",
            diagnostics=incomplete_diagnostics,
        )
    for label, observed in (("departed", departed_ids), ("arrived", arrived_ids)):
        missing = sorted(expected_ids - observed)
        unexpected = sorted(observed - expected_ids)
        if missing or unexpected:
            raise PaperGridRunError(
                f"{label} ID set mismatch; missing={missing[:20]}, unexpected={unexpected[:20]}"
            )
    incomplete_decisions = sorted(
        trip.spec.vehicle_id
        for trip in trips.values()
        if trip.decision_count != trip.eligible_encounter_count
    )
    if incomplete_decisions:
        raise PaperGridRunError(
            "intersection encounters without exactly one routing decision: "
            f"{incomplete_decisions[:20]}"
        )


def _incomplete_diagnostics(
    connection: Any,
    network: Any,
    runtimes: Mapping[str, IntersectionRuntime],
    config: PaperGridConfig,
    *,
    departed_count: int,
    arrived_count: int,
    last_arrival_time_s: float | None,
) -> dict[str, Any]:
    occupied_edges: list[dict[str, Any]] = []
    for edge in sorted(network.getEdges(withInternal=False), key=lambda item: item.getID()):
        edge_id = edge.getID()
        vehicle_ids = vehicles_on_edge(
            connection,
            network,
            edge_id,
            error_type=PaperGridRunError,
        )
        if not vehicle_ids:
            continue
        queued_ids = queue_vehicle_ids(
            connection,
            network,
            edge_id,
            config.queue_speed_threshold_mps,
            error_type=PaperGridRunError,
        )
        occupied_edges.append(
            {
                "edge_id": edge_id,
                "vehicles": len(vehicle_ids),
                "queued": len(queued_ids),
                "remaining_slots": remaining_capacity_slots(
                    connection,
                    network,
                    edge_id,
                    config.capacity_slot_length_m,
                    error_type=PaperGridRunError,
                ),
            }
        )
    return {
        "simulation_time_s": round(float(connection.simulation.getTime()), 6),
        "active_vehicles": len(connection.vehicle.getIDList()),
        "departed": departed_count,
        "arrived": arrived_count,
        "last_arrival_time_s": last_arrival_time_s,
        "occupied_edges": occupied_edges,
        "controllers": _controller_summaries(runtimes),
    }


def run_paper_grid(
    project_root: str | Path | None = None,
    *,
    max_steps: int | None = None,
) -> PaperGridRunResult:
    """Run seed-1 baseline until all 4,000 vehicles drain or the hard deadline fails."""

    if max_steps is not None and (not isinstance(max_steps, int) or max_steps <= 0):
        raise ValueError("max_steps must be a positive integer or None")
    root = Path(project_root).resolve() if project_root is not None else default_project_root()
    assets = _required_assets(root)
    for path in assets.values():
        if not path.is_file():
            raise PaperGridRunError(f"required paper-grid asset not found: {path}")
    config = load_paper_grid_config(root)
    metadata = _load_json(assets["network_metadata"])
    demand_metadata = _load_json(assets["demand_metadata"])
    specs = _read_vehicle_specs(assets["demand"])
    expected_ids = set(specs)
    expected_kind_counts = Counter(spec.kind for spec in specs.values())
    demand_counts = demand_metadata.get("counts", {})
    if (
        len(specs) != 4000
        or expected_kind_counts != Counter({"CAV": 3600, "HDV": 400})
        or demand_counts.get("vehicles") != 4000
        or demand_counts.get("cav") != 3600
        or demand_counts.get("hdv") != 400
    ):
        raise PaperGridRunError(
            f"baseline demand must be 4,000 vehicles (3,600 CAV/400 HDV): {demand_counts}"
        )
    if max(spec.depart_s for spec in specs.values()) >= config.departure_horizon_s:
        raise PaperGridRunError("scheduled departure lies outside the configured horizon")

    configured_steps = round(config.hard_deadline_s / config.step_length_s)
    hard_step_cap = configured_steps if max_steps is None else min(configured_steps, max_steps)
    limit_reason = (
        "configured hard deadline" if hard_step_cap == configured_steps else "diagnostic step cap"
    )
    if hard_step_cap * config.step_length_s > config.hard_deadline_s + 1e-9:
        raise PaperGridRunError("step cap exceeds configured hard deadline")

    sumo_home, sumo_binary = sumo_installation(
        EXPECTED_SUMO_VERSION,
        error_type=PaperGridRunError,
    )
    network = sumolib.net.readNet(str(assets["network"]), withInternal=True)
    input_hashes = {
        str(path.relative_to(root)).replace("\\", "/"): _sha256_file(path)
        for path in assets.values()
    }
    source_paths = (
        root / "src" / "irbp_replica" / "simulation" / "paper_grid_runner.py",
        root / "src" / "irbp_replica" / "simulation" / "traci_adapter.py",
        root / "src" / "irbp_replica" / "control" / "vtr.py",
        root / "src" / "irbp_replica" / "control" / "execution.py",
        root / "src" / "irbp_replica" / "control" / "pressure.py",
        root / "src" / "irbp_replica" / "control" / "phase_time.py",
        root / "src" / "irbp_replica" / "routing" / "irbp.py",
        root / "src" / "irbp_replica" / "routing" / "distance.py",
        root / "src" / "irbp_replica" / "routing" / "travel_time.py",
        root / "src" / "irbp_replica" / "domain" / "models.py",
    )
    source_hashes = {
        str(path.relative_to(root)).replace("\\", "/"): _sha256_file(path) for path in source_paths
    }
    event_digest = _EventDigest()
    random_source = random.Random(config.hdv_alternative_seed)

    departed_ids: set[str] = set()
    arrived_ids: set[str] = set()
    starting_teleport_ids: set[str] = set()
    ending_teleport_ids: set[str] = set()
    colliding_ids: set[str] = set()
    trips: dict[str, TripRuntime] = {}
    hdv_decisions: list[HDVDecisionTrace] = []
    bin_count = round(config.departure_horizon_s / config.loading_interval_s)
    bin_counters = [Counter() for _ in range(bin_count)]
    delayed_departures = 0
    first_departure_time_s: float | None = None
    last_departure_time_s: float | None = None
    last_arrival_time_s: float | None = None
    cav_route_update_count = 0
    steps = 0
    minimum_expected_remaining = len(expected_ids)
    runtimes: dict[str, IntersectionRuntime] = {}
    protocol = -1
    server_version = ""
    end_time_s = 0.0
    incomplete_diagnostics: dict[str, Any] = {}
    label = f"irbp-paper-grid-{uuid4().hex}"
    connection = None

    with TemporaryDirectory(prefix="irbp-paper-grid-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        command = [
            str(sumo_binary),
            "-c",
            str(assets["sumo_config"]),
            "--seed",
            str(config.seed),
            "--step-length",
            str(config.step_length_s),
            "--threads",
            "1",
            "--end",
            str(hard_step_cap * config.step_length_s),
            "--no-step-log",
            "true",
            "--duration-log.disable",
            "true",
            "--no-warnings",
            "true",
            "--tripinfo-output",
            str(temporary_path / "tripinfo.xml"),
            "--vehroute-output",
            str(temporary_path / "vehroute.xml"),
        ]
        old_sumo_home = os.environ.get("SUMO_HOME")
        old_path = os.environ.get("PATH")
        os.environ["SUMO_HOME"] = str(sumo_home)
        os.environ["PATH"] = str(sumo_home / "bin") + os.pathsep + (old_path or "")
        try:
            traci.start(
                command,
                label=label,
                doSwitch=True,
                stdout=subprocess.DEVNULL,
            )
            connection = traci.getConnection(label)
        finally:
            restore_environment("SUMO_HOME", old_sumo_home)
            restore_environment("PATH", old_path)

        try:
            protocol, server_version = validate_server_version(
                connection,
                EXPECTED_SUMO_VERSION,
                EXPECTED_TRACI_PROTOCOL,
                error_type=PaperGridRunError,
            )
            subscribe_normal_lanes(
                connection,
                network,
                error_type=PaperGridRunError,
                empty_network_message="paper grid has no normal lanes",
            )
            runtimes = _discover_intersections(connection, network, metadata)

            while steps < hard_step_cap:
                pre_time_s = float(connection.simulation.getTime())
                commanded = _command_intersections(
                    connection,
                    network,
                    runtimes,
                    config,
                    pre_time_s,
                    event_digest,
                )

                active_ids = tuple(sorted(connection.vehicle.getIDList()))
                for vehicle_id in active_ids:
                    trip = trips.get(vehicle_id)
                    if trip is None:
                        raise PaperGridRunError(
                            f"active vehicle has no departure runtime: {vehicle_id}"
                        )
                    if trip.spec.kind == "CAV":
                        if _route_cav(
                            connection,
                            network,
                            trip,
                            config,
                            pre_time_s,
                            event_digest,
                        ):
                            cav_route_update_count += 1
                    else:
                        trace = _route_hdv(
                            connection,
                            network,
                            trip,
                            config,
                            pre_time_s,
                            random_source,
                            event_digest,
                        )
                        if trace is not None:
                            hdv_decisions.append(trace)

                # Sole global clock advance. Every TLS was commanded above;
                # all boundary observations below belong to this exact tick.
                connection.simulationStep()
                steps += 1
                post_time_s = float(connection.simulation.getTime())

                newly_departed = tuple(sorted(connection.simulation.getDepartedIDList()))
                for vehicle_id in newly_departed:
                    if vehicle_id not in specs:
                        raise PaperGridRunError(f"unexpected departed vehicle: {vehicle_id}")
                    if vehicle_id in departed_ids:
                        raise PaperGridRunError(f"duplicate departure event: {vehicle_id}")
                    spec = specs[vehicle_id]
                    observed_type_id = connection.vehicle.getTypeID(vehicle_id)
                    if observed_type_id != spec.type_id:
                        raise PaperGridRunError(
                            f"departed vehicle type mismatch: {vehicle_id}/{observed_type_id}"
                        )
                    departure_time_s = float(connection.vehicle.getDeparture(vehicle_id))
                    connection.vehicle.subscribe(vehicle_id, VEHICLE_VARIABLES)
                    arrival_position_m, destination_position_m = _destination_geometry(
                        network,
                        spec.destination_edge_id,
                    )
                    trips[vehicle_id] = TripRuntime(
                        spec=spec,
                        destination_position_m=destination_position_m,
                        destination_arrival_position_m=arrival_position_m,
                        eta_remaining_m=config.initial_eta_m,
                    )
                    departed_ids.add(vehicle_id)
                    first_departure_time_s = (
                        departure_time_s
                        if first_departure_time_s is None
                        else min(first_departure_time_s, departure_time_s)
                    )
                    last_departure_time_s = (
                        departure_time_s
                        if last_departure_time_s is None
                        else max(last_departure_time_s, departure_time_s)
                    )
                    bin_index = int(departure_time_s // config.loading_interval_s)
                    if 0 <= bin_index < len(bin_counters):
                        bin_counters[bin_index]["vehicles"] += 1
                        bin_counters[bin_index][spec.kind] += 1
                    else:
                        delayed_departures += 1
                    event_digest.add(
                        "departure",
                        time_s=round(departure_time_s, 6),
                        vehicle_id=vehicle_id,
                        kind=spec.kind,
                    )

                newly_arrived = tuple(connection.simulation.getArrivedIDList())
                arrived_ids.update(newly_arrived)
                if newly_arrived:
                    last_arrival_time_s = post_time_s
                for vehicle_id in sorted(newly_arrived):
                    event_digest.add(
                        "arrival",
                        time_s=round(post_time_s, 6),
                        vehicle_id=vehicle_id,
                    )

                starting_teleports = set(connection.simulation.getStartingTeleportIDList())
                ending_teleports = set(connection.simulation.getEndingTeleportIDList())
                collisions = set(connection.simulation.getCollidingVehiclesIDList())
                starting_teleport_ids.update(starting_teleports)
                ending_teleport_ids.update(ending_teleports)
                colliding_ids.update(collisions)
                if starting_teleports or ending_teleports or collisions:
                    raise PaperGridRunError(
                        "safety failure: "
                        f"starting_teleports={sorted(starting_teleports)}, "
                        f"ending_teleports={sorted(ending_teleports)}, "
                        f"collisions={sorted(collisions)}"
                    )

                _advance_intersections(
                    connection,
                    network,
                    runtimes,
                    commanded,
                    config,
                    post_time_s,
                    event_digest,
                )
                minimum_expected_remaining = int(connection.simulation.getMinExpectedNumber())
                if minimum_expected_remaining == 0:
                    break
            end_time_s = float(connection.simulation.getTime())
            if minimum_expected_remaining != 0:
                incomplete_diagnostics = _incomplete_diagnostics(
                    connection,
                    network,
                    runtimes,
                    config,
                    departed_count=len(departed_ids),
                    arrived_count=len(arrived_ids),
                    last_arrival_time_s=last_arrival_time_s,
                )
                incomplete_diagnostics.update(
                    {
                        "limit_reason": limit_reason,
                        "limit_steps": hard_step_cap,
                        "configured_hard_deadline_s": config.hard_deadline_s,
                        "input_hashes": dict(sorted(input_hashes.items())),
                        "source_commit": _source_commit(root),
                        "source_dirty": _source_dirty(root),
                        "source_hashes": dict(sorted(source_hashes.items())),
                        "resolved_config": _resolved_config_payload(config),
                    }
                )
        finally:
            if connection is not None:
                connection.close()

    _validate_complete_run(
        specs,
        trips,
        departed_ids,
        arrived_ids,
        minimum_expected_remaining,
        incomplete_diagnostics,
        limit_reason,
    )
    if len(trips) != len(specs):
        raise PaperGridRunError("not every expected vehicle received a trip runtime")

    eligible_hdv = tuple(trace for trace in hdv_decisions if trace.random_draw is not None)
    chosen_hdv = tuple(trace for trace in eligible_hdv if trace.chose_alternative)
    for trace in eligible_hdv:
        if trace.chose_alternative != (
            trace.random_draw is not None and trace.random_draw < config.hdv_alternative_probability
        ):
            raise PaperGridRunError("HDV threshold decision disagrees with recorded draw")
        if trace.chose_alternative and trace.selected_edge_id not in trace.alternative_edge_ids:
            raise PaperGridRunError("HDV chose a road outside the alternative candidate set")

    event_digest.add(
        "termination",
        time_s=round(end_time_s, 6),
        steps=steps,
        expected=len(expected_ids),
        departed=len(departed_ids),
        arrived=len(arrived_ids),
        minimum_expected_remaining=minimum_expected_remaining,
        collision_count=len(colliding_ids),
        teleport_count=len(starting_teleport_ids | ending_teleport_ids),
    )
    cav_trips = tuple(trip for trip in trips.values() if trip.spec.kind == "CAV")
    hdv_trips = tuple(trip for trip in trips.values() if trip.spec.kind == "HDV")
    controller_summaries = _controller_summaries(runtimes)
    topology = {
        "tls": len(runtimes),
        "phases": sum(len(runtime.base_phases) for runtime in runtimes.values()),
        "controlled_links": sum(runtime.state_length for runtime in runtimes.values()),
        "normal_edges": len(tuple(network.getEdges(withInternal=False))),
    }
    total_in_horizon = sum(counter["vehicles"] for counter in bin_counters)
    vehicle_counts = {
        "expected": len(expected_ids),
        "expected_cav": expected_kind_counts["CAV"],
        "expected_hdv": expected_kind_counts["HDV"],
        "departed": len(departed_ids),
        "departed_in_horizon": total_in_horizon,
        "arrived": len(arrived_ids),
    }
    termination = {
        "reason": "drained",
        "steps": steps,
        "end_time_s": round(end_time_s, 6),
        "departure_horizon_s": config.departure_horizon_s,
        "drain_timeout_s": config.drain_timeout_s,
        "hard_deadline_s": config.hard_deadline_s,
        "drain_duration_s": round(max(end_time_s - config.departure_horizon_s, 0.0), 6),
        "first_observed_departure_s": first_departure_time_s,
        "last_observed_departure_s": last_departure_time_s,
        "minimum_expected_remaining": minimum_expected_remaining,
    }
    return PaperGridRunResult(
        environment={
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "sumo_package_version": version("eclipse-sumo"),
            "sumo_server_version": server_version,
            "traci_protocol": protocol,
        },
        source_commit=_source_commit(root),
        source_dirty=_source_dirty(root),
        source_hashes=dict(sorted(source_hashes.items())),
        resolved_config=_resolved_config_payload(config),
        input_hashes=dict(sorted(input_hashes.items())),
        topology=topology,
        termination=termination,
        vehicle_counts=vehicle_counts,
        id_digests={
            "expected": _id_digest(expected_ids),
            "departed": _id_digest(departed_ids),
            "arrived": _id_digest(arrived_ids),
        },
        observed_departure_bins=_observed_bins(config, bin_counters),
        delayed_departures_after_horizon=delayed_departures,
        controllers=controller_summaries,
        cav_routing={
            "vehicles": len(cav_trips),
            "encounters": sum(trip.eligible_encounter_count for trip in cav_trips),
            "decisions": sum(trip.decision_count for trip in cav_trips),
            "route_updates": cav_route_update_count,
            "eta_nonincrease_violations": sum(
                trip.eta_nonincrease_violations for trip in cav_trips
            ),
            "minimum_final_eta_m": min(trip.eta_remaining_m for trip in cav_trips),
            "maximum_final_eta_m": max(trip.eta_remaining_m for trip in cav_trips),
        },
        hdv_routing={
            "vehicles": len(hdv_trips),
            "encounters": sum(trip.eligible_encounter_count for trip in hdv_trips),
            "decisions": sum(trip.decision_count for trip in hdv_trips),
            "eligible_alternative_encounters": len(eligible_hdv),
            "chosen_alternatives": len(chosen_hdv),
            "realized_alternative_rate": (
                len(chosen_hdv) / len(eligible_hdv) if eligible_hdv else None
            ),
            "no_eligible_alternative": len(hdv_decisions) - len(eligible_hdv),
        },
        hdv_decisions=tuple(hdv_decisions),
        safety={
            "starting_teleports": tuple(sorted(starting_teleport_ids)),
            "ending_teleports": tuple(sorted(ending_teleport_ids)),
            "collisions": tuple(sorted(colliding_ids)),
        },
        event_digest=event_digest.hexdigest,
    )
