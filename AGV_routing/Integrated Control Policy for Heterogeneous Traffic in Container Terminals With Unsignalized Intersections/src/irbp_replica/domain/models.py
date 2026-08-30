"""Immutable traffic snapshots used by the pure control algorithms."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

VehicleKind = Literal["CAV", "HDV"]
PositionM = tuple[float, float]


def _require_nonempty(value: str, field_name: str) -> None:
    if not value:
        raise ValueError(f"{field_name} must not be empty")


def _require_finite(value: float, field_name: str) -> None:
    if not isfinite(value):
        raise ValueError(f"{field_name} must be finite")


def _validated_position(value: PositionM, field_name: str) -> PositionM:
    try:
        coordinates = tuple(value)
    except TypeError as exc:
        raise ValueError(f"{field_name} must contain two coordinates") from exc
    if len(coordinates) != 2:
        raise ValueError(f"{field_name} must contain two coordinates")
    x_m, y_m = (float(coordinate) for coordinate in coordinates)
    _require_finite(x_m, field_name)
    _require_finite(y_m, field_name)
    return (x_m, y_m)


@dataclass(frozen=True, slots=True)
class RoadState:
    """Road quantities expressed in compatible vehicle-slot units."""

    edge_id: str
    length_m: float
    queue_vehicles: float
    remaining_capacity_vehicles: float

    def __post_init__(self) -> None:
        _require_nonempty(self.edge_id, "edge_id")
        _require_finite(self.length_m, "length_m")
        _require_finite(self.queue_vehicles, "queue_vehicles")
        _require_finite(
            self.remaining_capacity_vehicles,
            "remaining_capacity_vehicles",
        )
        if self.length_m <= 0:
            raise ValueError("length_m must be greater than zero")
        if self.queue_vehicles < 0:
            raise ValueError("queue_vehicles must not be negative")
        if self.remaining_capacity_vehicles < 0:
            raise ValueError("remaining_capacity_vehicles must not be negative")


@dataclass(frozen=True, slots=True)
class PhaseState:
    """One VTR station and its conflict-free traffic phase."""

    phase_id: str
    station_id: str
    upstream_edge_id: str
    downstream_edge_ids: tuple[str, ...]
    clockwise_index: int
    head_vehicle_kind: VehicleKind | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.phase_id, "phase_id")
        _require_nonempty(self.station_id, "station_id")
        _require_nonempty(self.upstream_edge_id, "upstream_edge_id")
        if not self.downstream_edge_ids:
            raise ValueError("downstream_edge_ids must not be empty")
        if any(not edge_id for edge_id in self.downstream_edge_ids):
            raise ValueError("downstream_edge_ids must not contain empty IDs")
        if not isinstance(self.clockwise_index, int) or self.clockwise_index < 0:
            raise ValueError("clockwise_index must be a non-negative integer")
        if self.head_vehicle_kind not in (None, "CAV", "HDV"):
            raise ValueError("head_vehicle_kind must be 'CAV', 'HDV', or None")

    @property
    def head_is_hdv(self) -> bool:
        return self.head_vehicle_kind == "HDV"


@dataclass(frozen=True, slots=True)
class VehicleState:
    """One vehicle observation used by equation (8)."""

    vehicle_id: str
    vehicle_kind: VehicleKind
    edge_id: str
    speed_mps: float
    remaining_distance_m: float
    destination_edge_id: str

    def __post_init__(self) -> None:
        _require_nonempty(self.vehicle_id, "vehicle_id")
        if self.vehicle_kind not in ("CAV", "HDV"):
            raise ValueError("vehicle_kind must be 'CAV' or 'HDV'")
        _require_nonempty(self.edge_id, "edge_id")
        _require_nonempty(self.destination_edge_id, "destination_edge_id")
        _require_finite(self.speed_mps, "speed_mps")
        _require_finite(self.remaining_distance_m, "remaining_distance_m")
        if self.speed_mps < 0:
            raise ValueError("speed_mps must not be negative")
        if self.remaining_distance_m < 0:
            raise ValueError("remaining_distance_m must not be negative")


@dataclass(frozen=True, slots=True)
class VehicleRoutingState:
    """Immutable per-trip state used by equations (12)-(17)."""

    vehicle_id: str
    origin_edge_id: str
    destination_edge_id: str
    distance_travelled_m: float
    eta_remaining_m: float
    destination_position_m: PositionM

    def __post_init__(self) -> None:
        _require_nonempty(self.vehicle_id, "vehicle_id")
        _require_nonempty(self.origin_edge_id, "origin_edge_id")
        _require_nonempty(self.destination_edge_id, "destination_edge_id")
        _require_finite(self.distance_travelled_m, "distance_travelled_m")
        _require_finite(self.eta_remaining_m, "eta_remaining_m")
        if self.distance_travelled_m < 0:
            raise ValueError("distance_travelled_m must not be negative")
        if self.eta_remaining_m < 0:
            raise ValueError("eta_remaining_m must not be negative")
        object.__setattr__(
            self,
            "destination_position_m",
            _validated_position(
                self.destination_position_m,
                "destination_position_m",
            ),
        )


@dataclass(frozen=True, slots=True)
class RoutingCandidateState:
    """One downstream road supplied to Algorithm 3."""

    edge_id: str
    downstream_node_id: str
    length_m: float
    downstream_position_m: PositionM
    vehicles: tuple[VehicleState, ...] = ()
    is_legal: bool = True
    destination_reachable: bool = True

    def __post_init__(self) -> None:
        _require_nonempty(self.edge_id, "edge_id")
        _require_nonempty(self.downstream_node_id, "downstream_node_id")
        _require_finite(self.length_m, "length_m")
        if self.length_m <= 0:
            raise ValueError("length_m must be greater than zero")
        object.__setattr__(
            self,
            "downstream_position_m",
            _validated_position(
                self.downstream_position_m,
                "downstream_position_m",
            ),
        )
        vehicles = tuple(self.vehicles)
        if any(not isinstance(vehicle, VehicleState) for vehicle in vehicles):
            raise TypeError("vehicles must contain VehicleState values")
        if any(vehicle.edge_id != self.edge_id for vehicle in vehicles):
            raise ValueError("candidate vehicles must be on the candidate edge")
        vehicle_ids = [vehicle.vehicle_id for vehicle in vehicles]
        if len(vehicle_ids) != len(set(vehicle_ids)):
            raise ValueError("candidate vehicle IDs must be unique")
        if not isinstance(self.is_legal, bool):
            raise TypeError("is_legal must be a bool")
        if not isinstance(self.destination_reachable, bool):
            raise TypeError("destination_reachable must be a bool")
        object.__setattr__(self, "vehicles", vehicles)
