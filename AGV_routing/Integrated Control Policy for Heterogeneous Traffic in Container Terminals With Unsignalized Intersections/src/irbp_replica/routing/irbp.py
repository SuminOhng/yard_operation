"""Distance-constrained IR-BP routing for equations (11), (16), and (17)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Literal

from irbp_replica.domain.models import (
    RoutingCandidateState,
    VehicleRoutingState,
    VehicleState,
)
from irbp_replica.routing.distance import (
    a_star_cost,
    comparison_tolerance,
    distance_mask,
    euclidean_distance_m,
    minimum_distance_cost,
    relaxed_distance_cost,
)
from irbp_replica.routing.travel_time import (
    evaluate_candidate_travel_time,
    routing_pressure,
    routing_weight,
)


class NoRouteError(RuntimeError):
    """Raised when Algorithm 3 has no legal destination-reachable road."""

    def __init__(
        self,
        message: str,
        *,
        scores: Sequence[CandidateRoutingScore] = (),
    ) -> None:
        super().__init__(message)
        self.scores = tuple(scores)


CandidateRoutingStatus = Literal[
    "eligible",
    "distance_ineligible",
    "illegal",
    "destination_unreachable",
    "illegal_and_destination_unreachable",
]


@dataclass(frozen=True, slots=True)
class CandidateRoutingScore:
    """Traceable precheck and mathematical evaluation of one road."""

    edge_id: str
    status: CandidateRoutingStatus
    exclusion_reason: str | None
    controlling_vehicle_id: str | None
    travel_time_s: float | None
    pressure_weight_mps: float | None
    g_cost_m: float | None
    h_cost_m: float | None
    distance_cost_m: float | None
    detour_excess_m: float | None
    eligibility_mask: int
    masked_weight_mps: float

    @property
    def eligible(self) -> bool:
        """Whether equation (15) admitted this candidate."""

        return self.eligibility_mask == 1


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Pure Algorithm 3 result; caller commits eta after route mutation succeeds."""

    vehicle_id: str
    selected_edge_id: str
    eta_before_m: float
    updated_eta_m: float
    minimum_distance_cost_m: float
    relaxed_distance_cost_m: float
    scores: tuple[CandidateRoutingScore, ...]


def _nonnegative_finite(value: float, field_name: str) -> float:
    value = float(value)
    if not isfinite(value) or value < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return value


def _precheck_exclusion_score(
    candidate: RoutingCandidateState,
) -> CandidateRoutingScore | None:
    """Trace a topology precheck exclusion outside equations (8)-(17)."""

    if candidate.is_legal and candidate.destination_reachable:
        return None
    if not candidate.is_legal and not candidate.destination_reachable:
        status: CandidateRoutingStatus = (
            "illegal_and_destination_unreachable"
        )
        reason = "candidate_is_not_legal_and_destination_is_not_reachable"
    elif not candidate.is_legal:
        status = "illegal"
        reason = "candidate_is_not_legal"
    else:
        status = "destination_unreachable"
        reason = "destination_is_not_reachable"
    return CandidateRoutingScore(
        edge_id=candidate.edge_id,
        status=status,
        exclusion_reason=reason,
        controlling_vehicle_id=None,
        travel_time_s=None,
        pressure_weight_mps=None,
        g_cost_m=None,
        h_cost_m=None,
        distance_cost_m=None,
        detour_excess_m=None,
        eligibility_mask=0,
        masked_weight_mps=0.0,
    )


