"""Coordinates and storage addresses used by the physical yard model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, order=True)
class Position:
    """Crane travel coordinate inside one scheduled yard block."""

    bay: int
    row: int


@dataclass(frozen=True, slots=True, order=True)
class StackKey:
    block_id: str
    bay: int
    row: int

    @property
    def position(self) -> Position:
        return Position(self.bay, self.row)


@dataclass(frozen=True, slots=True, order=True)
class Slot:
    """Exact container address, including its tier in a stack."""

    block_id: str
    bay: int
    row: int
    tier: int

    @property
    def stack_key(self) -> StackKey:
        return StackKey(self.block_id, self.bay, self.row)

    @property
    def position(self) -> Position:
        return Position(self.bay, self.row)
