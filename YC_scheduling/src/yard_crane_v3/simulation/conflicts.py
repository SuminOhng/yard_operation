"""Structured continuous twin-crane separation conflicts."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..model import CraneSide, StaticSchedulingInstance
from ..schedule import CandidateSchedule, ScheduledOperation


TOL = 1e-9


@dataclass(frozen=True, slots=True)
class CraneConflict:
    """One piecewise-linear interval that violates crane separation."""

    onset_time: float
    witness_time: float
    interval_start: float
    interval_end: float
    seaside_crane_id: str
    landside_crane_id: str
    seaside_operation_index: int | None
    landside_operation_index: int | None
    seaside_bay: float
    landside_bay: float
    actual_separation: float
    required_separation: float
    violation_amount: float


def detect_crane_conflicts(
    instance: StaticSchedulingInstance,
    schedule: CandidateSchedule,
) -> tuple[CraneConflict, ...]:
    """Return every violating linear time interval in chronological order."""

    sides = {crane.side: crane for crane in instance.cranes}
    if set(sides) != set(CraneSide):
        return ()
    sea = sides[CraneSide.SEASIDE]
    land = sides[CraneSide.LANDSIDE]
    indexed = tuple(enumerate(schedule.operations))
    sea_ops = tuple(
        sorted(
            (
                (index, operation)
                for index, operation in indexed
                if operation.crane_id == sea.id
            ),
            key=lambda item: (
                item[1].start_time,
                item[1].end_time,
                item[0],
            ),
        )
    )
    land_ops = tuple(
        sorted(
            (
                (index, operation)
                for index, operation in indexed
                if operation.crane_id == land.id
            ),
            key=lambda item: (
                item[1].start_time,
                item[1].end_time,
                item[0],
            ),
        )
    )
    times = sorted(
        {instance.initial_state.current_time}
        | {
            time
            for operation in schedule.operations
            for time in (operation.start_time, operation.end_time)
            if math.isfinite(time)
        }
    )
    if not times:
        return ()

    required = instance.physical_rules.minimum_crane_separation_bays
    conflicts: list[CraneConflict] = []
    intervals = list(zip(times, times[1:]))
    if not intervals:
        intervals.append((times[-1], times[-1]))
    for start, end in intervals:
        sea_start = _bay_at(sea.initial_position.bay, sea_ops, start)
        land_start = _bay_at(land.initial_position.bay, land_ops, start)
        separation_start = land_start - sea_start
        sea_end = _bay_at(sea.initial_position.bay, sea_ops, end)
        land_end = _bay_at(land.initial_position.bay, land_ops, end)
        separation_end = land_end - sea_end

        if separation_start < required - TOL:
            onset = start
        elif separation_end < required - TOL and end > start + TOL:
            change = separation_end - separation_start
            if change >= -TOL:
                continue
            fraction = (required - separation_start) / change
            fraction = min(1.0, max(0.0, fraction))
            onset = start + fraction * (end - start)
        else:
            continue

        if separation_end <= separation_start:
            witness = end
            sea_bay = sea_end
            land_bay = land_end
            actual = separation_end
        else:
            witness = start
            sea_bay = sea_start
            land_bay = land_start
            actual = separation_start
        sea_index = _active_operation_index(sea_ops, witness)
        land_index = _active_operation_index(land_ops, witness)
        conflicts.append(
            CraneConflict(
                onset_time=onset,
                witness_time=witness,
                interval_start=start,
                interval_end=end,
                seaside_crane_id=sea.id,
                landside_crane_id=land.id,
                seaside_operation_index=sea_index,
                landside_operation_index=land_index,
                seaside_bay=sea_bay,
                landside_bay=land_bay,
                actual_separation=actual,
                required_separation=required,
                violation_amount=max(0.0, required - actual),
            )
        )
    return tuple(conflicts)


def first_crane_conflict(
    instance: StaticSchedulingInstance,
    schedule: CandidateSchedule,
) -> CraneConflict | None:
    conflicts = detect_crane_conflicts(instance, schedule)
    return conflicts[0] if conflicts else None


def _bay_at(
    initial_bay: int,
    indexed_operations: tuple[tuple[int, ScheduledOperation], ...],
    time: float,
) -> float:
    previous_bay = initial_bay
    for _, operation in indexed_operations:
        if time < operation.start_time - TOL:
            return float(previous_bay)
        if time <= operation.end_time + TOL:
            duration = operation.end_time - operation.start_time
            if duration <= TOL:
                return float(operation.end_position.bay)
            fraction = min(
                1.0,
                max(0.0, (time - operation.start_time) / duration),
            )
            return operation.start_position.bay + fraction * (
                operation.end_position.bay - operation.start_position.bay
            )
        previous_bay = operation.end_position.bay
    return float(previous_bay)


def _active_operation_index(
    indexed_operations: tuple[tuple[int, ScheduledOperation], ...],
    time: float,
) -> int | None:
    for index, operation in indexed_operations:
        if (
            operation.start_time - TOL
            <= time
            <= operation.end_time + TOL
        ):
            return index
    return None
