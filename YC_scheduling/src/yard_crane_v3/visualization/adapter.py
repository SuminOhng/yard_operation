"""Convert validated bound calculations into visualization view models."""

from __future__ import annotations

import math
from collections.abc import Iterable

from ..bounds import BoundCalculation
from ..model import ContainerStatus
from ..planners import (
    PlannerCandidateEvaluation,
    evaluate_any_bay_candidates,
    evaluate_handshake_area_candidates,
)
from ..policy import CooperationPolicy
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


TOLERANCE = 1e-9


def build_policy_schedule_visualization(
    calculation: BoundCalculation,
) -> PolicyScheduleVisualization:
    """Select the schedule proving Best UB and expose its exact operations."""

    result = calculation.result
    method, schedule, validation = _best_validated_schedule(calculation)
    operations: tuple[VisualizationOperation, ...] = ()
    crane_ids = tuple(crane.id for crane in calculation.request.instance.cranes)
    schedule_makespan: float | None = None
    schedule_valid = False
    violation_codes: tuple[str, ...] = ()
    handover_count = 0
    reshuffle_count = 0
    concurrent_crane_seconds = 0.0
    average_transfer_wait_seconds: float | None = None

    if schedule is not None and validation is not None:
        schedule_valid = validation.valid
        schedule_makespan = validation.makespan
        violation_codes = tuple(issue.code for issue in validation.issues)
        handover_count = validation.handover_count
        reshuffle_count = sum(
            operation.purpose is OperationPurpose.RESHUFFLE
            and operation.operation_type is OperationType.PICKUP
            for operation in schedule.operations
        )
        concurrent_crane_seconds = _concurrent_crane_seconds(
            schedule,
            crane_ids,
        )
        average_transfer_wait_seconds = _average_transfer_wait_seconds(
            schedule,
        )
        instance = calculation.request.instance
        jobs = instance.jobs_by_id
        transfer_points = constraints_for(
            instance,
            result.policy,
        ).transfer_points_by_id
        traces = {
            trace.operation_index: trace
            for trace in validation.simulation.operation_traces
        }
        operation_views: list[VisualizationOperation] = []
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
            operation_views.append(
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
                    container_bay_after=(
                        after_slot.bay if after_slot is not None else None
                    ),
                    container_row_after=(
                        after_slot.row if after_slot is not None else None
                    ),
                    container_tier_after=(
                        after_slot.tier if after_slot is not None else None
                    ),
                    container_transfer_after=(
                        operation.transfer_slot_id
                        if after_status
                        == ContainerStatus.AT_TRANSFER_SLOT.value
                        else None
                    ),
                )
            )
        operations = tuple(operation_views)

    if result.upper_bound_validated:
        if schedule is None or validation is None or not validation.valid:
            raise ValueError("validated upper bound has no valid source schedule")
        if result.best_known_upper_bound is None or schedule_makespan is None:
            raise ValueError("validated upper bound is missing its makespan")
        if not math.isclose(
            result.best_known_upper_bound,
            schedule_makespan,
            rel_tol=0.0,
            abs_tol=TOLERANCE,
        ):
            raise ValueError("Best UB differs from selected schedule makespan")

    return PolicyScheduleVisualization(
        policy=result.policy,
        status=_calculation_status(calculation),
        upper_bound_validated=result.upper_bound_validated,
        lower_bound_certified=result.lower_bound_certified,
        best_known_upper_bound=result.best_known_upper_bound,
        combined_lower_bound=result.combined_lower_bound,
        absolute_gap=result.absolute_gap,
        relative_gap=result.relative_gap,
        strict_append_upper_bound=result.strict_append_upper_bound,
        full_replan_upper_bound=result.full_replan_upper_bound,
        upper_bound_method=method,
        schedule_makespan=schedule_makespan,
        schedule_valid=schedule_valid,
        handover_count=handover_count,
        reshuffle_count=reshuffle_count,
        concurrent_crane_seconds=concurrent_crane_seconds,
        average_transfer_wait_seconds=average_transfer_wait_seconds,
        crane_ids=crane_ids,
        operations=operations,
        violation_codes=violation_codes,
        error=result.error,
    )


