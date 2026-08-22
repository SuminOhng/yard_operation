"""One public facade for all currently implemented upper bounds."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..planners import Planner
from .full_replan import (
    FullReplanCalculation,
    calculate_full_replan_upper_bound,
)
from .request import BoundCalculationRequest
from .result import BoundCalculationResult
from .strict_append import (
    StrictAppendCalculation,
    calculate_strict_append_upper_bound,
)


@dataclass(frozen=True, slots=True)
class UpperBoundCalculation:
    """Merged result plus both independently auditable calculations."""

    request: BoundCalculationRequest
    result: BoundCalculationResult
    strict_append: StrictAppendCalculation
    full_replan: FullReplanCalculation


def calculate_upper_bounds(
    request: BoundCalculationRequest,
    planner: Planner | None = None,
) -> UpperBoundCalculation:
    """Calculate both UB methods and retain the smallest validated value."""

    append = calculate_strict_append_upper_bound(request, planner)
    replan = calculate_full_replan_upper_bound(request, planner)
    candidates = tuple(
        value
        for value in (
            append.result.strict_append_upper_bound,
            replan.result.full_replan_upper_bound,
        )
        if value is not None
    )
    best = min(candidates) if candidates else None
    provenance = append.result.bound_provenance + replan.result.bound_provenance
    errors = tuple(
        error
        for error in (append.result.error, replan.result.error)
        if error is not None
    )
    result = replace(
        BoundCalculationResult.pending(request),
        baseline_makespan=append.result.baseline_makespan,
        baseline_operation_horizon=append.result.baseline_operation_horizon,
        strict_append_upper_bound=append.result.strict_append_upper_bound,
        full_replan_upper_bound=replan.result.full_replan_upper_bound,
        best_known_upper_bound=best,
        makespan_extension=(
            best - append.result.baseline_makespan
            if best is not None and append.result.baseline_makespan is not None
            else None
        ),
        append_valid=append.result.append_valid,
        upper_bound_validated=best is not None,
        bound_provenance=provenance,
        error="; ".join(errors) if not candidates and errors else None,
    )
    return UpperBoundCalculation(request, result, append, replan)

