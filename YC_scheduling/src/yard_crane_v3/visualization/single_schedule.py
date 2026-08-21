"""Build a standalone replay model from one validated schedule."""

from __future__ import annotations

from ..model import ContainerStatus, StaticSchedulingInstance
from ..policy import constraints_for
from ..schedule import CandidateSchedule, OperationPurpose, OperationType
from ..validator import ValidationResult
from .model import (
    InitialContainerVisualization,
    InitialCraneVisualization,
    PolicyScheduleVisualization,
    RouteCandidateVisualization,
    StaticScheduleVisualization,
    TransferSlotVisualization,
    VisualizationOperation,
)


def build_single_schedule_visualization(
    instance: StaticSchedulingInstance,
    schedule: CandidateSchedule,
    validation: ValidationResult,
    *,
    title: str,
    method: str,
) -> StaticScheduleVisualization:
    """Expose one valid planner candidate through the existing replay UI."""

    if not validation.valid:
        raise ValueError("single-schedule visualization requires a valid schedule")
    jobs = instance.jobs_by_id
    transfer_points = constraints_for(instance, schedule.policy).transfer_points_by_id
    traces = {
        trace.operation_index: trace
        for trace in validation.simulation.operation_traces
    }
    operations: list[VisualizationOperation] = []
    for index, operation in enumerate(schedule.operations):
        trace = traces[index]
        delta = trace.state_delta
        target = operation.target_slot
        if (
            target is None
            and operation.operation_type is OperationType.FINAL_DROP
            and operation.job_id in jobs
        ):
            target = jobs[operation.job_id].final_slot
        after_slot = delta.container_slot_after if delta is not None else None
        after_status = (
            delta.container_status_after.value
            if delta is not None and delta.container_status_after is not None
            else None
        )
        operations.append(
            VisualizationOperation(
                operation_index=index,
                crane_id=operation.crane_id,
                operation_type=operation.operation_type,
                purpose=operation.purpose,
                start_time=operation.start_time,
                end_time=operation.end_time,
                start_bay=operation.start_position.bay,
                start_row=operation.start_position.row,
                end_bay=operation.end_position.bay,
                end_row=operation.end_position.row,
                job_id=operation.job_id,
                container_id=(
                    operation.container_id
                    if operation.container_id is not None
                    else jobs[operation.job_id].container_id
                    if operation.job_id in jobs
                    else None
                ),
                transfer_slot_id=operation.transfer_slot_id,
                transfer_point_kind=(
                    transfer_points[operation.transfer_slot_id].kind.value
                    if operation.transfer_slot_id in transfer_points
                    else None
                ),
                target_bay=target.bay if target is not None else None,
                target_row=target.row if target is not None else None,
                target_tier=target.tier if target is not None else None,
                accepted=trace.accepted,
                crane_load_after=(
                    delta.crane_load_after if delta is not None else None
                ),
                container_status_after=after_status,
                container_bay_after=(after_slot.bay if after_slot is not None else None),
                container_row_after=(after_slot.row if after_slot is not None else None),
                container_tier_after=(
                    after_slot.tier if after_slot is not None else None
                ),
                container_transfer_after=(
                    operation.transfer_slot_id
                    if after_status == ContainerStatus.AT_TRANSFER_SLOT.value
                    else None
                ),
            )
        )

    crane_ids = tuple(crane.id for crane in instance.cranes)
    policy = PolicyScheduleVisualization(
        policy=schedule.policy,
        status="COMPLETE",
        upper_bound_validated=True,
        lower_bound_certified=False,
        best_known_upper_bound=validation.makespan,
        combined_lower_bound=None,
        absolute_gap=None,
        relative_gap=None,
        strict_append_upper_bound=None,
        full_replan_upper_bound=validation.makespan,
        upper_bound_method=method,
        schedule_makespan=validation.makespan,
        schedule_valid=True,
        handover_count=validation.handover_count,
        reshuffle_count=sum(
            operation.purpose is OperationPurpose.RESHUFFLE
            and operation.operation_type is OperationType.PICKUP
            for operation in schedule.operations
        ),
        concurrent_crane_seconds=_concurrent_seconds(schedule, crane_ids),
        average_transfer_wait_seconds=_average_transfer_wait(schedule),
        crane_ids=crane_ids,
        operations=tuple(operations),
        violation_codes=(),
        error=None,
    )
    initial = instance.initial_state
    crane_specs = instance.cranes_by_id
    transfer_specs = instance.yard.transfer_slots_by_id
    jobs_by_container = {job.container_id: job for job in instance.jobs}
    initial_containers: list[InitialContainerVisualization] = []
    for container in initial.containers:
        job = jobs_by_container.get(container.container_id)
        slot = container.current_slot
        position = slot.position if slot is not None else None
        if position is None and container.transfer_slot_id in transfer_specs:
            position = transfer_specs[container.transfer_slot_id].position
        if position is None and job is not None:
            position = job.origin
        initial_containers.append(
            InitialContainerVisualization(
                container_id=container.container_id,
                direction=job.direction.value if job is not None else None,
                status=container.status.value,
                bay=position.bay if position is not None else None,
                row=position.row if position is not None else None,
                tier=slot.tier if slot is not None else None,
                carried_by=container.carried_by,
                transfer_slot_id=container.transfer_slot_id,
            )
        )
    layout = instance.layout
    return StaticScheduleVisualization(
        instance_id=instance.instance_id,
        title=title,
        block_id=layout.block_id,
        work_bays=layout.bays,
        rows=layout.rows,
        tiers=layout.tiers,
        seaside_parking_bay=layout.seaside_parking_bay,
        landside_parking_bay=layout.landside_parking_bay,
        handshake_bay=layout.handshake_bay,
        decision_time=initial.current_time,
        existing_job_ids=tuple(job.id for job in instance.jobs),
        new_job_ids=(),
        shared_time_horizon=max(validation.makespan, 1.0),
        minimum_crane_separation_bays=(
            instance.physical_rules.minimum_crane_separation_bays
        ),
        initial_cranes=tuple(
            InitialCraneVisualization(
                crane_id=crane.crane_id,
                side=crane_specs[crane.crane_id].side.value,
                bay=crane.position.bay,
                row=crane.position.row,
                carrying_container=crane.carrying_container,
            )
            for crane in initial.cranes
        ),
        initial_containers=tuple(initial_containers),
        transfer_slots=tuple(
            TransferSlotVisualization(
                slot_id=slot.id,
                bay=slot.position.bay,
                row=slot.position.row,
                capacity=slot.capacity,
                enabled=slot.enabled,
            )
            for slot in instance.yard.transfer_slots
        ),
        route_candidates=(
            RouteCandidateVisualization(
                route_key="H_HANDOVER",
                policy=schedule.policy,
                method=method,
                valid=True,
                makespan=validation.makespan,
                handover_count=validation.handover_count,
                operation_count=len(schedule.operations),
                selected=True,
                error=None,
            ),
        ),
        policies=(policy,),
    )


