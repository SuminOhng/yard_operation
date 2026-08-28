"""Create timing-repair child nodes from the first structured conflict."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..model import StaticSchedulingInstance
from ..policy import constraints_for
from ..schedule import CandidateSchedule, OperationType
from ..simulation import CraneConflict, first_crane_conflict
from ..validator import ValidationResult, validate_schedule
from .timing_repair import (
    TimingConstraint,
    TimingRepairResult,
    repair_schedule_timing,
    timing_constraint_signature,
)


class BranchNodeStatus(str, Enum):
    OPEN = "OPEN"
    FEASIBLE = "FEASIBLE"
    CONFLICTED = "CONFLICTED"
    INFEASIBLE = "INFEASIBLE"
    PRUNED_BY_BOUND = "PRUNED_BY_BOUND"
    PRUNED_DUPLICATE = "PRUNED_DUPLICATE"


@dataclass(frozen=True, slots=True)
class BranchNode:
    node_id: str
    parent_id: str | None
    depth: int
    timing_constraints: tuple[TimingConstraint, ...]
    schedule: CandidateSchedule
    validation: ValidationResult
    first_conflict: CraneConflict | None
    lower_bound: float
    status: BranchNodeStatus

    @property
    def constraint_signature(
        self,
    ) -> tuple[tuple[int, int | None, float], ...]:
        return timing_constraint_signature(self.timing_constraints)


def create_root_branch_node(
    instance: StaticSchedulingInstance,
    schedule: CandidateSchedule,
) -> BranchNode:
    validation = validate_schedule(
        instance,
        constraints_for(instance, schedule.policy),
        schedule,
    )
    conflict = first_crane_conflict(instance, schedule)
    return BranchNode(
        node_id="N0",
        parent_id=None,
        depth=0,
        timing_constraints=(),
        schedule=schedule,
        validation=validation,
        first_conflict=conflict,
        lower_bound=_schedule_completion_lower_bound(schedule),
        status=_node_status(validation, conflict),
    )


def branch_on_first_conflict(
    instance: StaticSchedulingInstance,
    node: BranchNode,
) -> tuple[BranchNode, ...]:
    """Delay either active conflicting operation behind its opponent."""

    conflict = node.first_conflict
    if conflict is None:
        return ()
    operations = node.schedule.operations
    branches: list[tuple[str, int, int]] = []
    if (
        conflict.seaside_operation_index is not None
        and conflict.landside_operation_index is not None
    ):
        branches.extend(
            (
                (
                    "S",
                    conflict.seaside_operation_index,
                    conflict.landside_operation_index,
                ),
                (
                    "L",
                    conflict.landside_operation_index,
                    conflict.seaside_operation_index,
                ),
            )
        )
    children: list[BranchNode] = []
    for suffix, delayed_index, opposing_index in branches:
        delayed = operations[delayed_index]
        opposing = operations[opposing_index]
        earliest_start = opposing.end_time
        if earliest_start <= delayed.start_time + 1e-9:
            continue
        constraint = TimingConstraint(
            operation_index=delayed_index,
            earliest_start=earliest_start,
            delayed_crane_id=delayed.crane_id,
            conflict_time=conflict.onset_time,
            opposing_operation_index=opposing_index,
        )
        combined = node.timing_constraints + (constraint,)
        try:
            repair = repair_schedule_timing(
                instance,
                node.schedule,
                combined,
            )
        except ValueError:
            children.append(
                _infeasible_child(node, suffix, combined)
            )
        else:
            children.append(
                _child_node(node, suffix, repair)
            )
    return tuple(children)


def _child_node(
    parent: BranchNode,
    suffix: str,
    repair: TimingRepairResult,
) -> BranchNode:
    return BranchNode(
        node_id=f"{parent.node_id}.{suffix}",
        parent_id=parent.node_id,
        depth=parent.depth + 1,
        timing_constraints=repair.constraints,
        schedule=repair.schedule,
        validation=repair.validation,
        first_conflict=repair.first_conflict,
        lower_bound=_schedule_completion_lower_bound(repair.schedule),
        status=_node_status(repair.validation, repair.first_conflict),
    )


def _infeasible_child(
    parent: BranchNode,
    suffix: str,
    constraints: tuple[TimingConstraint, ...],
) -> BranchNode:
    return BranchNode(
        node_id=f"{parent.node_id}.{suffix}",
        parent_id=parent.node_id,
        depth=parent.depth + 1,
        timing_constraints=constraints,
        schedule=parent.schedule,
        validation=parent.validation,
        first_conflict=parent.first_conflict,
        lower_bound=parent.lower_bound,
        status=BranchNodeStatus.INFEASIBLE,
    )


def _node_status(
    validation: ValidationResult,
    conflict: CraneConflict | None,
) -> BranchNodeStatus:
    if validation.valid:
        return BranchNodeStatus.FEASIBLE
    if conflict is not None:
        return BranchNodeStatus.CONFLICTED
    return BranchNodeStatus.INFEASIBLE


def _schedule_completion_lower_bound(schedule: CandidateSchedule) -> float:
    completion_times = [
        operation.end_time
        for operation in schedule.operations
        if operation.operation_type is OperationType.FINAL_DROP
    ]
    return max(completion_times, default=0.0)
