"""Deterministic exhaustive enumeration over every static job order."""

from __future__ import annotations

import math
from dataclasses import replace
from itertools import permutations, product
from time import perf_counter

from ..model import StaticSchedulingInstance, validate_instance
from ..planners import (
    Planner,
    PlannerInfeasibleError,
    build_any_bay_schedule,
    build_handshake_area_schedule,
    build_no_sharing_schedule,
)
from ..policy import CooperationPolicy, constraints_for
from ..schedule import OperationType
from ..validator import validate_schedule
from .config import ReferenceSearchConfig, ReferenceSearchLimitError
from .concurrency import build_left_shifted_candidate, derive_crane_sequences
from .result import (
    ReferenceSearchResult,
    RouteReferenceSearchResult,
    ThreePolicyReferenceResult,
    ThreePolicyRouteReferenceResult,
)
from .route_builder import build_explicit_route_schedule
from .routes import RouteKind, RouteMode, allowed_route_modes


REFERENCE_POLICY_PLANNERS: dict[CooperationPolicy, Planner] = {
    CooperationPolicy.NO_SHARING: build_no_sharing_schedule,
    CooperationPolicy.HANDSHAKE_AREA: build_handshake_area_schedule,
    CooperationPolicy.ANY_BAY: build_any_bay_schedule,
}


def solve_exhaustive_reference(
    instance: StaticSchedulingInstance,
    policy: CooperationPolicy,
    *,
    config: ReferenceSearchConfig | None = None,
    planner: Planner | None = None,
) -> ReferenceSearchResult:
    """Return the exact minimum over all job orders in the candidate space.

    This is not a global twin-crane optimality proof. For each permutation it
    invokes the current policy planner, so the certificate covers every job
    order and every candidate that planner deterministically constructs.
    """

    validate_instance(instance)
    config = config or ReferenceSearchConfig()
    job_count = len(instance.jobs)
    if job_count > config.maximum_jobs:
        raise ReferenceSearchLimitError(
            f"instance has {job_count} jobs but maximum_jobs is "
            f"{config.maximum_jobs}; factorial search was not started"
        )

    selected_planner = planner or REFERENCE_POLICY_PLANNERS[policy]
    expected = math.factorial(job_count)
    evaluated = 0
    feasible = 0
    infeasible = 0
    failures: list[str] = []
    best = None
    best_key = None
    best_order: tuple[str, ...] = ()
    best_validation = None
    started = perf_counter()

    for order_indices in permutations(range(job_count)):
        ordered_jobs = tuple(instance.jobs[index] for index in order_indices)
        ordered_instance = replace(instance, jobs=ordered_jobs)
        order_ids = tuple(job.id for job in ordered_jobs)
        evaluated += 1
        try:
            schedule = selected_planner(ordered_instance, policy)
            validation = validate_schedule(
                ordered_instance,
                constraints_for(ordered_instance, policy),
                schedule,
            )
            if not validation.valid:
                details = ", ".join(
                    f"{issue.code}:{issue.message}"
                    for issue in validation.issues
                )
                raise PlannerInfeasibleError(
                    f"common validator rejected candidate: {details}"
                )
        except (PlannerInfeasibleError, ValueError) as exc:
            infeasible += 1
            if len(failures) < config.failure_sample_limit:
                failures.append(f"{order_ids!r}: {exc}")
            continue

        feasible += 1
        key = (
            validation.makespan,
            validation.handover_count,
            len(schedule.operations),
            order_ids,
        )
        if best_key is None or key < best_key:
            best_key = key
            best = schedule
            best_order = order_ids
            best_validation = validation

    runtime = perf_counter() - started
    if best is None or best_validation is None:
        detail = "; ".join(failures) or "no valid candidate"
        raise PlannerInfeasibleError(
            f"reference search found no feasible schedule for "
            f"{policy.value}: {detail}"
        )
    if evaluated != expected:
        raise RuntimeError("reference enumeration ended before all orders")

    return ReferenceSearchResult(
        instance_id=instance.instance_id,
        policy=policy,
        job_count=job_count,
        expected_permutation_count=expected,
        evaluated_permutation_count=evaluated,
        feasible_candidate_count=feasible,
        infeasible_candidate_count=infeasible,
        best_job_order=best_order,
        best_makespan=best_validation.makespan,
        best_schedule=best,
        best_validation=best_validation,
        runtime_seconds=runtime,
        failure_samples=tuple(failures),
    )


