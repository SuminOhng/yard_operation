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


def _validated_weights(
    weights: Mapping[str, float],
) -> tuple[tuple[str, ...], tuple[float, ...]]:
    phase_ids = tuple(weights)
    clean_weights: list[float] = []
    for phase_id in phase_ids:
        if not phase_id:
            raise ValueError("weight keys must not be empty")
        weight = float(weights[phase_id])
        if not isfinite(weight) or weight < 0:
            raise ValueError("weights must be finite and non-negative")
        clean_weights.append(weight)
    return phase_ids, tuple(clean_weights)


def compute_proportional_phase_durations(
    weights: Mapping[str, float],
    cycle_length_s: float,
) -> dict[str, float]:
    """Calculate the continuous equation (5) phase durations."""

    cycle = _positive_finite(cycle_length_s, "cycle_length_s")
    phase_ids, clean_weights = _validated_weights(weights)
    total_weight = sum(clean_weights)
    if total_weight == 0:
        return {phase_id: 0.0 for phase_id in phase_ids}
    return {
        phase_id: clean_weights[index] * cycle / total_weight
        for index, phase_id in enumerate(phase_ids)
    }


def allocate_phase_durations(
    weights: Mapping[str, float],
    cycle_length_s: float,
    resolution_s: float = 1.0,
) -> dict[str, float]:
    """Quantize equation (5) durations with a positive-phase lower bound.

    Every positive-weight phase receives at least one simulation step. Stable
    largest-remainder allocation is applied subject to that lower bound, with
    mapping insertion order resolving equal remainders. The cycle must contain
    a whole number of steps.
    """

    cycle = _positive_finite(cycle_length_s, "cycle_length_s")
    resolution = _positive_finite(resolution_s, "resolution_s")
    step_count_float = cycle / resolution
    step_count = round(step_count_float)
    if not isclose(step_count_float, step_count, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("cycle_length_s must be divisible by resolution_s")

    phase_ids, clean_weights = _validated_weights(weights)

    total_weight = sum(clean_weights)
    if total_weight == 0:
        return {phase_id: 0.0 for phase_id in phase_ids}

    positive_indexes = [
        index for index, weight in enumerate(clean_weights) if weight > 0
    ]
    if len(positive_indexes) > step_count:
        raise ValueError(
            "cycle_length_s provides fewer steps than positive-weight phases"
        )

    raw_steps = [weight * step_count / total_weight for weight in clean_weights]
    allocated_steps = [0 for _ in phase_ids]
    for index in positive_indexes:
        allocated_steps[index] = max(1, floor(raw_steps[index]))

    remaining_steps = step_count - sum(allocated_steps)
    if remaining_steps > 0:
        remainder_order = sorted(
            positive_indexes,
            key=lambda index: (
                -round(raw_steps[index] - floor(raw_steps[index]), 12),
                index,
            ),
        )
        for index in remainder_order[:remaining_steps]:
            allocated_steps[index] += 1
    elif remaining_steps < 0:
        for _ in range(-remaining_steps):
            removable_indexes = [
                index for index in positive_indexes if allocated_steps[index] > 1
            ]
            index = min(
                removable_indexes,
                key=lambda candidate: (
                    round(
                        (allocated_steps[candidate] - 1 - raw_steps[candidate]) ** 2
                        - (allocated_steps[candidate] - raw_steps[candidate]) ** 2,
                        12,
                    ),
                    candidate,
                ),
            )
            allocated_steps[index] -= 1

    return {
        phase_id: round(allocated_steps[index] * resolution, 12)
        for index, phase_id in enumerate(phase_ids)
    }


def extend_phase_for_hdv(
    initial_duration_s: float,
    leader_observations: Iterable[VehicleKind | None],
    increment_s: float,
    maximum_extension_s: float | None = None,
) -> float:
    """Apply Algorithm 1 to observations made at extension boundaries.

    Each consecutive ``"HDV"`` observation grants one increment. ``"CAV"``
    means a CAV leads the queue and ``None`` means the queue is empty. A finite
    observation stream must reach a stop condition; exhaustion after an HDV is
    not a completed Algorithm 1 result.
    """

    initial = float(initial_duration_s)
    if not isfinite(initial) or initial < 0:
        raise ValueError("initial_duration_s must be finite and non-negative")
    increment = _positive_finite(increment_s, "increment_s")
    maximum_extension = None
    if maximum_extension_s is not None:
        maximum_extension = float(maximum_extension_s)
        if not isfinite(maximum_extension) or maximum_extension < 0:
            raise ValueError("maximum_extension_s must be finite and non-negative")

    extension = 0.0
    for leader in leader_observations:
        if leader not in (None, "CAV", "HDV"):
            raise ValueError("leader observations must be 'CAV', 'HDV', or None")
        if leader != "HDV":
            break
        if (
            maximum_extension is not None
            and extension + increment > maximum_extension + 1e-12
        ):
            break
        extension += increment
    else:
        raise RuntimeError(
            "leader observations ended before Algorithm 1 terminated"
        )

    return round(initial + extension, 12)
