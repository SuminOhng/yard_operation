"""Policy-neutral, single-crane reference schedule used for smoke tests."""

from __future__ import annotations

from ...model import ContainerStatus, CraneSide, StaticSchedulingInstance
from ...policy import CooperationPolicy
from ...schedule import CandidateSchedule, OperationType, ScheduledOperation
from ...timing import TimeModel


def build_serial_baseline(
    instance: StaticSchedulingInstance,
    policy: CooperationPolicy,
) -> CandidateSchedule:
    """Serve every job directly with the seaside crane in input order."""

    crane = next(
        crane for crane in instance.cranes if crane.side is CraneSide.SEASIDE
    )
    timing = TimeModel(instance.motion)
    containers = instance.initial_state.containers_by_id
    clock = instance.initial_state.current_time
    position = crane.initial_position
    operations: list[ScheduledOperation] = []

    for job in instance.jobs:
        clock = max(clock, job.ready_time)
        empty_travel = timing.travel_seconds(position, job.origin)
        if empty_travel > 0:
            operations.append(
                ScheduledOperation(
                    crane.id,
                    OperationType.MOVE_EMPTY,
                    clock,
                    clock + empty_travel,
                    position,
                    job.origin,
                )
            )
            clock += empty_travel
        position = job.origin

        container = containers[job.container_id]
        pickup_slot = (
            container.current_slot
            if container.status is ContainerStatus.IN_STACK
            else None
        )
        pickup_duration = timing.pickup_seconds(pickup_slot)
        operations.append(
            ScheduledOperation(
                crane.id,
                OperationType.PICKUP,
                clock,
                clock + pickup_duration,
                position,
                position,
                job.id,
            )
        )
        clock += pickup_duration

        loaded_travel = timing.travel_seconds(position, job.destination)
        if loaded_travel > 0:
            operations.append(
                ScheduledOperation(
                    crane.id,
                    OperationType.MOVE_LOADED,
                    clock,
                    clock + loaded_travel,
                    position,
                    job.destination,
                    job.id,
                )
            )
            clock += loaded_travel
        position = job.destination

        drop_duration = timing.drop_seconds(job.final_slot)
        operations.append(
            ScheduledOperation(
                crane.id,
                OperationType.FINAL_DROP,
                clock,
                clock + drop_duration,
                position,
                position,
                job.id,
            )
        )
        clock += drop_duration

    return CandidateSchedule(instance.instance_id, policy, tuple(operations))