def build_static_schedule_visualization(
    calculations: Iterable[BoundCalculation],
    *,
    title: str | None = None,
) -> StaticScheduleVisualization:
    """Build one shared-scale three-policy visualization."""

    items = tuple(calculations)
    if len(items) != len(CooperationPolicy):
        raise ValueError("exactly one calculation per cooperation policy is required")
    by_policy = {item.result.policy: item for item in items}
    if set(by_policy) != set(CooperationPolicy):
        raise ValueError("calculations must contain all cooperation policies once")

    first = items[0]
    request = first.request
    for item in items[1:]:
        other = item.request
        if (
            other.instance.instance_id != request.instance.instance_id
            or other.existing_job_ids != request.existing_job_ids
            or other.new_job_ids != request.new_job_ids
            or not math.isclose(
                other.decision_time,
                request.decision_time,
                rel_tol=0.0,
                abs_tol=TOLERANCE,
            )
        ):
            raise ValueError("all policies must visualize the same bound request")

    policy_views = tuple(
        build_policy_schedule_visualization(by_policy[policy])
        for policy in CooperationPolicy
    )
    horizon_values: list[float] = [request.decision_time, 1.0]
    for policy_view in policy_views:
        horizon_values.extend(
            value
            for value in (
                policy_view.best_known_upper_bound,
                policy_view.combined_lower_bound,
            )
            if value is not None
        )
        horizon_values.extend(
            operation.end_time for operation in policy_view.operations
        )
    layout = request.instance.layout
    instance = request.instance
    initial = instance.initial_state
    jobs_by_container = {
        job.container_id: job for job in instance.jobs
    }
    transfer_specs = instance.yard.transfer_slots_by_id
    crane_specs = instance.cranes_by_id
    initial_cranes = tuple(
        InitialCraneVisualization(
            crane_id=crane.crane_id,
            side=crane_specs[crane.crane_id].side.value,
            bay=crane.position.bay,
            row=crane.position.row,
            carrying_container=crane.carrying_container,
        )
        for crane in initial.cranes
    )
    initial_containers: list[InitialContainerVisualization] = []
    for container in initial.containers:
        job = jobs_by_container.get(container.container_id)
        slot = container.current_slot
        position = slot.position if slot is not None else None
        if position is None and container.transfer_slot_id in transfer_specs:
            position = transfer_specs[container.transfer_slot_id].position
        if position is None and container.container_id in jobs_by_container:
            position = jobs_by_container[container.container_id].origin
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
    transfer_slots = tuple(
        TransferSlotVisualization(
            slot_id=slot.id,
            bay=slot.position.bay,
            row=slot.position.row,
            capacity=slot.capacity,
            enabled=slot.enabled,
        )
        for slot in instance.yard.transfer_slots
    )
    return StaticScheduleVisualization(
        instance_id=request.instance.instance_id,
        title=title or request.instance.instance_id,
        block_id=layout.block_id,
        work_bays=layout.bays,
        rows=layout.rows,
        tiers=layout.tiers,
        seaside_parking_bay=layout.seaside_parking_bay,
        landside_parking_bay=layout.landside_parking_bay,
        handshake_bay=layout.handshake_bay,
        decision_time=request.decision_time,
        existing_job_ids=request.existing_job_ids,
        new_job_ids=request.new_job_ids,
        shared_time_horizon=max(horizon_values),
        minimum_crane_separation_bays=(
            instance.physical_rules.minimum_crane_separation_bays
        ),
        initial_cranes=initial_cranes,
        initial_containers=tuple(initial_containers),
        transfer_slots=transfer_slots,
        route_candidates=_route_candidate_visualizations(
            by_policy,
        ),
        policies=policy_views,
    )


def _route_candidate_visualizations(
    calculations: dict[CooperationPolicy, BoundCalculation],
) -> tuple[RouteCandidateVisualization, ...]:
    instance = next(iter(calculations.values())).request.instance
    selected_artifacts = {
        policy: _best_validated_schedule(calculation)
        for policy, calculation in calculations.items()
    }
    selected = {
        policy: artifact[1]
        for policy, artifact in selected_artifacts.items()
    }
    direct_method, direct_schedule, direct_validation = selected_artifacts[
        CooperationPolicy.NO_SHARING
    ]
    direct = PlannerCandidateEvaluation(
        direct_method or "NO_SHARING_DIRECT",
        direct_schedule,
        direct_validation,
        None if direct_validation is not None else "direct schedule unavailable",
    )
    handshake_method, handshake_schedule, handshake_validation = (
        selected_artifacts[CooperationPolicy.HANDSHAKE_AREA]
    )
    if handshake_validation is not None and handshake_validation.handover_count > 0:
        handshake = PlannerCandidateEvaluation(
            handshake_method or "SELECTED_H_HANDOVER",
            handshake_schedule,
            handshake_validation,
        )
    else:
        handshake_items = tuple(
            item
            for item in evaluate_handshake_area_candidates(instance)
            if item.label != "DIRECT_FALLBACK" and item.handover_count > 0
        )
        handshake = _best_route_candidate(
            handshake_items,
            "no valid H handover candidate",
        )
    any_method, any_schedule, any_validation = selected_artifacts[
        CooperationPolicy.ANY_BAY
    ]
    if (
        any_validation is not None
        and any_validation.handover_count > 0
        and any_schedule is not None
        and _uses_any_only_transfer(instance, any_schedule)
    ):
        any_bay = PlannerCandidateEvaluation(
            any_method or "SELECTED_ANY_BAY_HANDOVER",
            any_schedule,
            any_validation,
        )
    else:
        any_items = tuple(
            item
            for item in evaluate_any_bay_candidates(instance)
            if item.label != "NESTED_HANDSHAKE" and item.handover_count > 0
        )
        any_bay = _best_route_candidate(
            any_items,
            "no valid any-bay handover candidate",
        )
    return (
        _route_candidate_view(
            "DIRECT",
            CooperationPolicy.NO_SHARING,
            direct,
            selected[CooperationPolicy.NO_SHARING],
        ),
        _route_candidate_view(
            "H_HANDOVER",
            CooperationPolicy.HANDSHAKE_AREA,
            handshake,
            selected[CooperationPolicy.HANDSHAKE_AREA],
        ),
        _route_candidate_view(
            "ANY_BAY_HANDOVER",
            CooperationPolicy.ANY_BAY,
            any_bay,
            selected[CooperationPolicy.ANY_BAY],
        ),
    )


