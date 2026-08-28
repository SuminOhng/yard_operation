"""Configuration and limits for the exhaustive reference search."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReferenceSearchConfig:
    """Bound factorial enumeration before any search work begins."""

    maximum_jobs: int = 8
    maximum_route_candidates: int = 100_000
    failure_sample_limit: int = 10

    def __post_init__(self) -> None:
        if self.maximum_jobs < 1:
            raise ValueError("maximum_jobs must be positive")
        if self.maximum_route_candidates < 1:
            raise ValueError("maximum_route_candidates must be positive")
        if self.failure_sample_limit < 0:
            raise ValueError("failure_sample_limit must be nonnegative")


class ReferenceSearchLimitError(ValueError):
    """Raised when an instance exceeds the configured exact search space."""
