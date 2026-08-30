"""Back-pressure equations (1)-(4) from the source paper."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from math import isfinite

from irbp_replica.domain.models import PhaseState, RoadState


def _nonnegative_finite(value: float, field_name: str) -> float:
    value = float(value)
    if not isfinite(value) or value < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return value


def _positive_finite(value: float, field_name: str) -> float:
    value = float(value)
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{field_name} must be finite and greater than zero")
    return value


def movement_pressure(
    queue_vehicles: float,
    downstream_capacity_vehicles: float,
) -> float:
    """Return movement pressure from equation (1)."""

    queue = _nonnegative_finite(queue_vehicles, "queue_vehicles")
    capacity = _nonnegative_finite(
        downstream_capacity_vehicles,
        "downstream_capacity_vehicles",
    )
    return min(queue, capacity)


def normalized_movement_pressure(
    queue_vehicles: float,
    downstream_capacity_vehicles: float,
    upstream_length_m: float,
) -> float:
    """Return road-length-normalized movement pressure from equation (2)."""

    length = _positive_finite(upstream_length_m, "upstream_length_m")
    return movement_pressure(queue_vehicles, downstream_capacity_vehicles) / length


def phase_pressure(
    queue_vehicles: float,
    downstream_capacities_vehicles: Iterable[float],
    upstream_length_m: float,
) -> float:
    """Return aggregate phase pressure from equation (3)."""

    queue = _nonnegative_finite(queue_vehicles, "queue_vehicles")
    length = _positive_finite(upstream_length_m, "upstream_length_m")
    capacities = tuple(
        _nonnegative_finite(value, "downstream_capacity_vehicles")
        for value in downstream_capacities_vehicles
    )
    if not capacities:
        raise ValueError("downstream_capacities_vehicles must not be empty")
    return min(queue, sum(capacities)) / length


def phase_weight(pressure: float) -> float:
    """Clamp phase pressure to the non-negative weight in equation (4)."""

    pressure = float(pressure)
    if not isfinite(pressure):
        raise ValueError("pressure must be finite")
    return max(pressure, 0.0)


def compute_phase_weight(
    phase: PhaseState,
    roads: Mapping[str, RoadState],
) -> float:
    """Evaluate equations (3)-(4) for one phase snapshot."""

    try:
        upstream = roads[phase.upstream_edge_id]
    except KeyError as exc:
        raise KeyError(f"unknown upstream edge: {phase.upstream_edge_id}") from exc

    downstream_capacities: list[float] = []
    for edge_id in phase.downstream_edge_ids:
        try:
            downstream_capacities.append(roads[edge_id].remaining_capacity_vehicles)
        except KeyError as exc:
            raise KeyError(f"unknown downstream edge: {edge_id}") from exc

    pressure = phase_pressure(
        upstream.queue_vehicles,
        downstream_capacities,
        upstream.length_m,
    )
    return phase_weight(pressure)
