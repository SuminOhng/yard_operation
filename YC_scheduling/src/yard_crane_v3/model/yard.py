"""Immutable yard geometry and physical storage resources."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .geometry import Position, StackKey


@dataclass(frozen=True, slots=True)
class StaticLayout:
    block_id: str
    bays: int
    rows: int
    tiers: int
    handshake_bay: int

    @property
    def first_work_bay(self) -> int:
        """First physical container-working bay."""

        return 1

    @property
    def last_work_bay(self) -> int:
        """Last physical container-working bay."""

        return self.bays

    @property
    def seaside_parking_bay(self) -> int:
        """Outside parking position reserved for the seaside crane."""

        return self.first_work_bay - 1

    @property
    def landside_parking_bay(self) -> int:
        """Outside parking position reserved for the landside crane."""

        return self.last_work_bay + 1

    @property
    def working_bays(self) -> range:
        return range(self.first_work_bay, self.last_work_bay + 1)

    def is_work_bay(self, bay: int) -> bool:
        return self.first_work_bay <= bay <= self.last_work_bay

    def is_on_crane_rail(self, bay: int) -> bool:
        """Return whether a bay is on the rail, including both parking bays."""

        return self.seaside_parking_bay <= bay <= self.landside_parking_bay


@dataclass(frozen=True, slots=True)
class StackSpec:
    key: StackKey
    capacity: int


class TransferSlotKind(str, Enum):
    FIXED_BUFFER = "FIXED_BUFFER"
    STACK_BACKED = "STACK_BACKED"
    VIRTUAL_STACK = "VIRTUAL_STACK"


VIRTUAL_TRANSFER_ID_PREFIX = "VIRTUAL::"


@dataclass(frozen=True, slots=True)
class TransferSlotSpec:
    id: str
    position: Position
    capacity: int
    enabled: bool = True
    kind: TransferSlotKind = TransferSlotKind.FIXED_BUFFER

    @property
    def uses_stack_storage(self) -> bool:
        return self.kind in {
            TransferSlotKind.STACK_BACKED,
            TransferSlotKind.VIRTUAL_STACK,
        }


@dataclass(frozen=True, slots=True)
class YardSpec:
    layout: StaticLayout
    stacks: tuple[StackSpec, ...]
    transfer_slots: tuple[TransferSlotSpec, ...]

    @property
    def stacks_by_key(self) -> dict[StackKey, StackSpec]:
        return {stack.key: stack for stack in self.stacks}

    @property
    def transfer_slots_by_id(self) -> dict[str, TransferSlotSpec]:
        return {slot.id: slot for slot in self.transfer_slots}

    @property
    def enabled_transfer_bays(self) -> frozenset[int]:
        return frozenset(
            slot.position.bay for slot in self.transfer_slots if slot.enabled
        )


def virtual_transfer_slots(
    layout: StaticLayout,
    fixed_slots: tuple[TransferSlotSpec, ...],
) -> tuple[TransferSlotSpec, ...]:
    """Build one logical stack-backed handover point per free coordinate."""

    occupied_positions = {slot.position for slot in fixed_slots}
    return tuple(
        TransferSlotSpec(
            id=(
                f"{VIRTUAL_TRANSFER_ID_PREFIX}{layout.block_id}::BAY_{bay}::ROW_{row}"
            ),
            position=Position(bay, row),
            capacity=1,
            kind=TransferSlotKind.VIRTUAL_STACK,
        )
        for bay in layout.working_bays
        for row in range(1, layout.rows + 1)
        if Position(bay, row) not in occupied_positions
    )


def build_regular_yard(
    layout: StaticLayout,
    transfer_slots: tuple[TransferSlotSpec, ...],
) -> YardSpec:
    """Create one stack at every bay/row coordinate in a regular block."""

    stacks = tuple(
        StackSpec(
            key=StackKey(layout.block_id, bay, row),
            capacity=layout.tiers,
        )
        for bay in layout.working_bays
        for row in range(1, layout.rows + 1)
    )
    return YardSpec(layout, stacks, transfer_slots)
