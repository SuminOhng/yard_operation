"""Run the three real policy planners against one immutable instance."""

from __future__ import annotations

from collections.abc import Mapping
from time import perf_counter

from ..model import StaticSchedulingInstance, validate_instance
from ..planners import (
    Planner,
    build_any_bay_schedule,
    build_handshake_area_schedule,
    build_no_sharing_schedule,
)
from ..policy import (
    CooperationPolicy,
    constraints_for,
    validate_policy_lattice,
)
from ..schedule import OperationPurpose, OperationType
from ..validator import validate_schedule
from .result import (
    PolicyComparisonRecord,
    PolicyMetrics,
    ThreePolicyComparison,
)


DEFAULT_POLICY_PLANNERS: Mapping[CooperationPolicy, Planner] = {
    CooperationPolicy.NO_SHARING: build_no_sharing_schedule,
    CooperationPolicy.HANDSHAKE_AREA: build_handshake_area_schedule,
    CooperationPolicy.ANY_BAY: build_any_bay_schedule,
}


def run_three_policy_comparison(
    instance: StaticSchedulingInstance,
    planners: Mapping[CooperationPolicy, Planner] | None = None,
) -> ThreePolicyComparison:
    """Execute every policy independently and preserve failures as records."""

    validate_instance(instance)
    validate_policy_lattice(instance)
    selected = dict(DEFAULT_POLICY_PLANNERS if planners is None else planners)
    missing = set(CooperationPolicy) - set(selected)
    if missing:
        names = ", ".join(sorted(policy.value for policy in missing))
        raise ValueError(f"planner mapping is missing: {names}")

    records = tuple(
        _run_one_policy(instance, policy, selected[policy])
        for policy in CooperationPolicy
    )
    return ThreePolicyComparison(instance.instance_id, records)


def _run_one_policy(
    instance: StaticSchedulingInstance,
    policy: CooperationPolicy,
    planner: Planner,
) -> PolicyComparisonRecord:
    planner_name = getattr(planner, "__name__", type(planner).__name__)
    started = perf_counter()
    try:
        schedule = planner(instance, policy)
        validation = validate_schedule(
            instance,
            constraints_for(instance, policy),
            schedule,
        )
        runtime = perf_counter() - started
        reshuffle_count = sum(
            operation.purpose is OperationPurpose.RESHUFFLE
            and operation.operation_type is OperationType.PICKUP
            for operation in schedule.operations
        )
        metrics = PolicyMetrics(
            valid=validation.valid,
            feasible_upper_bound=(
                validation.makespan if validation.valid else None
            ),
            runtime_seconds=runtime,
            handover_count=validation.handover_count,
            reshuffle_count=reshuffle_count,
            operation_count=len(schedule.operations),
            used_crane_ids=tuple(
                sorted({operation.crane_id for operation in schedule.operations})
            ),
            used_transfer_slot_ids=tuple(
                sorted(
                    {
                        operation.transfer_slot_id
                        for operation in schedule.operations
                        if operation.transfer_slot_id is not None
                    }
                )
            ),
            completed_job_ids=tuple(
                sorted(validation.simulation.completed_job_ids)
            ),
            violation_codes=tuple(
                issue.code for issue in validation.issues
            ),
        )
        return PolicyComparisonRecord(
            policy,
            planner_name,
            metrics,
            schedule,
            validation,
        )
    except Exception as exc:
        runtime = perf_counter() - started
        metrics = PolicyMetrics(
            valid=False,
            feasible_upper_bound=None,
            runtime_seconds=runtime,
            handover_count=0,
            reshuffle_count=0,
            operation_count=0,
            used_crane_ids=(),
            used_transfer_slot_ids=(),
            completed_job_ids=(),
            violation_codes=("PLANNER_ERROR",),
        )
        return PolicyComparisonRecord(
            policy,
            planner_name,
            metrics,
            None,
            None,
            f"{type(exc).__name__}: {exc}",
        )

