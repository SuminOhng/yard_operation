"""Contracts and scenario construction for bound calculations."""

from .bound_calculator import BoundCalculation, calculate_bounds
from .calculator import UpperBoundCalculation, calculate_upper_bounds
from .full_replan import (
    FullReplanCalculation,
    build_full_replan_instance,
    calculate_full_replan_upper_bound,
)
from .lower_bound import (
    JobLowerBoundComponent,
    LowerBoundCalculation,
    calculate_lower_bound,
)
from .request import BoundCalculationRequest, BoundRequestError
from .residual import ResidualStateError, build_residual_instance
from .result import BoundCalculationResult
from .scenario import (
    BoundScenario,
    JobSubsetError,
    derive_bound_scenario,
    derive_job_subset_instance,
)
from .serialization import (
    BOUND_ARTIFACT_SCHEMA_VERSION,
    bound_calculation_dict,
    write_bound_calculation,
)
from .strict_append import (
    StrictAppendCalculation,
    calculate_strict_append_upper_bound,
)

__all__ = [
    "BOUND_ARTIFACT_SCHEMA_VERSION",
    "BoundCalculation",
    "BoundCalculationRequest",
    "BoundCalculationResult",
    "BoundRequestError",
    "BoundScenario",
    "FullReplanCalculation",
    "JobLowerBoundComponent",
    "JobSubsetError",
    "LowerBoundCalculation",
    "ResidualStateError",
    "StrictAppendCalculation",
    "UpperBoundCalculation",
    "build_full_replan_instance",
    "build_residual_instance",
    "bound_calculation_dict",
    "calculate_strict_append_upper_bound",
    "calculate_full_replan_upper_bound",
    "calculate_bounds",
    "calculate_lower_bound",
    "calculate_upper_bounds",
    "derive_bound_scenario",
    "derive_job_subset_instance",
    "write_bound_calculation",
]
