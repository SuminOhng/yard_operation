"""Job ordering and handshake-slot decisions for the 2017-style planner."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ...model import (
    CraneSide,
    Job,
    MoveDirection,
    Position,
    StaticSchedulingInstance,
    TransferSlotSpec,
)
from ...schedule import CandidateSchedule
from ...timing import TimeModel
from ...validator import ValidationResult
from ..common import PlannerInfeasibleError
from ..handshake_area.scheduler import _integer_separation
from ..no_sharing import JobRegion, classify_job
from .paper_timing import (
    BypassRecord,
    MovementTableEntry,
    RequestLeg,
    SchedulingProfile,
    WaitRecord,
)


@dataclass(frozen=True, slots=True)
class Handshake2017CandidateEvaluation:
    label: str
    schedule: CandidateSchedule | None
    validation: ValidationResult | None
    error: str | None = None
    blocking_seconds: float | None = None
    conflict_repairs: int = 0
    movement_table: tuple[MovementTableEntry, ...] = ()
    wait_records: tuple[WaitRecord, ...] = ()
    request_legs: tuple[RequestLeg, ...] = ()
    profile: SchedulingProfile = SchedulingProfile.CURRENT_YARD
    job_order: tuple[str, ...] = ()
    bypass_records: tuple[BypassRecord, ...] = ()
    fallback_used: bool = False
    experimental_makespan: float | None = None
    attempted_bypass_records: tuple[BypassRecord, ...] = ()

    @property
    def valid(self) -> bool:
        return self.validation is not None and self.validation.valid

    @property
    def makespan(self) -> float | None:
        return self.validation.makespan if self.validation is not None else None

    @property
    def handover_count(self) -> int:
        return self.validation.handover_count if self.validation is not None else 0


class SchedulingHeuristic(str, Enum):
    FCFS = "FCFS"
    NN = "NN"
    TWO_OPT = "2_OPT"


class HandshakeStorageRule(str, Enum):
    NEAR_IO = "NEAR_IO"
    NEAR_REQUEST = "NEAR_REQUEST"


def _fcfs_order(
    instance: StaticSchedulingInstance,
    profile: SchedulingProfile,
) -> tuple[Job, ...]:
    if profile is not SchedulingProfile.CURRENT_YARD:
        return instance.jobs
    input_index = {job.id: index for index, job in enumerate(instance.jobs)}
    return tuple(
        sorted(
            instance.jobs,
            key=lambda job: (job.ready_time, input_index[job.id]),
        )
    )


def _nearest_neighbor_order(
    instance: StaticSchedulingInstance,
    timing: TimeModel,
    storage_rule: HandshakeStorageRule,
    profile: SchedulingProfile,
) -> tuple[Job, ...]:
    """Build the paper's priority-crane full movement-table order."""

    cranes = {crane.side: crane for crane in instance.cranes}
    transfer_by_job = {
        job.id: _choose_transfer_slot(
            instance,
            timing,
            job,
            storage_rule,
            profile,
        )
        for job in instance.jobs
        if classify_job(instance, job) is JobRegion.CROSS_REGION
    }
    sequences: dict[CraneSide, tuple[Job, ...]] = {}
    solo_times: dict[CraneSide, float] = {}
    for side in CraneSide:
        jobs = tuple(job for job in instance.jobs if _job_uses_side(instance, job, side))
        sequence = _nn_sequence(
            instance,
            timing,
            side,
            jobs,
            cranes[side].initial_position,
            transfer_by_job,
            profile,
        )
        sequences[side] = sequence
        solo_times[side] = _solo_completion_time(
            instance,
            timing,
            side,
            sequence,
            transfer_by_job,
            profile,
        )

    priority = max(
        CraneSide,
        key=lambda side: (solo_times[side], side is CraneSide.SEASIDE),
    )
    non_priority = (
        CraneSide.LANDSIDE if priority is CraneSide.SEASIDE else CraneSide.SEASIDE
    )

    ordered = list(sequences[priority])
    already_added = {job.id for job in ordered}
    ordered.extend(
        job
        for job in sequences[non_priority]
        if job.id not in already_added
        and classify_job(instance, job) is not JobRegion.CROSS_REGION
    )
    return tuple(ordered)


def _nn_sequence(
    instance: StaticSchedulingInstance,
    timing: TimeModel,
    side: CraneSide,
    jobs: tuple[Job, ...],
    initial_position: Position,
    transfer_by_job: dict[str, TransferSlotSpec],
    profile: SchedulingProfile,
) -> tuple[Job, ...]:
    input_index = {job.id: index for index, job in enumerate(instance.jobs)}
    remaining = list(jobs)
    position = initial_position
    sequence: list[Job] = []
    while remaining:
        selected = min(
            remaining,
            key=lambda job: (
                _decision_travel_seconds(
                    profile,
                    timing,
                    position,
                    _leg_endpoints(
                        instance,
                        job,
                        side,
                        transfer_by_job.get(job.id),
                    )[0],
                ),
                job.ready_time,
                input_index[job.id],
            ),
        )
        sequence.append(selected)
        remaining.remove(selected)
        position = _leg_endpoints(
            instance,
            selected,
            side,
            transfer_by_job[selected.id] if selected.id in transfer_by_job else None,
        )[1]
    return tuple(sequence)


