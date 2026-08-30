"""Travel-time pressure for IR-BP equations (8)-(10)."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from irbp_replica.domain.models import RoutingCandidateState, VehicleState


@dataclass(frozen=True, slots=True)
class TravelTimeEstimate:
    """Equation (8) value and the vehicle attaining its maximum."""

    travel_time_s: float
    controlling_vehicle_id: str | None


def _positive_finite(value: float, field_name: str) -> float:
    value = float(value)
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{field_name} must be finite and greater than zero")
    return value


def _nonnegative_finite(value: float, field_name: str) -> float:
    value = float(value)
    if not isfinite(value) or value < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return value


def estimate_candidate_travel_time(
    cav: VehicleState,
    candidate: RoutingCandidateState,
    *,
    empty_road_speed_mps: float,
    speed_floor_mps: float,
    distance_tolerance_m: float = 1e-9,
) -> float:
    """Return the equation (8) time, including the declared empty-road rule."""

    return evaluate_candidate_travel_time(
        cav,
        candidate,
        empty_road_speed_mps=empty_road_speed_mps,
        speed_floor_mps=speed_floor_mps,
        distance_tolerance_m=distance_tolerance_m,
    ).travel_time_s


def evaluate_candidate_travel_time(
    cav: VehicleState,
    candidate: RoutingCandidateState,
    *,
    empty_road_speed_mps: float,
    speed_floor_mps: float,
    distance_tolerance_m: float = 1e-9,
) -> TravelTimeEstimate:
    """Evaluate equation (8) and retain its controlling vehicle for traces."""

    if cav.vehicle_kind != "CAV":
        raise ValueError("equation (8) requires a CAV")
    empty_speed = _positive_finite(
        empty_road_speed_mps,
        "empty_road_speed_mps",
    )
    speed_floor = _positive_finite(speed_floor_mps, "speed_floor_mps")
    distance_tolerance = _nonnegative_finite(
        distance_tolerance_m,
        "distance_tolerance_m",
    )

    if not candidate.vehicles:
        travel_time = candidate.length_m / empty_speed
        if not isfinite(travel_time) or travel_time <= 0:
            raise ValueError("empty-road rule produced an invalid travel time")
        return TravelTimeEstimate(travel_time, None)

    cav_speed = max(cav.speed_mps, speed_floor)
    travel_times: list[tuple[float, str]] = []
    for vehicle in candidate.vehicles:
        remaining_distance = vehicle.remaining_distance_m
        if remaining_distance > candidate.length_m + distance_tolerance:
            raise ValueError(
                "vehicle remaining_distance_m exceeds candidate length_m"
            )
        remaining_distance = min(remaining_distance, candidate.length_m)
        vehicle_speed = max(vehicle.speed_mps, speed_floor)
        travel_time = (
            (candidate.length_m - remaining_distance) / vehicle_speed
            + remaining_distance / cav_speed
        )
        if not isfinite(travel_time) or travel_time <= 0:
            raise ValueError("equation (8) produced an invalid travel time")
        travel_times.append((travel_time, vehicle.vehicle_id))
    maximum_time = max(travel_time for travel_time, _ in travel_times)
    controlling_vehicle_id = min(
        vehicle_id
        for travel_time, vehicle_id in travel_times
        if travel_time == maximum_time
    )
    return TravelTimeEstimate(maximum_time, controlling_vehicle_id)


def routing_pressure(length_m: float, travel_time_s: float) -> float:
    """Evaluate equation (9)."""

    length = _positive_finite(length_m, "length_m")
    travel_time = _positive_finite(travel_time_s, "travel_time_s")
    pressure = length / travel_time
    if not isfinite(pressure) or pressure <= 0:
        raise ValueError("equation (9) produced an invalid pressure")
    return pressure


def routing_weight(pressure: float) -> float:
    """Evaluate equation (10)."""

    return _nonnegative_finite(pressure, "pressure")
