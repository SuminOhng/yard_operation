"""Immutable view models for static schedule visualization."""

from __future__ import annotations

from dataclasses import dataclass

from ..policy import CooperationPolicy
from ..schedule import OperationPurpose, OperationType


@dataclass(frozen=True, slots=True)
class VisualizationOperation:
    operation_index: int
    crane_id: str
    operation_type: OperationType
    purpose: OperationPurpose
    start_time: float
    end_time: float
    start_bay: int
    start_row: int
    end_bay: int
    end_row: int
    job_id: str | None
    container_id: str | None
    transfer_slot_id: str | None
    transfer_point_kind: str | None
    target_bay: int | None
    target_row: int | None
    target_tier: int | None
    accepted: bool
    crane_load_after: str | None
    container_status_after: str | None
    container_bay_after: int | None
    container_row_after: int | None
    container_tier_after: int | None
    container_transfer_after: str | None

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


@dataclass(frozen=True, slots=True)
class PolicyScheduleVisualization:
    policy: CooperationPolicy
    status: str
    upper_bound_validated: bool
    lower_bound_certified: bool
    best_known_upper_bound: float | None
    combined_lower_bound: float | None
    absolute_gap: float | None
    relative_gap: float | None
    strict_append_upper_bound: float | None
    full_replan_upper_bound: float | None
    upper_bound_method: str | None
    schedule_makespan: float | None
    schedule_valid: bool
    handover_count: int
    reshuffle_count: int
    concurrent_crane_seconds: float
    average_transfer_wait_seconds: float | None
    crane_ids: tuple[str, ...]
    operations: tuple[VisualizationOperation, ...]
    violation_codes: tuple[str, ...]
    error: str | None


@dataclass(frozen=True, slots=True)
class RouteCandidateVisualization:
    route_key: str
    policy: CooperationPolicy
    method: str | None
    valid: bool
    makespan: float | None
    handover_count: int
    operation_count: int
    selected: bool
    error: str | None


@dataclass(frozen=True, slots=True)
class InitialCraneVisualization:
    crane_id: str
    side: str
    bay: int
    row: int
    carrying_container: str | None


@dataclass(frozen=True, slots=True)
class InitialContainerVisualization:
    container_id: str
    status: str
    bay: int | None
    row: int | None
    tier: int | None
    carried_by: str | None
    transfer_slot_id: str | None
    direction: str | None = None


@dataclass(frozen=True, slots=True)
class TransferSlotVisualization:
    slot_id: str
    bay: int
    row: int
    capacity: int
    enabled: bool


@dataclass(frozen=True, slots=True)
class StaticScheduleVisualization:
    instance_id: str
    title: str
    block_id: str
    work_bays: int
    rows: int
    tiers: int
    seaside_parking_bay: int
    landside_parking_bay: int
    handshake_bay: int
    decision_time: float
    existing_job_ids: tuple[str, ...]
    new_job_ids: tuple[str, ...]
    shared_time_horizon: float
    minimum_crane_separation_bays: float
    initial_cranes: tuple[InitialCraneVisualization, ...]
    initial_containers: tuple[InitialContainerVisualization, ...]
    transfer_slots: tuple[TransferSlotVisualization, ...]
    route_candidates: tuple[RouteCandidateVisualization, ...]
    policies: tuple[PolicyScheduleVisualization, ...]
