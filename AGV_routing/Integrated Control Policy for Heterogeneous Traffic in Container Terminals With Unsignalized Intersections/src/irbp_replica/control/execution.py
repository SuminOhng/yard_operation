"""Discrete execution state for one BP/VTR intersection cycle."""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose, isfinite
from typing import Literal

from irbp_replica.control.vtr import TokenSlot
from irbp_replica.domain.models import VehicleKind

ExecutionMode = Literal["ACTIVE", "CLEARANCE", "COMPLETE"]
BoundaryOutcome = Literal[
    "extended",
    "cav_leader",
    "queue_empty",
    "extension_cap_hit",
]


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


def _require_step_multiple(value: float, step_length_s: float, field_name: str) -> None:
    steps = value / step_length_s
    if not isclose(steps, round(steps), rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"{field_name} must be divisible by step_length_s")


@dataclass(frozen=True, slots=True)
class ExecutionSnapshot:
    """Observable controller output for one simulation instant."""

    time_s: float
    mode: ExecutionMode
    active_phase_id: str | None
    token_station_id: str | None
    slot_index: int | None
    time_remaining_s: float
    extension_used_s: float
    cycle_extension_used_s: float
    last_completed_station_id: str
    nominal_service_budget_s: float
    actual_cycle_duration_s: float | None
    boundary_outcome: BoundaryOutcome | None
    boundary_phase_id: str | None
    boundary_station_id: str | None


