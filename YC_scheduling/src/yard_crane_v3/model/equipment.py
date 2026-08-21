"""Crane identity and common motion parameters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .geometry import Position


class CraneSide(str, Enum):
    SEASIDE = "SEASIDE"
    LANDSIDE = "LANDSIDE"


@dataclass(frozen=True, slots=True)
class CraneSpec:
    id: str
    side: CraneSide
    initial_position: Position


@dataclass(frozen=True, slots=True)
class MotionParameters:
    gantry_seconds_per_bay: float
    trolley_seconds_per_row: float
    hoist_seconds_per_tier: float
    pickup_seconds: float
    drop_seconds: float
