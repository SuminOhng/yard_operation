"""Small-instance exhaustive reference search."""

from .config import ReferenceSearchConfig, ReferenceSearchLimitError
from .concurrency import (
    ConcurrentCandidate,
    CraneSequence,
    build_left_shifted_candidate,
    derive_crane_sequences,
)
from .branch_node import (
    BranchNode,
    BranchNodeStatus,
    branch_on_first_conflict,
    create_root_branch_node,
)
from .result import (
    ReferenceOptimalityScope,
    ReferenceSearchResult,
    RouteReferenceSearchResult,
    ThreePolicyReferenceResult,
    ThreePolicyRouteReferenceResult,
)
from .route_builder import build_explicit_route_schedule
from .routes import RouteKind, RouteMode, allowed_route_modes, route_mode_dict
from .serialization import (
    REFERENCE_RESULT_SCHEMA_VERSION,
    reference_result_dict,
    route_reference_result_dict,
    three_policy_reference_dict,
    three_policy_route_reference_dict,
    write_reference_result,
)
from .solver import (
    REFERENCE_POLICY_PLANNERS,
    solve_exhaustive_reference,
    solve_route_mode_reference,
    solve_three_policy_reference,
    solve_three_policy_route_reference,
)
from .timing_repair import (
    TimingConstraint,
    TimingConstraintReason,
    TimingRepairResult,
    normalize_timing_constraints,
    repair_schedule_timing,
    timing_constraint_signature,
)

__all__ = [
    "ConcurrentCandidate",
    "CraneSequence",
    "BranchNode",
    "BranchNodeStatus",
    "REFERENCE_POLICY_PLANNERS",
    "REFERENCE_RESULT_SCHEMA_VERSION",
    "ReferenceOptimalityScope",
    "ReferenceSearchConfig",
    "ReferenceSearchLimitError",
    "ReferenceSearchResult",
    "RouteKind",
    "RouteMode",
    "RouteReferenceSearchResult",
    "ThreePolicyReferenceResult",
    "ThreePolicyRouteReferenceResult",
    "allowed_route_modes",
    "build_explicit_route_schedule",
    "build_left_shifted_candidate",
    "branch_on_first_conflict",
    "create_root_branch_node",
    "derive_crane_sequences",
    "reference_result_dict",
    "route_mode_dict",
    "route_reference_result_dict",
    "solve_exhaustive_reference",
    "solve_route_mode_reference",
    "solve_three_policy_reference",
    "solve_three_policy_route_reference",
    "three_policy_reference_dict",
    "three_policy_route_reference_dict",
    "TimingConstraint",
    "TimingConstraintReason",
    "TimingRepairResult",
    "normalize_timing_constraints",
    "repair_schedule_timing",
    "timing_constraint_signature",
    "write_reference_result",
]