def solve_three_policy_reference(
    instance: StaticSchedulingInstance,
    *,
    config: ReferenceSearchConfig | None = None,
) -> ThreePolicyReferenceResult:
    records = tuple(
        solve_exhaustive_reference(instance, policy, config=config)
        for policy in CooperationPolicy
    )
    return ThreePolicyReferenceResult(instance.instance_id, records)


def solve_route_mode_reference(
    instance: StaticSchedulingInstance,
    policy: CooperationPolicy,
    *,
    config: ReferenceSearchConfig | None = None,
) -> RouteReferenceSearchResult:
    """Enumerate every job order and every allowed explicit serial route."""

    validate_instance(instance)
    config = config or ReferenceSearchConfig()
    job_count = len(instance.jobs)
    if job_count > config.maximum_jobs:
        raise ReferenceSearchLimitError(
            f"instance has {job_count} jobs but maximum_jobs is "
            f"{config.maximum_jobs}; route search was not started"
        )

    modes_by_job = {
        job.id: allowed_route_modes(instance, policy, job)
        for job in instance.jobs
    }
    route_plan_count = math.prod(len(modes) for modes in modes_by_job.values())
    permutation_count = math.factorial(job_count)
    explicit_candidate_count = route_plan_count * permutation_count
    planner_candidate_count = permutation_count
    concurrent_candidate_count = explicit_candidate_count
    expected = (
        planner_candidate_count
        + explicit_candidate_count
        + concurrent_candidate_count
    )
    if expected > config.maximum_route_candidates:
        raise ReferenceSearchLimitError(
            f"route search needs {expected} candidates but "
            f"maximum_route_candidates is {config.maximum_route_candidates}; "
            "search was not started"
        )

    evaluated = 0
    feasible = 0
    infeasible = 0
    failures: list[str] = []
    best_schedule = None
    best_validation = None
    best_order: tuple[str, ...] = ()
    best_modes = ()
    best_source = ""
    best_sequences = ()
    best_key = None
    started = perf_counter()

    for order_indices in permutations(range(job_count)):
        ordered_jobs = tuple(instance.jobs[index] for index in order_indices)
        ordered_instance = replace(instance, jobs=ordered_jobs)
        order_ids = tuple(job.id for job in ordered_jobs)
        ordered_mode_spaces = tuple(modes_by_job[job.id] for job in ordered_jobs)

        evaluated += 1
        try:
            planner_schedule = REFERENCE_POLICY_PLANNERS[policy](
                ordered_instance,
                policy,
            )
            planner_validation = validate_schedule(
                ordered_instance,
                constraints_for(ordered_instance, policy),
                planner_schedule,
            )
            if not planner_validation.valid:
                raise PlannerInfeasibleError(
                    "common validator rejected current planner candidate"
                )
            planner_modes = _infer_route_modes(
                ordered_instance,
                order_ids,
                planner_schedule,
            )
        except (PlannerInfeasibleError, ValueError) as exc:
            infeasible += 1
            if len(failures) < config.failure_sample_limit:
                failures.append(
                    f"order={order_ids!r}, source=CURRENT_POLICY_PLANNER: {exc}"
                )
        else:
            feasible += 1
            planner_labels = tuple(mode.label for mode in planner_modes)
            key = (
                planner_validation.makespan,
                planner_validation.handover_count,
                len(planner_schedule.operations),
                order_ids,
                planner_labels,
                "CURRENT_POLICY_PLANNER",
            )
            if best_key is None or key < best_key:
                best_key = key
                best_schedule = planner_schedule
                best_validation = planner_validation
                best_order = order_ids
                best_modes = planner_modes
                best_source = "CURRENT_POLICY_PLANNER"
                best_sequences = _sequence_summary(planner_schedule)

        for route_modes in product(*ordered_mode_spaces):
            evaluated += 1
            route_labels = tuple(mode.label for mode in route_modes)
            try:
                schedule = build_explicit_route_schedule(
                    instance,
                    policy,
                    order_ids,
                    tuple(route_modes),
                )
                validation = validate_schedule(
                    instance,
                    constraints_for(instance, policy),
                    schedule,
                )
                if not validation.valid:
                    raise PlannerInfeasibleError(
                        "common validator rejected explicit route candidate"
                    )
            except (PlannerInfeasibleError, ValueError) as exc:
                infeasible += 1
                evaluated += 1
                infeasible += 1
                if len(failures) < config.failure_sample_limit:
                    failures.append(
                        f"order={order_ids!r}, routes={route_labels!r}: {exc}"
                    )
                continue

            feasible += 1
            key = (
                validation.makespan,
                validation.handover_count,
                len(schedule.operations),
                order_ids,
                route_labels,
                "EXPLICIT_SERIAL_ROUTE",
            )
            if best_key is None or key < best_key:
                best_key = key
                best_schedule = schedule
                best_validation = validation
                best_order = order_ids
                best_modes = tuple(route_modes)
                best_source = "EXPLICIT_SERIAL_ROUTE"
                best_sequences = _sequence_summary(schedule)

            evaluated += 1
            concurrent = build_left_shifted_candidate(
                instance,
                policy,
                schedule,
            )
            if not concurrent.validation.valid:
                infeasible += 1
                if len(failures) < config.failure_sample_limit:
                    details = ", ".join(
                        issue.code for issue in concurrent.validation.issues
                    )
                    failures.append(
                        f"order={order_ids!r}, routes={route_labels!r}, "
                        f"source=LEFT_SHIFTED_ROUTE: {details}"
                    )
                continue
            feasible += 1
            concurrent_key = (
                concurrent.validation.makespan,
                concurrent.validation.handover_count,
                len(concurrent.schedule.operations),
                order_ids,
                route_labels,
                "LEFT_SHIFTED_ROUTE",
            )
            if best_key is None or concurrent_key < best_key:
                best_key = concurrent_key
                best_schedule = concurrent.schedule
                best_validation = concurrent.validation
                best_order = order_ids
                best_modes = tuple(route_modes)
                best_source = "LEFT_SHIFTED_ROUTE"
                best_sequences = tuple(
                    (sequence.crane_id, sequence.job_ids)
                    for sequence in concurrent.crane_sequences
                )

    runtime = perf_counter() - started
    if evaluated != expected:
        raise RuntimeError("route enumeration ended before all candidates")
    if best_schedule is None or best_validation is None:
        detail = "; ".join(failures) or "no valid candidate"
        raise PlannerInfeasibleError(
            f"route reference search found no feasible schedule for "
            f"{policy.value}: {detail}"
        )

    return RouteReferenceSearchResult(
        instance_id=instance.instance_id,
        policy=policy,
        job_count=job_count,
        permutation_count=permutation_count,
        planner_candidate_count=planner_candidate_count,
        explicit_route_candidate_count=explicit_candidate_count,
        concurrent_candidate_count=concurrent_candidate_count,
        expected_candidate_count=expected,
        evaluated_candidate_count=evaluated,
        feasible_candidate_count=feasible,
        infeasible_candidate_count=infeasible,
        best_job_order=best_order,
        best_route_modes=best_modes,
        best_candidate_source=best_source,
        best_crane_job_sequences=best_sequences,
        best_makespan=best_validation.makespan,
        best_schedule=best_schedule,
        best_validation=best_validation,
        runtime_seconds=runtime,
        failure_samples=tuple(failures),
    )


