"""Equation (5) duration allocation and Algorithm 1 HDV extension."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from math import floor, isclose, isfinite

from irbp_replica.domain.models import VehicleKind


def _positive_finite(value: float, field_name: str) -> float:
    value = float(value)
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{field_name} must be finite and greater than zero")
    return value


def allocate_phase_durations(
    weights: Mapping[str, float],
    cycle_length_s: float,
    resolution_s: float = 1.0,
) -> dict[str, float]:
    """Allocate equation (5) durations with stable largest-remainder rounding.

    Mapping insertion order resolves equal fractional remainders. The configured
    cycle must contain a whole number of resolution steps.
    """

    cycle = _positive_finite(cycle_length_s, "cycle_length_s")
    resolution = _positive_finite(resolution_s, "resolution_s")
    step_count_float = cycle / resolution
    step_count = round(step_count_float)
    if not isclose(step_count_float, step_count, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("cycle_length_s must be divisible by resolution_s")

    phase_ids = tuple(weights)
    clean_weights: list[float] = []
    for phase_id in phase_ids:
        if not phase_id:
            raise ValueError("weight keys must not be empty")
        weight = float(weights[phase_id])
        if not isfinite(weight) or weight < 0:
            raise ValueError("weights must be finite and non-negative")
        clean_weights.append(weight)

    total_weight = sum(clean_weights)
    if total_weight == 0:
        return {phase_id: 0.0 for phase_id in phase_ids}

    raw_steps = [weight * step_count / total_weight for weight in clean_weights]
    allocated_steps = [floor(value) for value in raw_steps]
    remaining_steps = step_count - sum(allocated_steps)
    remainder_order = sorted(
        range(len(phase_ids)),
        key=lambda index: (-(raw_steps[index] - allocated_steps[index]), index),
    )
    for index in remainder_order[:remaining_steps]:
        allocated_steps[index] += 1

    return {
        phase_id: round(allocated_steps[index] * resolution, 12)
        for index, phase_id in enumerate(phase_ids)
    }


def extend_phase_for_hdv(
    initial_duration_s: float,
    leader_observations: Iterable[VehicleKind | None],
    increment_s: float,
    maximum_extension_s: float,
) -> float:
    """Apply Algorithm 1 to observations made at extension boundaries.

    Each consecutive ``"HDV"`` observation grants one increment. ``"CAV"``
    means a CAV leads the queue and ``None`` means the queue is empty.
    """

    initial = float(initial_duration_s)
    maximum_extension = float(maximum_extension_s)
    if not isfinite(initial) or initial < 0:
        raise ValueError("initial_duration_s must be finite and non-negative")
    increment = _positive_finite(increment_s, "increment_s")
    if not isfinite(maximum_extension) or maximum_extension < 0:
        raise ValueError("maximum_extension_s must be finite and non-negative")

    extension = 0.0
    for leader in leader_observations:
        if leader not in (None, "CAV", "HDV"):
            raise ValueError("leader observations must be 'CAV', 'HDV', or None")
        if leader != "HDV":
            break
        if extension + increment > maximum_extension + 1e-12:
            break
        extension += increment

    return round(initial + extension, 12)
