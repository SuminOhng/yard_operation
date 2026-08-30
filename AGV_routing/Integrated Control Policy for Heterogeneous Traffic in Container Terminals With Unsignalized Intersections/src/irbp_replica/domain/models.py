"""Immutable traffic snapshots used by the pure control algorithms."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal


VehicleKind = Literal["CAV", "HDV"]


def _require_nonempty(value: str, field_name: str) -> None:
    if not value:
        raise ValueError(f"{field_name} must not be empty")


def _require_finite(value: float, field_name: str) -> None:
    if not isfinite(value):
        raise ValueError(f"{field_name} must be finite")


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
