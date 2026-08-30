"""Deterministic TraCI smoke adapter for the one-intersection replica network.

The mathematical BP/VTR and IR-BP modules remain pure.  This module is the
small live-adapter boundary: it samples SUMO, constructs immutable domain
snapshots, applies one routing mutation, and drives one controller tick per
simulation step.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
from importlib.metadata import version
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
from irbp_replica.domain.models import (
    PhaseState,
    RoadState,
    RoutingCandidateState,
    VehicleRoutingState,
    VehicleState,
)
from irbp_replica.routing.irbp import RoutingDecision, select_next_edge
from irbp_replica.simulation import traci_adapter

EXPECTED_SUMO_VERSION = "1.27.1"
EXPECTED_TRACI_PROTOCOL = 22
TLS_ID = "junction"
CAV_ID = "cav_0"
CAV_TYPE_ID = "cav"
WEST_EDGE_ID = "w_in"
SOUTH_EDGE_ID = "s_in"
WEST_OUT_EDGE_ID = "e_out"
SOUTH_OUT_EDGE_ID = "n_out"
PHASE_BY_EDGE = {
    WEST_EDGE_ID: ("west_phase", "west_station", 0),
    SOUTH_EDGE_ID: ("south_phase", "south_station", 1),
}
STEP_LENGTH_S = 1.0
CYCLE_LENGTH_S = 10.0
EXTENSION_INCREMENT_S = 1.0
VEHICLE_SLOT_M = 7.5
QUEUE_SPEED_THRESHOLD_MPS = 0.1
INITIAL_ETA_M = 500.0
ROUTING_SPEED_FLOOR_MPS = 0.1
SUMO_SEED = 42
VEHICLE_KIND_BY_TYPE_ID = {
    "cav": "CAV",
    "truck": "HDV",
    "slow_hdv": "HDV",
}


class SmokeRunError(RuntimeError):
    """Raised when a live integration invariant fails."""


@dataclass(frozen=True, slots=True)
class SignalRun:
    """One compact run of an unchanged commanded signal state."""

    start_time_s: float
    end_time_s: float
    steps: int
    state: str
    mode: str
    active_phase_id: str | None


@dataclass(frozen=True, slots=True)
class BoundaryTrace:
    """One Algorithm 1/2 service-boundary outcome."""

    time_s: float
    phase_id: str
    station_id: str
    outcome: str


@dataclass(frozen=True, slots=True)
class CycleTrace:
    """One non-empty cycle plan made from a live SUMO snapshot."""

    cycle_index: int
    time_s: float
    station_order: tuple[str, ...]
    durations_s: tuple[float, ...]
    weights: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class CandidateTrace:
    """Compact Algorithm 3 score retained by the integration trace."""

    edge_id: str
    status: str
    controlling_vehicle_id: str | None
    travel_time_s: float | None
    pressure_weight_mps: float | None
    distance_cost_m: float | None
    detour_excess_m: float | None


@dataclass(frozen=True, slots=True)
class RouteTrace:
    """The one transactional CAV route change performed by the smoke run."""

    time_s: float
    vehicle_id: str
    source_edge_id: str
    destination_edge_id: str
    arrival_position_m: float
    destination_position_m: tuple[float, float]
    selected_edge_id: str
    eta_before_m: float
    eta_after_m: float
    route_after: tuple[str, ...]
    scores: tuple[CandidateTrace, ...]


@dataclass(frozen=True, slots=True)
class InputHash:
    """One stable SHA-256 identifier for a SUMO input artifact."""

    relative_path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ControlledLinkIndex:
    """Runtime link indexes discovered through ``getControlledLinks``."""

    incoming_edge_id: str
    link_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SmokeResult:
    """Stable, JSON-serializable proof returned by a complete smoke run."""

    sumo_package_version: str
    sumo_server_version: str
    traci_protocol: int
    seed: int
    step_length_s: float
    effective_slot_length_m: float
    input_hashes: tuple[InputHash, ...]
    controlled_link_indexes: tuple[ControlledLinkIndex, ...]
    subscribed_lane_ids: tuple[str, ...]
    subscribed_vehicle_ids: tuple[str, ...]
    validated_vehicle_subscription_observations: int
    steps: int
    end_time_s: float
    minimum_expected_remaining: int
    expected_vehicle_ids: tuple[str, ...]
    departed_vehicle_ids: tuple[str, ...]
    arrived_vehicle_ids: tuple[str, ...]
    teleported_vehicle_ids: tuple[str, ...]
    starting_teleport_vehicle_ids: tuple[str, ...]
    ending_teleport_vehicle_ids: tuple[str, ...]
    colliding_vehicle_ids: tuple[str, ...]
    route_update_count: int
    route: RouteTrace
    signal_runs: tuple[SignalRun, ...]
    cycle_plans: tuple[CycleTrace, ...]
    boundary_events: tuple[BoundaryTrace, ...]

    def normalized_payload(self) -> dict[str, Any]:
        """Return run data with no process label, port, or temporary path."""

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


@dataclass(slots=True)
class _MutableSignalRun:
    start_time_s: float
    end_time_s: float
    steps: int
    state: str
    mode: str
    active_phase_id: str | None


def default_project_root() -> Path:
    """Locate the repository root from this installed or source module."""

    return Path(__file__).resolve().parents[3]


def _network_directory(project_root: Path) -> Path:
    return project_root / "sumo" / "networks" / "smoke_intersection"


def _sumo_installation() -> tuple[Path, Path]:
    return traci_adapter.sumo_installation(
        EXPECTED_SUMO_VERSION,
        error_type=SmokeRunError,
    )


def _expected_vehicle_ids(route_file: Path) -> tuple[str, ...]:
    root = ElementTree.parse(route_file).getroot()
    vehicle_ids = tuple(
        sorted(
            element.attrib["id"] for element in root.findall("vehicle") if "id" in element.attrib
        )
    )
    if CAV_ID not in vehicle_ids:
        raise SmokeRunError(f"route file does not declare {CAV_ID}")
    if len(vehicle_ids) != len(set(vehicle_ids)):
        raise SmokeRunError("route file contains duplicate vehicle IDs")
    return vehicle_ids


def _input_hashes(project_root: Path, paths: Iterable[Path]) -> tuple[InputHash, ...]:
    return tuple(
        InputHash(
            relative_path=path.relative_to(project_root).as_posix(),
            sha256=sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(paths, key=lambda value: value.as_posix())
    )


def _validate_cav_arrival_position(route_file: Path) -> None:
    root = ElementTree.parse(route_file).getroot()
    cav = next(
        (element for element in root.findall("vehicle") if element.get("id") == CAV_ID),
        None,
    )
    if cav is None or cav.get("arrivalPos") != "max":
        raise SmokeRunError(f"{CAV_ID} must declare arrivalPos='max'")


def _edge_lane_ids(network: Any, edge_id: str) -> tuple[str, ...]:
    return traci_adapter.edge_lane_ids(network, edge_id)


def _vehicle_subscription_value(connection: Any, vehicle_id: str, variable: int) -> Any:
    return traci_adapter.vehicle_subscription_value(
        connection,
        vehicle_id,
        variable,
        error_type=SmokeRunError,
    )


def _vehicle_kind(connection: Any, vehicle_id: str) -> str:
    return traci_adapter.vehicle_kind(
        connection,
        vehicle_id,
        VEHICLE_KIND_BY_TYPE_ID,
        error_type=SmokeRunError,
    )


def _vehicles_on_edge(connection: Any, network: Any, edge_id: str) -> tuple[str, ...]:
    return traci_adapter.vehicles_on_edge(
        connection,
        network,
        edge_id,
        error_type=SmokeRunError,
    )


def _queue_vehicle_ids(connection: Any, network: Any, edge_id: str) -> tuple[str, ...]:
    return traci_adapter.queue_vehicle_ids(
        connection,
        network,
        edge_id,
        QUEUE_SPEED_THRESHOLD_MPS,
        error_type=SmokeRunError,
    )


def _queue_leader_kind(connection: Any, network: Any, edge_id: str) -> str | None:
    return traci_adapter.queue_leader_kind(
        connection,
        network,
        edge_id,
        VEHICLE_KIND_BY_TYPE_ID,
        QUEUE_SPEED_THRESHOLD_MPS,
        error_type=SmokeRunError,
    )


def _edge_length(connection: Any, network: Any, edge_id: str) -> float:
    return traci_adapter.edge_length(
        connection,
        network,
        edge_id,
        error_type=SmokeRunError,
    )


def _remaining_capacity_slots(connection: Any, network: Any, edge_id: str) -> float:
    return traci_adapter.remaining_capacity_slots(
        connection,
        network,
        edge_id,
        VEHICLE_SLOT_M,
        error_type=SmokeRunError,
    )


def _phase_snapshot(connection: Any, network: Any) -> tuple[PhaseState, ...]:
    return tuple(
        PhaseState(
            phase_id=phase_id,
            station_id=station_id,
            upstream_edge_id=edge_id,
            downstream_edge_ids=(
                WEST_OUT_EDGE_ID if edge_id == WEST_EDGE_ID else SOUTH_OUT_EDGE_ID,
            ),
            clockwise_index=clockwise_index,
            head_vehicle_kind=_queue_leader_kind(connection, network, edge_id),
        )
        for edge_id, (phase_id, station_id, clockwise_index) in PHASE_BY_EDGE.items()
    )


def _road_snapshot(
    connection: Any,
    network: Any,
    phases: Iterable[PhaseState],
) -> dict[str, RoadState]:
    return traci_adapter.road_snapshot(
        connection,
        network,
        phases,
        vehicle_slot_m=VEHICLE_SLOT_M,
        queue_speed_threshold_mps=QUEUE_SPEED_THRESHOLD_MPS,
        error_type=SmokeRunError,
    )


def _controlled_link_indexes(connection: Any) -> tuple[dict[str, tuple[int, ...]], int]:
    return traci_adapter.controlled_link_indexes(
        connection,
        TLS_ID,
        PHASE_BY_EDGE,
        error_type=SmokeRunError,
    )


def _subscribe_normal_lanes(connection: Any, network: Any) -> tuple[str, ...]:
    return traci_adapter.subscribe_normal_lanes(
        connection,
        network,
        error_type=SmokeRunError,
        empty_network_message="smoke network has no normal lanes",
    )


def _validate_lane_subscriptions(connection: Any, lane_ids: Iterable[str]) -> None:
    traci_adapter.validate_lane_subscriptions(
        connection,
        lane_ids,
        error_type=SmokeRunError,
    )


def _validate_vehicle_subscriptions(connection: Any, vehicle_ids: Iterable[str]) -> int:
    return traci_adapter.validate_vehicle_subscriptions(
        connection,
        vehicle_ids,
        error_type=SmokeRunError,
    )


def _signal_state(
    active_phase_id: str | None,
    phases: Iterable[PhaseState],
    link_indexes: Mapping[str, tuple[int, ...]],
    state_length: int,
) -> str:
    return traci_adapter.signal_state(
        active_phase_id,
        phases,
        link_indexes,
        state_length,
        error_type=SmokeRunError,
    )


def _build_executor(
    connection: Any,
    network: Any,
    last_station_id: str,
    simulation_time_s: float,
    cycle_index: int,
) -> tuple[VTRCycleExecutor | None, CycleTrace | None]:
    phases = _phase_snapshot(connection, network)
    roads = _road_snapshot(connection, network, phases)
    plan = build_cycle_plan(
        phases,
        roads,
        last_station_id=last_station_id,
        cycle_length_s=CYCLE_LENGTH_S,
        resolution_s=STEP_LENGTH_S,
    )
    if not plan:
        return None, None
    executor = VTRCycleExecutor(
        plan,
        previous_station_id=last_station_id,
        step_length_s=STEP_LENGTH_S,
        extension_increment_s=EXTENSION_INCREMENT_S,
        maximum_extension_s=None,
        clearance_time_s=0.0,
    )
    trace = CycleTrace(
        cycle_index=cycle_index,
        time_s=round(simulation_time_s, 6),
        station_order=tuple(slot.station_id for slot in plan),
        durations_s=tuple(round(slot.initial_duration_s, 6) for slot in plan),
        weights=tuple(round(slot.weight, 12) for slot in plan),
    )
    return executor, trace


def _reachable_stage(
    connection: Any,
    candidate_edge_id: str,
    destination_edge_id: str,
    vehicle_type_id: str,
    simulation_time_s: float,
    arrival_position_m: float,
) -> Any | None:
    return traci_adapter.reachable_stage(
        connection,
        candidate_edge_id,
        destination_edge_id,
        vehicle_type_id,
        simulation_time_s,
        arrival_position_m,
    )


def _candidate_snapshot(
    connection: Any,
    network: Any,
    cav: VehicleState,
    candidate_edge: Any,
    simulation_time_s: float,
    destination_edge_id: str,
    arrival_position_m: float,
    destination_position_m: tuple[float, float],
) -> tuple[RoutingCandidateState, Any | None]:
    return traci_adapter.candidate_snapshot(
        connection,
        network,
        cav.vehicle_id,
        candidate_edge,
        simulation_time_s,
        destination_edge_id,
        arrival_position_m,
        destination_position_m,
        VEHICLE_KIND_BY_TYPE_ID,
        error_type=SmokeRunError,
    )


def _route_cav_once(
    connection: Any,
    network: Any,
    eta_remaining_m: float,
) -> tuple[RouteTrace, float]:
    simulation_time_s = float(connection.simulation.getTime())
    current_edge_id = str(_vehicle_subscription_value(connection, CAV_ID, tc.VAR_ROAD_ID))
    if not current_edge_id or current_edge_id.startswith(":"):
        raise SmokeRunError(f"{CAV_ID} is not on a routable source edge")
    original_route = tuple(connection.vehicle.getRoute(CAV_ID))
    destination_edge_id = original_route[-1]
    current_edge = network.getEdge(current_edge_id)
    destination_edge = network.getEdge(destination_edge_id)
    outgoing_edges = traci_adapter.outgoing_edges(network, current_edge_id)
    if not outgoing_edges:
        raise SmokeRunError(f"no routing candidates from {current_edge_id}")
    candidate_edge_ids = tuple(edge.getID() for edge in outgoing_edges)
    if candidate_edge_ids != ("bypass_w", "w_in"):
        raise SmokeRunError(
            "smoke fixture must expose exactly sorted candidates "
            f"('bypass_w', 'w_in'); found {candidate_edge_ids}"
        )

    cav_lane_id = str(_vehicle_subscription_value(connection, CAV_ID, tc.VAR_LANE_ID))
    cav_remaining_m = max(
        float(connection.lane.getLength(cav_lane_id))
        - float(_vehicle_subscription_value(connection, CAV_ID, tc.VAR_LANEPOSITION)),
        0.0,
    )
    cav = VehicleState(
        vehicle_id=CAV_ID,
        vehicle_kind="CAV",
        edge_id=current_edge_id,
        speed_mps=max(
            float(_vehicle_subscription_value(connection, CAV_ID, tc.VAR_SPEED)),
            0.0,
        ),
        remaining_distance_m=cav_remaining_m,
        destination_edge_id=destination_edge_id,
    )
    destination_lanes = tuple(destination_edge.getLanes())
    if len(destination_lanes) != 1:
        raise SmokeRunError("smoke destination edge must have exactly one lane")
    destination_lane = destination_lanes[0]
    destination_shape = tuple(destination_lane.getShape())
    if not destination_shape:
        raise SmokeRunError("smoke destination lane has no shape")
    arrival_position_m = float(destination_lane.getLength())
    destination_position_m = tuple(float(value) for value in destination_shape[-1])
    trip = VehicleRoutingState(
        vehicle_id=CAV_ID,
        origin_edge_id=original_route[0],
        destination_edge_id=destination_edge_id,
        # The decision belongs to route_split.  Equation (12) therefore uses
        # completed distance through the incoming cav_src edge, never the
        # CAV's partial live getDistance() value at adapter sampling time.
        distance_travelled_m=float(current_edge.getLength()),
        eta_remaining_m=eta_remaining_m,
        destination_position_m=destination_position_m,
    )

    candidates: list[RoutingCandidateState] = []
    stages: dict[str, Any] = {}
    for edge in outgoing_edges:
        candidate, stage = _candidate_snapshot(
            connection,
            network,
            cav,
            edge,
            simulation_time_s,
            destination_edge_id,
            arrival_position_m,
            destination_position_m,
        )
        candidates.append(candidate)
        if stage is not None:
            stages[candidate.edge_id] = stage

    empty_road_speed_mps = max(
        float(connection.lane.getMaxSpeed(lane_id))
        for candidate in candidates
        for lane_id in _edge_lane_ids(network, candidate.edge_id)
    )
    decision: RoutingDecision = select_next_edge(
        cav,
        trip,
        candidates,
        empty_road_speed_mps=empty_road_speed_mps,
        speed_floor_mps=ROUTING_SPEED_FLOOR_MPS,
    )
    selected_stage = stages.get(decision.selected_edge_id)
    if selected_stage is None:
        raise SmokeRunError("selected route has no destination-reachable suffix")
    suffix = tuple(selected_stage.edges)
    # Transaction boundary: eta is returned only after SUMO accepts and echoes
    # the entire current-edge-first route.
    committed_route = traci_adapter.commit_route(
        connection,
        CAV_ID,
        current_edge_id,
        decision.selected_edge_id,
        suffix,
        vehicle_label="CAV",
        error_type=SmokeRunError,
    )

    score_traces = tuple(
        CandidateTrace(
            edge_id=score.edge_id,
            status=score.status,
            controlling_vehicle_id=score.controlling_vehicle_id,
            travel_time_s=(None if score.travel_time_s is None else round(score.travel_time_s, 6)),
            pressure_weight_mps=(
                None if score.pressure_weight_mps is None else round(score.pressure_weight_mps, 6)
            ),
            distance_cost_m=(
                None if score.distance_cost_m is None else round(score.distance_cost_m, 6)
            ),
            detour_excess_m=(
                None if score.detour_excess_m is None else round(score.detour_excess_m, 6)
            ),
        )
        for score in decision.scores
    )
    trace = RouteTrace(
        time_s=round(simulation_time_s, 6),
        vehicle_id=CAV_ID,
        source_edge_id=current_edge_id,
        destination_edge_id=destination_edge_id,
        arrival_position_m=round(arrival_position_m, 6),
        destination_position_m=tuple(round(value, 6) for value in destination_position_m),
        selected_edge_id=decision.selected_edge_id,
        eta_before_m=round(decision.eta_before_m, 6),
        eta_after_m=round(decision.updated_eta_m, 6),
        route_after=committed_route,
        scores=score_traces,
    )
    return trace, decision.updated_eta_m


def _append_signal_run(
    runs: list[_MutableSignalRun],
    *,
    start_time_s: float,
    end_time_s: float,
    state: str,
    mode: str,
    active_phase_id: str | None,
) -> None:
    if (
        runs
        and runs[-1].state == state
        and runs[-1].mode == mode
        and runs[-1].active_phase_id == active_phase_id
    ):
        runs[-1].end_time_s = round(end_time_s, 6)
        runs[-1].steps += 1
        return
    runs.append(
        _MutableSignalRun(
            start_time_s=round(start_time_s, 6),
            end_time_s=round(end_time_s, 6),
            steps=1,
            state=state,
            mode=mode,
            active_phase_id=active_phase_id,
        )
    )


def _freeze_signal_runs(runs: Iterable[_MutableSignalRun]) -> tuple[SignalRun, ...]:
    return tuple(
        SignalRun(
            start_time_s=run.start_time_s,
            end_time_s=run.end_time_s,
            steps=run.steps,
            state=run.state,
            mode=run.mode,
            active_phase_id=run.active_phase_id,
        )
        for run in runs
    )


def _validate_server_version(connection: Any) -> tuple[int, str]:
    return traci_adapter.validate_server_version(
        connection,
        EXPECTED_SUMO_VERSION,
        EXPECTED_TRACI_PROTOCOL,
        error_type=SmokeRunError,
    )


def _restore_environment(name: str, old_value: str | None) -> None:
    traci_adapter.restore_environment(name, old_value)


def run_sumo_smoke(
    project_root: str | Path | None = None,
    *,
    max_steps: int = 180,
) -> SmokeResult:
    """Run the real SUMO/TraCI adapter twice identically when called twice."""

    if not isinstance(max_steps, int) or max_steps <= 0:
        raise ValueError("max_steps must be a positive integer")
    root = Path(project_root).resolve() if project_root is not None else default_project_root()
    network_directory = _network_directory(root)
    config_path = network_directory / "smoke.sumocfg"
    network_path = network_directory / "smoke.net.xml"
    route_path = network_directory / "smoke.rou.xml"
    for required_path in (config_path, network_path, route_path):
        if not required_path.is_file():
            raise SmokeRunError(f"required smoke asset not found: {required_path}")
    expected_vehicle_ids = _expected_vehicle_ids(route_path)
    _validate_cav_arrival_position(route_path)
    sumo_home, sumo_binary = _sumo_installation()
    network = sumolib.net.readNet(str(network_path), withInternal=True)

    connection = None
    label = f"irbp-smoke-{uuid4().hex}"
    departed_ids: set[str] = set()
    arrived_ids: set[str] = set()
    teleported_ids: set[str] = set()
    starting_teleport_ids: set[str] = set()
    ending_teleport_ids: set[str] = set()
    colliding_ids: set[str] = set()
    signal_runs: list[_MutableSignalRun] = []
    cycle_traces: list[CycleTrace] = []
    boundary_traces: list[BoundaryTrace] = []
    route_trace: RouteTrace | None = None
    route_update_count = 0
    validated_vehicle_subscription_observations = 0
    eta_remaining_m = INITIAL_ETA_M
    executor: VTRCycleExecutor | None = None
    last_station_id = PHASE_BY_EDGE[SOUTH_EDGE_ID][1]
    steps = 0
    minimum_expected_remaining = len(expected_vehicle_ids)
    input_hashes = _input_hashes(root, (config_path, network_path, route_path))

    with TemporaryDirectory(prefix="irbp-sumo-smoke-") as temporary_directory:
        temporary_path = Path(temporary_directory)
        command = [
            str(sumo_binary),
            "-c",
            str(config_path),
            "--seed",
            str(SUMO_SEED),
            "--step-length",
            str(STEP_LENGTH_S),
            "--threads",
            "1",
            "--end",
            str(max_steps),
            "--no-step-log",
            "true",
            "--duration-log.disable",
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
            _restore_environment("SUMO_HOME", old_sumo_home)
            _restore_environment("PATH", old_path)

        try:
            protocol, server_version = _validate_server_version(connection)
            link_indexes, state_length = _controlled_link_indexes(connection)
            subscribed_lane_ids = _subscribe_normal_lanes(connection, network)
            connection.trafficlight.subscribe(
                TLS_ID,
                (tc.TL_RED_YELLOW_GREEN_STATE,),
            )

            while steps < max_steps:
                pre_time_s = float(connection.simulation.getTime())
                if executor is None:
                    executor, cycle_trace = _build_executor(
                        connection,
                        network,
                        last_station_id,
                        pre_time_s,
                        len(cycle_traces) + 1,
                    )
                    if cycle_trace is not None:
                        cycle_traces.append(cycle_trace)

                phases = _phase_snapshot(connection, network)
                snapshot = executor.snapshot() if executor is not None else None
                active_phase_id = (
                    snapshot.active_phase_id
                    if snapshot is not None and snapshot.mode == "ACTIVE"
                    else None
                )
                mode = snapshot.mode if snapshot is not None else "IDLE"
                state = _signal_state(
                    active_phase_id,
                    phases,
                    link_indexes,
                    state_length,
                )
                if state.count("G") > max(len(link_indexes[edge_id]) for edge_id in PHASE_BY_EDGE):
                    raise SmokeRunError("signal command activates conflicting approaches")
                connection.trafficlight.setRedYellowGreenState(TLS_ID, state)
                if connection.trafficlight.getRedYellowGreenState(TLS_ID) != state:
                    raise SmokeRunError("SUMO did not apply the commanded signal state")

                active_vehicle_ids = set(connection.vehicle.getIDList())
                if route_trace is None and CAV_ID in active_vehicle_ids:
                    current_edge_id = str(
                        _vehicle_subscription_value(
                            connection,
                            CAV_ID,
                            tc.VAR_ROAD_ID,
                        )
                    )
                    if current_edge_id == "cav_src":
                        route_trace, eta_remaining_m = _route_cav_once(
                            connection,
                            network,
                            eta_remaining_m,
                        )
                        route_update_count += 1

                # Sole clock advance in the loop.  All extension observations
                # below are post-step values from this exact tick.
                connection.simulationStep()
                steps += 1
                post_time_s = float(connection.simulation.getTime())
                _append_signal_run(
                    signal_runs,
                    start_time_s=pre_time_s,
                    end_time_s=post_time_s,
                    state=state,
                    mode=mode,
                    active_phase_id=active_phase_id,
                )

                newly_departed = tuple(connection.simulation.getDepartedIDList())
                for vehicle_id in newly_departed:
                    departed_ids.add(vehicle_id)
                    connection.vehicle.subscribe(
                        vehicle_id,
                        (
                            tc.VAR_ROAD_ID,
                            tc.VAR_SPEED,
                            tc.VAR_LANEPOSITION,
                            tc.VAR_TYPE,
                            tc.VAR_LANE_ID,
                        ),
                    )
                arrived_ids.update(connection.simulation.getArrivedIDList())
                starting_teleports = tuple(connection.simulation.getStartingTeleportIDList())
                ending_teleports = tuple(connection.simulation.getEndingTeleportIDList())
                starting_teleport_ids.update(starting_teleports)
                ending_teleport_ids.update(ending_teleports)
                teleported_ids.update(starting_teleports)
                teleported_ids.update(ending_teleports)
                colliding_ids.update(connection.simulation.getCollidingVehiclesIDList())
                _validate_lane_subscriptions(connection, subscribed_lane_ids)
                active_subscribed_vehicle_ids = tuple(
                    sorted(set(connection.vehicle.getIDList()) & departed_ids)
                )
                validated_vehicle_subscription_observations += _validate_vehicle_subscriptions(
                    connection,
                    active_subscribed_vehicle_ids,
                )

                subscribed_tls = connection.trafficlight.getSubscriptionResults(TLS_ID)
                if (
                    subscribed_tls is None
                    or subscribed_tls.get(tc.TL_RED_YELLOW_GREEN_STATE) != state
                ):
                    raise SmokeRunError("traffic-light subscription disagrees with command")

                if executor is not None:
                    leader_kind = (
                        _queue_leader_kind(
                            connection,
                            network,
                            next(
                                phase.upstream_edge_id
                                for phase in phases
                                if phase.phase_id == active_phase_id
                            ),
                        )
                        if active_phase_id is not None
                        else None
                    )
                    post_snapshot = executor.advance_after_step(
                        post_step_queue_leader=leader_kind,
                    )
                    if post_snapshot.boundary_outcome is not None:
                        if (
                            post_snapshot.boundary_phase_id is None
                            or post_snapshot.boundary_station_id is None
                        ):
                            raise SmokeRunError("controller boundary trace is incomplete")
                        boundary_traces.append(
                            BoundaryTrace(
                                time_s=round(post_time_s, 6),
                                phase_id=post_snapshot.boundary_phase_id,
                                station_id=post_snapshot.boundary_station_id,
                                outcome=post_snapshot.boundary_outcome,
                            )
                        )
                    if executor.is_complete:
                        last_station_id = executor.last_completed_station_id
                        executor, cycle_trace = _build_executor(
                            connection,
                            network,
                            last_station_id,
                            post_time_s,
                            len(cycle_traces) + 1,
                        )
                        if cycle_trace is not None:
                            cycle_traces.append(cycle_trace)

                minimum_expected_remaining = int(connection.simulation.getMinExpectedNumber())
                if minimum_expected_remaining == 0:
                    break

            end_time_s = float(connection.simulation.getTime())
        finally:
            connection.close()

    if route_trace is None or route_update_count != 1:
        raise SmokeRunError(f"expected one CAV route update; observed {route_update_count}")
    missing_departures = set(expected_vehicle_ids) - departed_ids
    missing_arrivals = set(expected_vehicle_ids) - arrived_ids
    if missing_departures:
        raise SmokeRunError(f"vehicles never departed: {sorted(missing_departures)}")
    if missing_arrivals:
        raise SmokeRunError(f"vehicles did not arrive: {sorted(missing_arrivals)}")
    if teleported_ids:
        raise SmokeRunError(f"vehicles teleported: {sorted(teleported_ids)}")
    if colliding_ids:
        raise SmokeRunError(f"vehicles collided: {sorted(colliding_ids)}")
    if minimum_expected_remaining != 0:
        raise SmokeRunError(
            f"simulation reached hard step cap {max_steps} with "
            f"minExpected={minimum_expected_remaining}"
        )

    return SmokeResult(
        sumo_package_version=version("eclipse-sumo"),
        sumo_server_version=server_version,
        traci_protocol=protocol,
        seed=SUMO_SEED,
        step_length_s=STEP_LENGTH_S,
        effective_slot_length_m=VEHICLE_SLOT_M,
        input_hashes=input_hashes,
        controlled_link_indexes=tuple(
            ControlledLinkIndex(edge_id, indexes)
            for edge_id, indexes in sorted(link_indexes.items())
        ),
        subscribed_lane_ids=subscribed_lane_ids,
        subscribed_vehicle_ids=tuple(sorted(departed_ids)),
        validated_vehicle_subscription_observations=(validated_vehicle_subscription_observations),
        steps=steps,
        end_time_s=round(end_time_s, 6),
        minimum_expected_remaining=minimum_expected_remaining,
        expected_vehicle_ids=expected_vehicle_ids,
        departed_vehicle_ids=tuple(sorted(departed_ids)),
        arrived_vehicle_ids=tuple(sorted(arrived_ids)),
        teleported_vehicle_ids=tuple(sorted(teleported_ids)),
        starting_teleport_vehicle_ids=tuple(sorted(starting_teleport_ids)),
        ending_teleport_vehicle_ids=tuple(sorted(ending_teleport_ids)),
        colliding_vehicle_ids=tuple(sorted(colliding_ids)),
        route_update_count=route_update_count,
        route=route_trace,
        signal_runs=_freeze_signal_runs(signal_runs),
        cycle_plans=tuple(cycle_traces),
        boundary_events=tuple(boundary_traces),
    )