def select_unconstrained_edge(
    weights: Mapping[str, float],
    *,
    absolute_tolerance_mps: float = 1e-12,
    relative_tolerance: float = 1e-12,
) -> str:
    """Evaluate equation (11) with a stable edge-ID tie rule."""

    if not weights:
        raise NoRouteError("weights must not be empty")
    clean_weights: dict[str, float] = {}
    for edge_id, value in weights.items():
        if not edge_id:
            raise ValueError("weight keys must not be empty")
        clean_weights[edge_id] = _nonnegative_finite(value, "routing weight")

    maximum_weight = max(clean_weights.values())
    tied_edges = []
    for edge_id, weight in clean_weights.items():
        tolerance = comparison_tolerance(
            maximum_weight,
            weight,
            absolute_tolerance=absolute_tolerance_mps,
            relative_tolerance=relative_tolerance,
        )
        if maximum_weight - weight <= tolerance:
            tied_edges.append(edge_id)
    return min(tied_edges)


def update_eta(
    eta_m: float,
    selected_cost_m: float,
    minimum_cost_m: float,
    *,
    absolute_tolerance_m: float = 1e-9,
    relative_tolerance: float = 1e-12,
) -> float:
    """Evaluate equation (17)."""

    eta = _nonnegative_finite(eta_m, "eta_m")
    selected_cost = _nonnegative_finite(selected_cost_m, "selected_cost_m")
    minimum_cost = _nonnegative_finite(minimum_cost_m, "minimum_cost_m")
    tolerance = comparison_tolerance(
        selected_cost,
        minimum_cost,
        absolute_tolerance=absolute_tolerance_m,
        relative_tolerance=relative_tolerance,
    )
    if selected_cost < minimum_cost - tolerance:
        raise ValueError("selected_cost_m must not be less than minimum_cost_m")
    detour_excess = max(selected_cost - minimum_cost, 0.0)
    return max(eta - detour_excess, 0.0)


