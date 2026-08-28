"""Policy-neutral explicit route modes for one container job."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..model import CraneSide, Job, StaticSchedulingInstance
from ..policy import CooperationPolicy, constraints_for


class RouteKind(str, Enum):
    DIRECT = "DIRECT"
    HANDOVER = "HANDOVER"


@dataclass(frozen=True, slots=True)
class RouteMode:
    job_id: str
    kind: RouteKind
    direct_crane_side: CraneSide | None = None
    transfer_slot_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind is RouteKind.DIRECT:
            if self.direct_crane_side is None or self.transfer_slot_id is not None:
                raise ValueError(
                    "DIRECT route needs direct_crane_side and no transfer slot"
                )
        elif self.kind is RouteKind.HANDOVER:
            if self.transfer_slot_id is None or self.direct_crane_side is not None:
                raise ValueError(
                    "HANDOVER route needs transfer_slot_id and no direct crane"
                )

    @property
    def label(self) -> str:
        if self.kind is RouteKind.DIRECT:
            return f"DIRECT_{self.direct_crane_side.value}"
        return f"HANDOVER_AT_{self.transfer_slot_id}"


def allowed_route_modes(
    instance: StaticSchedulingInstance,
    policy: CooperationPolicy,
    job: Job,
) -> tuple[RouteMode, ...]:
    """Create the nested explicit route space for one job."""

    modes = [
        RouteMode(job.id, RouteKind.DIRECT, CraneSide.SEASIDE),
        RouteMode(job.id, RouteKind.DIRECT, CraneSide.LANDSIDE),
    ]
    if policy is CooperationPolicy.NO_SHARING:
        return tuple(modes)

    # Local import avoids making policy-neutral route types initialize planners.
    from ..planners.any_bay.scheduler import _slot_can_split_job

    for point in constraints_for(instance, policy).transfer_points:
        if _slot_can_split_job(instance, job, point):
            modes.append(
                RouteMode(
                    job.id,
                    RouteKind.HANDOVER,
                    transfer_slot_id=point.id,
                )
            )
    return tuple(modes)


def route_mode_dict(mode: RouteMode) -> dict[str, str | None]:
    return {
        "job_id": mode.job_id,
        "kind": mode.kind.value,
        "direct_crane_side": (
            mode.direct_crane_side.value
            if mode.direct_crane_side is not None
            else None
        ),
        "transfer_slot_id": mode.transfer_slot_id,
        "label": mode.label,
    }
