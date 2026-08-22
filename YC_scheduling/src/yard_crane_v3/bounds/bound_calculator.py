"""Complete static UB/LB calculator facade."""

from __future__ import annotations

from dataclasses import dataclass

from ..planners import Planner
from .calculator import UpperBoundCalculation, calculate_upper_bounds
from .lower_bound import LowerBoundCalculation, calculate_lower_bound
from .request import BoundCalculationRequest
from .result import BoundCalculationResult


@dataclass(frozen=True, slots=True)
class BoundCalculation:
    """Final result with separated upper- and lower-bound evidence."""

    request: BoundCalculationRequest
    result: BoundCalculationResult
    upper_bounds: UpperBoundCalculation
    lower_bound: LowerBoundCalculation


def calculate_bounds(
    request: BoundCalculationRequest,
    planner: Planner | None = None,
) -> BoundCalculation:
    """Run every implemented bound method through one public entry point."""

    upper_bounds = calculate_upper_bounds(request, planner)
    lower_bound = calculate_lower_bound(request, upper_bounds.result)
    return BoundCalculation(
        request=request,
        result=lower_bound.result,
        upper_bounds=upper_bounds,
        lower_bound=lower_bound,
    )