def select_next_edge(
    cav: VehicleState,
    trip: VehicleRoutingState,
    candidates: Sequence[RoutingCandidateState],
    *,
    empty_road_speed_mps: float,
    speed_floor_mps: float,
    position_absolute_tolerance_m: float = 1e-9,
    cost_absolute_tolerance_m: float = 1e-9,
    pressure_absolute_tolerance_mps: float = 1e-12,
    relative_tolerance: float = 1e-12,
) -> RoutingDecision:
    """Reconstruct ``R_ij``, then evaluate Algorithm 3 without mutation.

    Legality and reachability flags form a defensive topology precheck outside
    equations (8)-(17). A live adapter should normally supply only valid
    members of ``R_ij``; excluded discoveries remain visible in the trace.
    """

    if cav.vehicle_kind != "CAV":
        raise ValueError("Algorithm 3 requires a CAV")
    if cav.vehicle_id != trip.vehicle_id:
        raise ValueError("cav and trip vehicle IDs must match")
    if cav.destination_edge_id != trip.destination_edge_id:
        raise ValueError("cav and trip destination edge IDs must match")
    position_tolerance = _nonnegative_finite(
        position_absolute_tolerance_m,
        "position_absolute_tolerance_m",
    )
    cost_tolerance = _nonnegative_finite(
        cost_absolute_tolerance_m,
        "cost_absolute_tolerance_m",
    )
    pressure_tolerance = _nonnegative_finite(
        pressure_absolute_tolerance_mps,
        "pressure_absolute_tolerance_mps",
    )
    relative = _nonnegative_finite(relative_tolerance, "relative_tolerance")

    candidates = tuple(candidates)
    edge_ids = [candidate.edge_id for candidate in candidates]
    if len(edge_ids) != len(set(edge_ids)):
        raise ValueError("candidate edge IDs must be unique")
    ordered_candidates = tuple(
        sorted(candidates, key=lambda candidate: candidate.edge_id)
    )
    usable_candidates = tuple(
        candidate
        for candidate in ordered_candidates
        if candidate.is_legal and candidate.destination_reachable
    )
    if not usable_candidates:
        scores = tuple(
            score
            for candidate in ordered_candidates
            if (score := _precheck_exclusion_score(candidate)) is not None
        )
        raise NoRouteError(
            "no legal destination-reachable candidate road",
            scores=scores,
        )

    travel_times: dict[str, float] = {}
    controlling_vehicle_ids: dict[str, str | None] = {}
    weights: dict[str, float] = {}
    full_costs: dict[str, float] = {}
    local_costs: dict[str, float] = {}
    g_costs: dict[str, float] = {}
    h_costs: dict[str, float] = {}
    for candidate in usable_candidates:
        estimate = evaluate_candidate_travel_time(
            cav,
            candidate,
            empty_road_speed_mps=empty_road_speed_mps,
            speed_floor_mps=speed_floor_mps,
            distance_tolerance_m=position_tolerance,
        )
        travel_time = estimate.travel_time_s
        pressure = routing_pressure(candidate.length_m, travel_time)
        weight = routing_weight(pressure)
        heuristic = euclidean_distance_m(
            candidate.downstream_position_m,
            trip.destination_position_m,
        )
        local_cost = a_star_cost(candidate.length_m, heuristic)
        full_cost = a_star_cost(
            trip.distance_travelled_m + candidate.length_m,
            heuristic,
        )
        g_costs[candidate.edge_id] = (
            trip.distance_travelled_m + candidate.length_m
        )
        h_costs[candidate.edge_id] = heuristic
        local_costs[candidate.edge_id] = local_cost
        full_costs[candidate.edge_id] = full_cost
        travel_times[candidate.edge_id] = travel_time
        controlling_vehicle_ids[candidate.edge_id] = (
            estimate.controlling_vehicle_id
        )
        weights[candidate.edge_id] = weight

    minimum_local_cost = minimum_distance_cost(local_costs)
    minimum_full_cost = minimum_distance_cost(full_costs)
    relaxed_full_cost = relaxed_distance_cost(
        minimum_full_cost,
        trip.eta_remaining_m,
    )

    scores: list[CandidateRoutingScore] = []
    eligible_weights: dict[str, float] = {}
    for candidate in ordered_candidates:
        edge_id = candidate.edge_id
        precheck_score = _precheck_exclusion_score(candidate)
        if precheck_score is not None:
            scores.append(precheck_score)
            continue
        weight = weights[edge_id]
        detour_excess = max(local_costs[edge_id] - minimum_local_cost, 0.0)
        eligibility_mask = distance_mask(
            detour_excess,
            trip.eta_remaining_m,
            absolute_tolerance_m=cost_tolerance,
            relative_tolerance=relative,
        )
        eligible = bool(eligibility_mask)
        masked_weight = weight if eligible else 0.0
        scores.append(
            CandidateRoutingScore(
                edge_id=edge_id,
                status="eligible" if eligible else "distance_ineligible",
                exclusion_reason=None if eligible else "detour_exceeds_eta",
                controlling_vehicle_id=controlling_vehicle_ids[edge_id],
                travel_time_s=travel_times[edge_id],
                pressure_weight_mps=weight,
                g_cost_m=g_costs[edge_id],
                h_cost_m=h_costs[edge_id],
                distance_cost_m=full_costs[edge_id],
                detour_excess_m=detour_excess,
                eligibility_mask=eligibility_mask,
                masked_weight_mps=masked_weight,
            )
        )
        if eligible:
            eligible_weights[edge_id] = weight

    if not eligible_weights:
        raise RuntimeError("equation (15) left no eligible candidate")
    selected_edge_id = select_unconstrained_edge(
        eligible_weights,
        absolute_tolerance_mps=pressure_tolerance,
        relative_tolerance=relative,
    )
    updated_eta = update_eta(
        trip.eta_remaining_m,
        local_costs[selected_edge_id],
        minimum_local_cost,
        absolute_tolerance_m=cost_tolerance,
        relative_tolerance=relative,
    )
    return RoutingDecision(
        vehicle_id=cav.vehicle_id,
        selected_edge_id=selected_edge_id,
        eta_before_m=trip.eta_remaining_m,
        updated_eta_m=updated_eta,
        minimum_distance_cost_m=minimum_full_cost,
        relaxed_distance_cost_m=relaxed_full_cost,
        scores=tuple(scores),
    )