def _uses_any_only_transfer(
    instance,
    schedule: CandidateSchedule,
) -> bool:
    handshake_ids = constraints_for(
        instance,
        CooperationPolicy.HANDSHAKE_AREA,
    ).allowed_handover_point_ids
    return any(
        operation.transfer_slot_id not in handshake_ids
        for operation in schedule.operations
        if operation.transfer_slot_id is not None
    )


def _best_route_candidate(
    items: tuple[PlannerCandidateEvaluation, ...],
    unavailable_message: str,
) -> PlannerCandidateEvaluation:
    valid = tuple(item for item in items if item.valid)
    if valid:
        return min(
            valid,
            key=lambda item: (
                item.makespan,
                item.handover_count,
                len(item.schedule.operations),
                item.label,
            ),
        )
    error = "; ".join(item.error for item in items if item.error)
    return PlannerCandidateEvaluation(
        unavailable_message,
        None,
        None,
        error or unavailable_message,
    )


def _route_candidate_view(
    route_key: str,
    policy: CooperationPolicy,
    candidate: PlannerCandidateEvaluation,
    selected_schedule: CandidateSchedule | None,
) -> RouteCandidateVisualization:
    schedule = candidate.schedule
    return RouteCandidateVisualization(
        route_key=route_key,
        policy=policy,
        method=candidate.label,
        valid=candidate.valid,
        makespan=candidate.makespan,
        handover_count=candidate.handover_count,
        operation_count=len(schedule.operations) if schedule is not None else 0,
        selected=(
            schedule is not None
            and selected_schedule is not None
            and schedule.operations == selected_schedule.operations
        ),
        error=candidate.error,
    )


def _best_validated_schedule(
    calculation: BoundCalculation,
) -> tuple[str | None, CandidateSchedule | None, ValidationResult | None]:
    result = calculation.result
    best = result.best_known_upper_bound
    if best is None:
        return None, None, None
    append = result.strict_append_upper_bound
    if append is not None and math.isclose(
        best, append, rel_tol=0.0, abs_tol=TOLERANCE
    ):
        item = calculation.upper_bounds.strict_append
        return "STRICT_APPEND", item.combined_schedule, item.combined_validation
    replan = result.full_replan_upper_bound
    if replan is not None and math.isclose(
        best, replan, rel_tol=0.0, abs_tol=TOLERANCE
    ):
        item = calculation.upper_bounds.full_replan
        return "FULL_REPLAN", item.schedule, item.validation
    raise ValueError("Best UB has no matching calculation artifact")


def _concurrent_crane_seconds(
    schedule: CandidateSchedule,
    crane_ids: tuple[str, ...],
) -> float:
    if len(crane_ids) != 2:
        return 0.0
    intervals = {
        crane_id: sorted(
            (
                (operation.start_time, operation.end_time)
                for operation in schedule.operations
                if operation.crane_id == crane_id
            ),
        )
        for crane_id in crane_ids
    }
    first = intervals[crane_ids[0]]
    second = intervals[crane_ids[1]]
    first_index = 0
    second_index = 0
    overlap = 0.0
    while first_index < len(first) and second_index < len(second):
        first_start, first_end = first[first_index]
        second_start, second_end = second[second_index]
        overlap += max(
            0.0,
            min(first_end, second_end) - max(first_start, second_start),
        )
        if first_end <= second_end:
            first_index += 1
        else:
            second_index += 1
    return overlap


def _average_transfer_wait_seconds(
    schedule: CandidateSchedule,
) -> float | None:
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


def _calculation_status(calculation: BoundCalculation) -> str:
    result = calculation.result
    if result.upper_bound_validated and result.lower_bound_certified:
        return "COMPLETE"
    if result.upper_bound_validated:
        return "UPPER_BOUND_ONLY"
    if result.lower_bound_certified:
        return "LOWER_BOUND_ONLY"
    return "FAILED"
