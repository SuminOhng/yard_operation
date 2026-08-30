"""Distance constraints for IR-BP equations (12)-(15)."""

from __future__ import annotations

from collections.abc import Mapping
from math import hypot, isfinite

from irbp_replica.domain.models import PositionM


def _nonnegative_finite(value: float, field_name: str) -> float:
    value = float(value)
    if not isfinite(value) or value < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return value


def _position(value: PositionM, field_name: str) -> PositionM:
    try:
        coordinates = tuple(value)
    except TypeError as exc:
        raise ValueError(f"{field_name} must contain two coordinates") from exc
    if len(coordinates) != 2:
        raise ValueError(f"{field_name} must contain two coordinates")
    x_m, y_m = (float(coordinate) for coordinate in coordinates)
    if not isfinite(x_m) or not isfinite(y_m):
        raise ValueError(f"{field_name} coordinates must be finite")
    return (x_m, y_m)


def comparison_tolerance(
    first: float,
    second: float,
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> float:
    """Return one deterministic absolute tolerance for a comparison."""

    first = _nonnegative_finite(first, "first")
    second = _nonnegative_finite(second, "second")
    absolute = _nonnegative_finite(absolute_tolerance, "absolute_tolerance")
    relative = _nonnegative_finite(relative_tolerance, "relative_tolerance")
    tolerance = max(absolute, relative * max(first, second, 1.0))
    if not isfinite(tolerance):
        raise ValueError("comparison tolerance must be finite")
    return tolerance


def euclidean_distance_m(start_m: PositionM, end_m: PositionM) -> float:
    """Calculate the Euclidean heuristic used by equation (12)."""

    start_x, start_y = _position(start_m, "start_m")
    end_x, end_y = _position(end_m, "end_m")
    return hypot(end_x - start_x, end_y - start_y)


def a_star_cost(cumulative_distance_m: float, heuristic_distance_m: float) -> float:
    """Evaluate equation (12)."""

    cumulative = _nonnegative_finite(
        cumulative_distance_m,
        "cumulative_distance_m",
    )
    heuristic = _nonnegative_finite(
        heuristic_distance_m,
        "heuristic_distance_m",
    )
    cost = cumulative + heuristic
    if not isfinite(cost):
        raise ValueError("equation (12) produced a non-finite cost")
    return cost


def minimum_distance_cost(costs: Mapping[str, float]) -> float:
    """Evaluate equation (13)."""

    if not costs:
        raise ValueError("costs must not be empty")
    clean_costs: list[float] = []
    for edge_id, value in costs.items():
        if not edge_id:
            raise ValueError("cost keys must not be empty")
        clean_costs.append(_nonnegative_finite(value, "distance cost"))
    return min(clean_costs)


def relaxed_distance_cost(minimum_cost_m: float, eta_m: float) -> float:
    """Evaluate equation (14)."""

    minimum_cost = _nonnegative_finite(minimum_cost_m, "minimum_cost_m")
    eta = _nonnegative_finite(eta_m, "eta_m")
    relaxed = minimum_cost + eta
    if not isfinite(relaxed):
        raise ValueError("equation (14) produced a non-finite cost")
    return relaxed


def distance_mask(
    cost_m: float,
    relaxed_cost_m: float,
    *,
    absolute_tolerance_m: float = 1e-9,
    relative_tolerance: float = 1e-12,
) -> int:
    """Evaluate equation (15) with a declared floating-point tolerance."""

    cost = _nonnegative_finite(cost_m, "cost_m")
    relaxed = _nonnegative_finite(relaxed_cost_m, "relaxed_cost_m")
    tolerance = comparison_tolerance(
        cost,
        relaxed,
        absolute_tolerance=absolute_tolerance_m,
        relative_tolerance=relative_tolerance,
    )
    return int(cost <= relaxed + tolerance)
