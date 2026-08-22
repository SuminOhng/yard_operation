from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .model import (
    StaticSchedulingInstance,
    TransferSlotKind,
    TransferSlotSpec,
    virtual_transfer_slots,
)


class CooperationPolicy(str, Enum):
    NO_SHARING = "NO_SHARING"
    HANDSHAKE_AREA = "HANDSHAKE_AREA"
    ANY_BAY = "ANY_BAY"


@dataclass(frozen=True, slots=True)
class PolicyConstraints:
    policy: CooperationPolicy
    active_crane_ids: frozenset[str]
    direct_transport_allowed: bool
    transfer_points: tuple[TransferSlotSpec, ...]
    maximum_handovers_per_job: int

    @property
    def transfer_points_by_id(self) -> dict[str, TransferSlotSpec]:
        return {point.id: point for point in self.transfer_points}

    @property
    def allowed_handover_point_ids(self) -> frozenset[str]:
        return frozenset(self.transfer_points_by_id)

    @property
    def allowed_handover_bays(self) -> frozenset[int]:
        return frozenset(point.position.bay for point in self.transfer_points)

    @property
    def handover_allowed(self) -> bool:
        return bool(self.transfer_points)


def constraints_for(instance: StaticSchedulingInstance, policy: CooperationPolicy) -> PolicyConstraints:
    """Return the fixed behavioral contract for one cooperation policy.

    Both cranes and direct end-to-end transport are enabled in every policy.
    The policies differ only in where a one-time handover may occur.
    """

    maximum = instance.physical_rules.maximum_handovers_per_job
    active_cranes = frozenset(crane.id for crane in instance.cranes)
    fixed_slots = tuple(
        slot
        for slot in instance.yard.transfer_slots
        if slot.kind is TransferSlotKind.FIXED_BUFFER
    )
    enabled_fixed_slots = tuple(slot for slot in fixed_slots if slot.enabled)
    if policy is CooperationPolicy.NO_SHARING:
        return PolicyConstraints(
            policy=policy,
            active_crane_ids=active_cranes,
            direct_transport_allowed=True,
            transfer_points=(),
            maximum_handovers_per_job=0,
        )
    if policy is CooperationPolicy.HANDSHAKE_AREA:
        return PolicyConstraints(
            policy=policy,
            active_crane_ids=active_cranes,
            direct_transport_allowed=True,
            transfer_points=tuple(
                slot
                for slot in enabled_fixed_slots
                if slot.position.bay == instance.layout.handshake_bay
            ),
            maximum_handovers_per_job=maximum,
        )
    return PolicyConstraints(
        policy=policy,
        active_crane_ids=active_cranes,
        direct_transport_allowed=True,
        transfer_points=(
            enabled_fixed_slots
            + virtual_transfer_slots(instance.layout, fixed_slots)
        ),
        maximum_handovers_per_job=maximum,
    )


def validate_policy_lattice(instance: StaticSchedulingInstance) -> None:
    """Fail if the three fixed policy feasible sets stop being nested."""

    no_sharing = constraints_for(instance, CooperationPolicy.NO_SHARING)
    handshake = constraints_for(instance, CooperationPolicy.HANDSHAKE_AREA)
    any_bay = constraints_for(instance, CooperationPolicy.ANY_BAY)
    contracts = (no_sharing, handshake, any_bay)
    if not all(contract.direct_transport_allowed for contract in contracts):
        raise ValueError("direct transport must be allowed by every policy")
    if not all(
        contract.active_crane_ids == no_sharing.active_crane_ids
        for contract in contracts
    ):
        raise ValueError("every policy must activate the same two cranes")
    if not (
        no_sharing.allowed_handover_point_ids
        <= handshake.allowed_handover_point_ids
        <= any_bay.allowed_handover_point_ids
    ):
        raise ValueError("policy handover permissions must be nested")
    if not (
        no_sharing.maximum_handovers_per_job
        <= handshake.maximum_handovers_per_job
        <= any_bay.maximum_handovers_per_job
    ):
        raise ValueError("policy handover limits must be nested")