def _solo_completion_time(
    instance: StaticSchedulingInstance,
    timing: TimeModel,
    side: CraneSide,
    jobs: tuple[Job, ...],
    transfer_by_job: dict[str, TransferSlotSpec],
    profile: SchedulingProfile,
) -> float:
    crane = next(crane for crane in instance.cranes if crane.side is side)
    clock = (
        0.0
        if profile is not SchedulingProfile.CURRENT_YARD
        else instance.initial_state.cranes_by_id[crane.id].available_time
    )
    position = crane.initial_position
    for job in jobs:
        transfer = transfer_by_job.get(job.id)
        pickup, destination = _leg_endpoints(instance, job, side, transfer)
        if profile is SchedulingProfile.CURRENT_YARD:
            clock = max(clock, job.ready_time)
        clock += _decision_travel_seconds(profile, timing, position, pickup)
        container = instance.initial_state.containers_by_id[job.container_id]
        pickup_slot = container.current_slot if pickup == job.origin else None
        if profile is not SchedulingProfile.CURRENT_YARD:
            clock += 30.0
            clock += _decision_travel_seconds(profile, timing, pickup, destination)
            clock += 30.0
        else:
            clock += timing.pickup_seconds(pickup_slot)
            clock += timing.travel_seconds(pickup, destination)
            clock += timing.drop_seconds(
                job.final_slot if destination == job.destination else None
            )
        position = destination
    return clock


def _decision_travel_seconds(
    profile: SchedulingProfile,
    timing: TimeModel,
    origin: Position,
    destination: Position,
) -> float:
    if profile is not SchedulingProfile.CURRENT_YARD:
        return abs(destination.bay - origin.bay) * 6.1
    return timing.travel_seconds(origin, destination)


def _job_uses_side(
    instance: StaticSchedulingInstance,
    job: Job,
    side: CraneSide,
) -> bool:
    region = classify_job(instance, job)
    if region is JobRegion.CROSS_REGION:
        return True
    return (region is JobRegion.SEA_LOCAL) is (side is CraneSide.SEASIDE)


def _leg_endpoints(
    instance: StaticSchedulingInstance,
    job: Job,
    side: CraneSide,
    transfer: TransferSlotSpec | None,
) -> tuple[Position, Position]:
    region = classify_job(instance, job)
    if region is not JobRegion.CROSS_REGION:
        return job.origin, job.destination
    if transfer is None:
        raise AssertionError("cross-region job has no transfer slot")
    donor_side = _donor_side(instance, job)
    if side is donor_side:
        return job.origin, transfer.position
    return transfer.position, job.destination


def _donor_side(instance: StaticSchedulingInstance, job: Job) -> CraneSide:
    separation = _integer_separation(instance)
    h_bay = instance.layout.handshake_bay
    if job.origin.bay <= h_bay and job.destination.bay >= h_bay + separation:
        return CraneSide.SEASIDE
    if job.origin.bay >= h_bay + separation and job.destination.bay <= h_bay:
        return CraneSide.LANDSIDE
    raise PlannerInfeasibleError(f"job {job.id!r} cannot be split at the H bay")


def _choose_transfer_slot(
    instance: StaticSchedulingInstance,
    timing: TimeModel,
    job: Job,
    storage_rule: HandshakeStorageRule,
    profile: SchedulingProfile = SchedulingProfile.CURRENT_YARD,
) -> TransferSlotSpec:
    slots = tuple(
        slot
        for slot in instance.yard.transfer_slots
        if slot.enabled and slot.position.bay == instance.layout.handshake_bay
    )
    if not slots:
        raise PlannerInfeasibleError("no enabled slot exists at the H bay")

    center_row = (instance.layout.rows + 1) / 2
    if profile is not SchedulingProfile.CURRENT_YARD:
        return min(
            slots,
            key=lambda slot: (
                abs(slot.position.row - center_row),
                slot.position.row,
                slot.id,
            ),
        )

    if storage_rule is HandshakeStorageRule.NEAR_IO:
        anchor = job.origin if job.direction is MoveDirection.INBOUND else job.destination
    else:
        anchor = job.destination if job.direction is MoveDirection.INBOUND else job.origin
    return min(
        slots,
        key=lambda slot: (
            timing.travel_seconds(anchor, slot.position),
            abs(slot.position.row - center_row),
            slot.position.row,
            slot.id,
        ),
    )
