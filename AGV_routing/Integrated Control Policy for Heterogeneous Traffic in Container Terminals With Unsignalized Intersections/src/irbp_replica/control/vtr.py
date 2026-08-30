"""Algorithm 2 virtual-token ordering and cycle-plan construction."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import isfinite

from irbp_replica.control.phase_time import allocate_phase_durations
from irbp_replica.control.pressure import compute_phase_weight
from irbp_replica.domain.models import PhaseState, RoadState


@dataclass(frozen=True, slots=True)
class TokenSlot:
    """One station entry in Algorithm 2 output lists S* and T*."""

    phase_id: str
    station_id: str
    weight: float
    initial_duration_s: float
    head_is_hdv: bool


def _validate_phases(phases: Sequence[PhaseState]) -> tuple[PhaseState, ...]:
    phases = tuple(phases)
    if not phases:
        raise ValueError("phases must not be empty")
    phase_ids = [phase.phase_id for phase in phases]
    station_ids = [phase.station_id for phase in phases]
    indexes = [phase.clockwise_index for phase in phases]
    if len(set(phase_ids)) != len(phase_ids):
        raise ValueError("phase IDs must be unique")
    if len(set(station_ids)) != len(station_ids):
        raise ValueError("station IDs must be unique")
    if len(set(indexes)) != len(indexes):
        raise ValueError("clockwise indexes must be unique")
    return phases


def clockwise_phases_after(
    phases: Sequence[PhaseState],
    last_station_id: str,
) -> tuple[PhaseState, ...]:
    """Return one clockwise ring traversal beginning after the last holder."""

    phases = _validate_phases(phases)
    clockwise = tuple(sorted(phases, key=lambda phase: phase.clockwise_index))
    try:
        last_index = next(
            index
            for index, phase in enumerate(clockwise)
            if phase.station_id == last_station_id
        )
    except StopIteration as exc:
        raise ValueError(f"unknown last_station_id: {last_station_id}") from exc
    return clockwise[last_index + 1 :] + clockwise[: last_index + 1]


def order_token_stations(
    phases: Sequence[PhaseState],
    weights: Mapping[str, float],
    last_station_id: str,
) -> tuple[str, ...]:
    """Order stations using the deterministic reconstruction of Algorithm 2."""

    phases = _validate_phases(phases)
    phase_ids = {phase.phase_id for phase in phases}
    if set(weights) != phase_ids:
        raise ValueError("weights must contain exactly one value for every phase")
    clean_weights: dict[str, float] = {}
    for phase_id, value in weights.items():
        value = float(value)
        if not isfinite(value) or value < 0:
            raise ValueError("weights must be finite and non-negative")
        clean_weights[phase_id] = value

    clockwise = clockwise_phases_after(phases, last_station_id)
    clockwise_rank = {
        phase.station_id: index for index, phase in enumerate(clockwise)
    }
    hdv_priority = [phase for phase in clockwise if phase.head_is_hdv]
    remaining = [
        phase
        for phase in clockwise
        if not phase.head_is_hdv and clean_weights[phase.phase_id] > 0
    ]
    remaining.sort(
        key=lambda phase: (
            -clean_weights[phase.phase_id],
            clockwise_rank[phase.station_id],
        )
    )
    return tuple(phase.station_id for phase in hdv_priority + remaining)


def build_cycle_plan(
    phases: Sequence[PhaseState],
    roads: Mapping[str, RoadState],
    last_station_id: str,
    cycle_length_s: float,
    resolution_s: float = 1.0,
) -> tuple[TokenSlot, ...]:
    """Evaluate equations (3)-(5) and Algorithm 2 for one intersection."""

    phases = _validate_phases(phases)
    weights = {
        phase.phase_id: compute_phase_weight(phase, roads) for phase in phases
    }
    durations = allocate_phase_durations(weights, cycle_length_s, resolution_s)
    station_order = order_token_stations(phases, weights, last_station_id)
    phase_by_station = {phase.station_id: phase for phase in phases}
    return tuple(
        TokenSlot(
            phase_id=phase_by_station[station_id].phase_id,
            station_id=station_id,
            weight=weights[phase_by_station[station_id].phase_id],
            initial_duration_s=durations[phase_by_station[station_id].phase_id],
            head_is_hdv=phase_by_station[station_id].head_is_hdv,
        )
        for station_id in station_order
    )


def validate_single_activation(
    phases: Sequence[PhaseState],
    active_phase_ids: Iterable[str],
    token_station_ids: Iterable[str],
) -> None:
    """Enforce equations (6)-(7) and phase/station correspondence."""

    phases = _validate_phases(phases)
    active_phase_ids = tuple(active_phase_ids)
    token_station_ids = tuple(token_station_ids)
    if len(active_phase_ids) != 1:
        raise ValueError("exactly one phase must be active")
    if len(token_station_ids) != 1:
        raise ValueError("exactly one station must hold the token")
    phase_by_id = {phase.phase_id: phase for phase in phases}
    active_phase_id = active_phase_ids[0]
    if active_phase_id not in phase_by_id:
        raise ValueError(f"unknown active phase: {active_phase_id}")
    expected_station = phase_by_id[active_phase_id].station_id
    if token_station_ids[0] != expected_station:
        raise ValueError("active phase and token-holding station do not correspond")