def solve_three_policy_route_reference(
    instance: StaticSchedulingInstance,
    *,
    config: ReferenceSearchConfig | None = None,
) -> ThreePolicyRouteReferenceResult:
    records = tuple(
        solve_route_mode_reference(instance, policy, config=config)
        for policy in CooperationPolicy
    )
    return ThreePolicyRouteReferenceResult(instance.instance_id, records)


def _infer_route_modes(
    instance: StaticSchedulingInstance,
    order_ids: tuple[str, ...],
    schedule,
) -> tuple[RouteMode, ...]:
    crane_sides = {
        crane.id: crane.side for crane in instance.cranes
    }
    modes: list[RouteMode] = []
    for job_id in order_ids:
        operations = [
            operation
            for operation in schedule.operations
            if operation.job_id == job_id
        ]
        handover = next(
            (
                operation
                for operation in operations
                if operation.operation_type is OperationType.HANDOVER_DROP
            ),
            None,
        )
        if handover is not None:
            if handover.transfer_slot_id is None:
                raise ValueError(f"job {job_id!r} handover has no slot")
            modes.append(
                RouteMode(
                    job_id,
                    RouteKind.HANDOVER,
                    transfer_slot_id=handover.transfer_slot_id,
                )
            )
            continue
        final_drop = next(
            (
                operation
                for operation in operations
                if operation.operation_type is OperationType.FINAL_DROP
            ),
            None,
        )
        if final_drop is None:
            raise ValueError(f"job {job_id!r} has no final drop")
        modes.append(
            RouteMode(
                job_id,
                RouteKind.DIRECT,
                direct_crane_side=crane_sides[final_drop.crane_id],
            )
        )
    return tuple(modes)


def _sequence_summary(schedule) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (sequence.crane_id, sequence.job_ids)
        for sequence in derive_crane_sequences(schedule)
    )
