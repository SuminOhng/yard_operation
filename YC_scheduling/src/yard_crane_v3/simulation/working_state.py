"""Mutable replay state hidden behind immutable YardState snapshots."""

from __future__ import annotations

from dataclasses import replace

from ..model import (
    ContainerState,
    CraneState,
    Slot,
    StackKey,
    StackState,
    StaticSchedulingInstance,
    TransferSlotState,
    YardState,
)


class WorkingState:
    def __init__(self, instance: StaticSchedulingInstance) -> None:
        initial = instance.initial_state
        self.current_time = initial.current_time
        self.stack_order = tuple(stack.key for stack in initial.stacks)
        self.container_order = tuple(
            container.container_id for container in initial.containers
        )
        self.crane_order = tuple(crane.crane_id for crane in initial.cranes)
        self.transfer_order = tuple(
            slot.slot_id for slot in initial.transfer_slots
        )
        self.stacks: dict[StackKey, list[str]] = {
            stack.key: list(stack.containers) for stack in initial.stacks
        }
        self.containers: dict[str, ContainerState] = {
            container.container_id: container for container in initial.containers
        }
        self.cranes: dict[str, CraneState] = {
            crane.crane_id: crane for crane in initial.cranes
        }
        self.transfer_slots: dict[str, list[str]] = {
            slot.slot_id: list(slot.containers)
            for slot in initial.transfer_slots
        }
        self.active_cranes: dict[str, int] = {}
        self.reserved_containers: dict[str, int] = {}
        self.reserved_final_slots: dict[Slot, int] = {}
        self.reserved_transfer_drops: dict[str, int] = {}
        self.reserved_virtual_stack_slots: dict[Slot, int] = {}
        self.virtual_handover_donors: dict[str, str] = {}
        self.handover_counts: dict[str, int] = {}

    def ensure_transfer_point(self, slot_id: str) -> list[str]:
        """Materialize policy-only transfer state without changing snapshots."""

        return self.transfer_slots.setdefault(slot_id, [])

    def update_crane(self, crane_id: str, **changes) -> None:
        self.cranes[crane_id] = replace(self.cranes[crane_id], **changes)

    def update_container(self, container_id: str, **changes) -> None:
        self.containers[container_id] = replace(
            self.containers[container_id], **changes
        )

    def freeze(self) -> YardState:
        return YardState(
            current_time=self.current_time,
            stacks=tuple(
                StackState(key, tuple(self.stacks[key]))
                for key in self.stack_order
            ),
            containers=tuple(
                self.containers[container_id]
                for container_id in self.container_order
            ),
            cranes=tuple(
                self.cranes[crane_id] for crane_id in self.crane_order
            ),
            transfer_slots=tuple(
                TransferSlotState(slot_id, tuple(self.transfer_slots[slot_id]))
                for slot_id in self.transfer_order
            ),
        )
