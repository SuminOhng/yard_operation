"""Strict JSON loader for the structured static physical model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import (
    ContainerState,
    ContainerStatus,
    CraneSide,
    CraneSpec,
    CraneState,
    Job,
    MotionParameters,
    MoveDirection,
    PhysicalRules,
    Position,
    Slot,
    StackKey,
    StackState,
    StaticLayout,
    StaticSchedulingInstance,
    TransferSlotSpec,
    TransferSlotState,
    YardState,
    build_regular_yard,
    validate_instance,
)


class InputError(ValueError):
    pass


def _object(
    value: Any,
    label: str,
    required: set[str],
    optional: set[str] = frozenset(),
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError(f"{label} must be an object")
    unknown = set(value) - required - optional
    if unknown:
        raise InputError(f"{label} contains unknown fields: {sorted(unknown)}")
    missing = required - set(value)
    if missing:
        raise InputError(f"{label} is missing fields: {sorted(missing)}")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise InputError(f"{label} must be an array")
    return value


def _position(value: Any, label: str) -> Position:
    item = _object(value, label, {"bay", "row"})
    return Position(int(item["bay"]), int(item["row"]))


def _slot(value: Any, label: str) -> Slot:
    item = _object(value, label, {"block_id", "bay", "row", "tier"})
    return Slot(
        str(item["block_id"]),
        int(item["bay"]),
        int(item["row"]),
        int(item["tier"]),
    )


def _optional_slot(value: Any, label: str) -> Slot | None:
    return None if value is None else _slot(value, label)


def parse_instance(payload: Any) -> StaticSchedulingInstance:
    root = _object(
        payload,
        "root",
        {
            "schema_version",
            "instance_id",
            "layout",
            "motion",
            "physical_rules",
            "cranes",
            "transfer_slots",
            "initial_state",
            "jobs",
        },
    )
    raw_layout = _object(
        root["layout"],
        "layout",
        {"block_id", "bays", "rows", "tiers", "handshake_bay"},
    )
    layout = StaticLayout(
        block_id=str(raw_layout["block_id"]),
        bays=int(raw_layout["bays"]),
        rows=int(raw_layout["rows"]),
        tiers=int(raw_layout["tiers"]),
        handshake_bay=int(raw_layout["handshake_bay"]),
    )
    raw_motion = _object(
        root["motion"],
        "motion",
        {
            "gantry_seconds_per_bay",
            "trolley_seconds_per_row",
            "hoist_seconds_per_tier",
            "pickup_seconds",
            "drop_seconds",
        },
    )
    motion = MotionParameters(
        gantry_seconds_per_bay=float(raw_motion["gantry_seconds_per_bay"]),
        trolley_seconds_per_row=float(raw_motion["trolley_seconds_per_row"]),
        hoist_seconds_per_tier=float(raw_motion["hoist_seconds_per_tier"]),
        pickup_seconds=float(raw_motion["pickup_seconds"]),
        drop_seconds=float(raw_motion["drop_seconds"]),
    )
    raw_rules = _object(
        root["physical_rules"],
        "physical_rules",
        {"minimum_crane_separation_bays", "maximum_handovers_per_job"},
    )
    physical_rules = PhysicalRules(
        minimum_crane_separation_bays=float(
            raw_rules["minimum_crane_separation_bays"]
        ),
        maximum_handovers_per_job=int(raw_rules["maximum_handovers_per_job"]),
    )

    cranes: list[CraneSpec] = []
    for index, raw in enumerate(_array(root["cranes"], "cranes")):
        item = _object(
            raw,
            f"cranes[{index}]",
            {"id", "side", "initial_position"},
        )
        cranes.append(
            CraneSpec(
                id=str(item["id"]),
                side=CraneSide(item["side"]),
                initial_position=_position(
                    item["initial_position"],
                    f"cranes[{index}].initial_position",
                ),
            )
        )

    transfer_specs: list[TransferSlotSpec] = []
    for index, raw in enumerate(
        _array(root["transfer_slots"], "transfer_slots")
    ):
        item = _object(
            raw,
            f"transfer_slots[{index}]",
            {"id", "position", "capacity", "enabled"},
        )
        transfer_specs.append(
            TransferSlotSpec(
                id=str(item["id"]),
                position=_position(
                    item["position"], f"transfer_slots[{index}].position"
                ),
                capacity=int(item["capacity"]),
                enabled=bool(item["enabled"]),
            )
        )
    yard = build_regular_yard(layout, tuple(transfer_specs))

    raw_state = _object(
        root["initial_state"],
        "initial_state",
        {"current_time", "stacks", "containers", "cranes", "transfer_slots"},
    )
    populated_stacks: dict[StackKey, tuple[str, ...]] = {}
    for index, raw in enumerate(_array(raw_state["stacks"], "initial_state.stacks")):
        item = _object(
            raw,
            f"initial_state.stacks[{index}]",
            {"block_id", "bay", "row", "containers"},
        )
        key = StackKey(
            str(item["block_id"]), int(item["bay"]), int(item["row"])
        )
        if key not in yard.stacks_by_key:
            raise InputError(
                f"initial_state.stacks[{index}] is outside the physical yard"
            )
        if key in populated_stacks:
            raise InputError(
                f"initial_state.stacks contains duplicate stack {key!r}"
            )
        populated_stacks[key] = tuple(
            str(container_id)
            for container_id in _array(
                item["containers"],
                f"initial_state.stacks[{index}].containers",
            )
        )
    stack_states = tuple(
        StackState(
            key=stack.key,
            containers=populated_stacks.get(stack.key, ()),
        )
        for stack in yard.stacks
    )

    containers: list[ContainerState] = []
    for index, raw in enumerate(
        _array(raw_state["containers"], "initial_state.containers")
    ):
        item = _object(
            raw,
            f"initial_state.containers[{index}]",
            {"container_id", "status", "current_slot", "target_slot"},
            {"carried_by", "transfer_slot_id"},
        )
        containers.append(
            ContainerState(
                container_id=str(item["container_id"]),
                status=ContainerStatus(item["status"]),
                current_slot=_optional_slot(
                    item["current_slot"],
                    f"initial_state.containers[{index}].current_slot",
                ),
                target_slot=_optional_slot(
                    item["target_slot"],
                    f"initial_state.containers[{index}].target_slot",
                ),
                carried_by=(
                    str(item["carried_by"])
                    if item.get("carried_by") is not None
                    else None
                ),
                transfer_slot_id=(
                    str(item["transfer_slot_id"])
                    if item.get("transfer_slot_id") is not None
                    else None
                ),
            )
        )

    crane_states: list[CraneState] = []
    for index, raw in enumerate(_array(raw_state["cranes"], "initial_state.cranes")):
        item = _object(
            raw,
            f"initial_state.cranes[{index}]",
            {"crane_id", "position", "carrying_container", "available_time"},
        )
        crane_states.append(
            CraneState(
                crane_id=str(item["crane_id"]),
                position=_position(
                    item["position"], f"initial_state.cranes[{index}].position"
                ),
                carrying_container=(
                    str(item["carrying_container"])
                    if item["carrying_container"] is not None
                    else None
                ),
                available_time=float(item["available_time"]),
            )
        )

    transfer_states: list[TransferSlotState] = []
    for index, raw in enumerate(
        _array(raw_state["transfer_slots"], "initial_state.transfer_slots")
    ):
        item = _object(
            raw,
            f"initial_state.transfer_slots[{index}]",
            {"slot_id", "containers"},
        )
        transfer_states.append(
            TransferSlotState(
                slot_id=str(item["slot_id"]),
                containers=tuple(
                    str(container_id)
                    for container_id in _array(
                        item["containers"],
                        f"initial_state.transfer_slots[{index}].containers",
                    )
                ),
            )
        )
    initial_state = YardState(
        current_time=float(raw_state["current_time"]),
        stacks=stack_states,
        containers=tuple(containers),
        cranes=tuple(crane_states),
        transfer_slots=tuple(transfer_states),
    )

    jobs: list[Job] = []
    for index, raw in enumerate(_array(root["jobs"], "jobs")):
        item = _object(
            raw,
            f"jobs[{index}]",
            {
                "id",
                "container_id",
                "direction",
                "origin",
                "destination",
                "final_slot",
                "release_time",
                "agv_ready_time",
            },
        )
        jobs.append(
            Job(
                id=str(item["id"]),
                container_id=str(item["container_id"]),
                direction=MoveDirection(item["direction"]),
                origin=_position(item["origin"], f"jobs[{index}].origin"),
                destination=_position(
                    item["destination"], f"jobs[{index}].destination"
                ),
                final_slot=_optional_slot(
                    item["final_slot"], f"jobs[{index}].final_slot"
                ),
                release_time=float(item["release_time"]),
                agv_ready_time=float(item["agv_ready_time"]),
            )
        )

    instance = StaticSchedulingInstance(
        schema_version=str(root["schema_version"]),
        instance_id=str(root["instance_id"]),
        yard=yard,
        motion=motion,
        physical_rules=physical_rules,
        cranes=tuple(cranes),
        jobs=tuple(jobs),
        initial_state=initial_state,
    )
    validate_instance(instance)
    return instance


def load_instance(path: str | Path) -> StaticSchedulingInstance:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InputError(f"cannot load input: {error}") from error
    return parse_instance(payload)