class VTRCycleExecutor:
    """Execute one Algorithm 2 plan on a deterministic discrete clock.

    ``advance_after_step`` records one already-completed simulation step. Its
    queue leader must therefore come from the post-step state and is evaluated
    only when the activation expires, matching Algorithm 1. Positive clearance
    is a reconstruction safety variant outside equations (6)-(7).
    """

    def __init__(
        self,
        plan: tuple[TokenSlot, ...],
        previous_station_id: str,
        *,
        step_length_s: float,
        extension_increment_s: float,
        maximum_extension_s: float | None = None,
        clearance_time_s: float = 0.0,
    ) -> None:
        if not previous_station_id:
            raise ValueError("previous_station_id must not be empty")
        self._step_length_s = _positive_finite(step_length_s, "step_length_s")
        self._extension_increment_s = _positive_finite(
            extension_increment_s,
            "extension_increment_s",
        )
        self._maximum_extension_s = None
        if maximum_extension_s is not None:
            self._maximum_extension_s = _nonnegative_finite(
                maximum_extension_s,
                "maximum_extension_s",
            )
        self._clearance_time_s = _nonnegative_finite(
            clearance_time_s,
            "clearance_time_s",
        )
        _require_step_multiple(
            self._extension_increment_s,
            self._step_length_s,
            "extension_increment_s",
        )
        _require_step_multiple(
            self._clearance_time_s,
            self._step_length_s,
            "clearance_time_s",
        )

        self._plan = tuple(plan)
        phase_ids = [slot.phase_id for slot in self._plan]
        station_ids = [slot.station_id for slot in self._plan]
        if len(phase_ids) != len(set(phase_ids)):
            raise ValueError("plan phase IDs must be unique")
        if len(station_ids) != len(set(station_ids)):
            raise ValueError("plan station IDs must be unique")
        for slot in self._plan:
            duration = _nonnegative_finite(
                slot.initial_duration_s,
                "initial_duration_s",
            )
            _nonnegative_finite(slot.weight, "weight")
            _require_step_multiple(duration, self._step_length_s, "initial_duration_s")

        self._time_s = 0.0
        self._mode: ExecutionMode = "COMPLETE"
        self._slot_index = -1
        self._elapsed_in_state_s = 0.0
        self._active_target_s = 0.0
        self._extension_used_s = 0.0
        self._cycle_extension_used_s = 0.0
        self._boundary_outcome: BoundaryOutcome | None = None
        self._boundary_phase_id: str | None = None
        self._boundary_station_id: str | None = None
        self._last_completed_station_id = previous_station_id
        self._nominal_service_budget_s = round(
            sum(slot.initial_duration_s for slot in self._plan),
            12,
        )
        self._start_next_slot()

    @property
    def is_complete(self) -> bool:
        return self._mode == "COMPLETE"

    @property
    def last_completed_station_id(self) -> str:
        return self._last_completed_station_id

    @property
    def nominal_service_budget_s(self) -> float:
        return self._nominal_service_budget_s

    @property
    def actual_cycle_duration_s(self) -> float | None:
        if not self.is_complete:
            return None
        return self._time_s

    def snapshot(self) -> ExecutionSnapshot:
        if self._mode == "ACTIVE":
            slot = self._plan[self._slot_index]
            return ExecutionSnapshot(
                time_s=self._time_s,
                mode=self._mode,
                active_phase_id=slot.phase_id,
                token_station_id=slot.station_id,
                slot_index=self._slot_index,
                time_remaining_s=round(
                    self._active_target_s - self._elapsed_in_state_s,
                    12,
                ),
                extension_used_s=self._extension_used_s,
                cycle_extension_used_s=self._cycle_extension_used_s,
                last_completed_station_id=self._last_completed_station_id,
                nominal_service_budget_s=self._nominal_service_budget_s,
                actual_cycle_duration_s=None,
                boundary_outcome=self._boundary_outcome,
                boundary_phase_id=self._boundary_phase_id,
                boundary_station_id=self._boundary_station_id,
            )
        if self._mode == "CLEARANCE":
            remaining = self._clearance_time_s - self._elapsed_in_state_s
            return ExecutionSnapshot(
                time_s=self._time_s,
                mode=self._mode,
                active_phase_id=None,
                token_station_id=None,
                slot_index=None,
                time_remaining_s=round(remaining, 12),
                extension_used_s=self._extension_used_s,
                cycle_extension_used_s=self._cycle_extension_used_s,
                last_completed_station_id=self._last_completed_station_id,
                nominal_service_budget_s=self._nominal_service_budget_s,
                actual_cycle_duration_s=None,
                boundary_outcome=self._boundary_outcome,
                boundary_phase_id=self._boundary_phase_id,
                boundary_station_id=self._boundary_station_id,
            )
        return ExecutionSnapshot(
            time_s=self._time_s,
            mode="COMPLETE",
            active_phase_id=None,
            token_station_id=None,
            slot_index=None,
            time_remaining_s=0.0,
            extension_used_s=0.0,
            cycle_extension_used_s=self._cycle_extension_used_s,
            last_completed_station_id=self._last_completed_station_id,
            nominal_service_budget_s=self._nominal_service_budget_s,
            actual_cycle_duration_s=self._time_s,
            boundary_outcome=self._boundary_outcome,
            boundary_phase_id=self._boundary_phase_id,
            boundary_station_id=self._boundary_station_id,
        )

    def advance_after_step(
        self,
        *,
        post_step_queue_leader: VehicleKind | None,
    ) -> ExecutionSnapshot:
        """Record one simulation step using its post-step queue observation."""

        if self.is_complete:
            raise RuntimeError("cannot advance a completed VTR cycle")
        if post_step_queue_leader not in (None, "CAV", "HDV"):
            raise ValueError(
                "post_step_queue_leader must be 'CAV', 'HDV', or None"
            )

        self._boundary_outcome = None
        self._boundary_phase_id = None
        self._boundary_station_id = None

        self._time_s = round(self._time_s + self._step_length_s, 12)
        self._elapsed_in_state_s = round(
            self._elapsed_in_state_s + self._step_length_s,
            12,
        )

        if self._mode == "ACTIVE" and isclose(
            self._elapsed_in_state_s,
            self._active_target_s,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            boundary_slot = self._plan[self._slot_index]
            self._boundary_phase_id = boundary_slot.phase_id
            self._boundary_station_id = boundary_slot.station_id
            if post_step_queue_leader == "HDV":
                extension_candidate = (
                    self._extension_used_s + self._extension_increment_s
                )
                cap_allows_extension = (
                    self._maximum_extension_s is None
                    or extension_candidate <= self._maximum_extension_s + 1e-12
                )
                if cap_allows_extension:
                    self._extension_used_s = round(extension_candidate, 12)
                    self._cycle_extension_used_s = round(
                        self._cycle_extension_used_s + self._extension_increment_s,
                        12,
                    )
                    self._active_target_s = round(
                        self._active_target_s + self._extension_increment_s,
                        12,
                    )
                    self._boundary_outcome = "extended"
                else:
                    self._boundary_outcome = "extension_cap_hit"
                    self._finish_active_slot()
            else:
                self._boundary_outcome = (
                    "cav_leader"
                    if post_step_queue_leader == "CAV"
                    else "queue_empty"
                )
                self._finish_active_slot()
        elif self._mode == "CLEARANCE" and isclose(
            self._elapsed_in_state_s,
            self._clearance_time_s,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            self._start_next_slot()

        return self.snapshot()

    def _finish_active_slot(self) -> None:
        slot = self._plan[self._slot_index]
        self._last_completed_station_id = slot.station_id
        if self._clearance_time_s > 0:
            self._mode = "CLEARANCE"
            self._elapsed_in_state_s = 0.0
        else:
            self._start_next_slot()

    def _start_next_slot(self) -> None:
        self._slot_index += 1
        while self._slot_index < len(self._plan):
            slot = self._plan[self._slot_index]
            if slot.initial_duration_s > 0:
                self._mode = "ACTIVE"
                self._elapsed_in_state_s = 0.0
                self._active_target_s = slot.initial_duration_s
                self._extension_used_s = 0.0
                return
            self._slot_index += 1
        self._mode = "COMPLETE"
        self._elapsed_in_state_s = 0.0
        self._active_target_s = 0.0
        self._extension_used_s = 0.0