def _concurrent_seconds(
    schedule: CandidateSchedule,
    crane_ids: tuple[str, ...],
) -> float:
    if len(crane_ids) != 2:
        return 0.0
    first = sorted(
        (operation.start_time, operation.end_time)
        for operation in schedule.operations
        if operation.crane_id == crane_ids[0]
    )
    second = sorted(
        (operation.start_time, operation.end_time)
        for operation in schedule.operations
        if operation.crane_id == crane_ids[1]
    )
    left = right = 0
    overlap = 0.0
    while left < len(first) and right < len(second):
        overlap += max(
            0.0,
            min(first[left][1], second[right][1])
            - max(first[left][0], second[right][0]),
        )
        if first[left][1] <= second[right][1]:
            left += 1
        else:
            right += 1
    return overlap


def _average_transfer_wait(schedule: CandidateSchedule) -> float | None:
    drops = {
        operation.job_id: operation.end_time
        for operation in schedule.operations
        if operation.operation_type is OperationType.HANDOVER_DROP
        and operation.job_id is not None
    }
    waits = [
        operation.start_time - drops[operation.job_id]
        for operation in schedule.operations
        if operation.operation_type is OperationType.HANDOVER_PICKUP
        and operation.job_id in drops
    ]
    return sum(waits) / len(waits) if waits else None
