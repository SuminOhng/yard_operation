"""Immutable snapshots of yard, container, transfer, and crane state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .geometry import Position, Slot, StackKey


class ContainerStatus(str, Enum):
    ON_AGV = "ON_AGV"
    IN_STACK = "IN_STACK"
    ON_CRANE = "ON_CRANE"
    AT_TRANSFER_SLOT = "AT_TRANSFER_SLOT"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class ContainerState:
    container_id: str
    status: ContainerStatus
    current_slot: Slot | None = None
    target_slot: Slot | None = None
    carried_by: str | None = None
    transfer_slot_id: str | None = None


@dataclass(frozen=True, slots=True)
class StackState:
    """Container IDs ordered bottom-to-top."""

    key: StackKey
    containers: tuple[str, ...] = ()

    @property
    def height(self) -> int:
        return len(self.containers)

    @property
    def top_container(self) -> str | None:
        return self.containers[-1] if self.containers else None


@dataclass(frozen=True, slots=True)
class TransferSlotState:
    slot_id: str
    containers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CraneState:
    crane_id: str
    position: Position
    carrying_container: str | None = None
    available_time: float = 0.0


@dataclass(frozen=True, slots=True)
class YardState:
    current_time: float
    stacks: tuple[StackState, ...]
    containers: tuple[ContainerState, ...]
    cranes: tuple[CraneState, ...]
    transfer_slots: tuple[TransferSlotState, ...]

    @property
    def stacks_by_key(self) -> dict[StackKey, StackState]:
        return {stack.key: stack for stack in self.stacks}

    @property
    def containers_by_id(self) -> dict[str, ContainerState]:
        return {container.container_id: container for container in self.containers}

    @property
    def cranes_by_id(self) -> dict[str, CraneState]:
        return {crane.crane_id: crane for crane in self.cranes}

    @property
    def transfer_slots_by_id(self) -> dict[str, TransferSlotState]:
        return {slot.slot_id: slot for slot in self.transfer_slots}
