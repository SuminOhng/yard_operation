from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from yard_crane_v3 import load_instance


BLOCK_COUNT = 22
BASE_SEED = 20260823
BAYS = 20
ROWS = 10
TIERS = 6
HANDSHAKE_BAY = 10


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate 22 distinct 20x10x6 block instances."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data" / "blocks_22_stack_h",
    )
    args = parser.parse_args()

    output_dir = args.output_dir
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, object]] = []
    fingerprints: set[str] = set()
    for number in range(1, BLOCK_COUNT + 1):
        seed = BASE_SEED + number
        payload, metadata = build_instance(number, seed)
        path = output_dir / f"block_{number:02d}.json"
        _write_json(path, payload)
        load_instance(path)

        fingerprint = _layout_fingerprint(payload)
        if fingerprint in fingerprints:
            raise RuntimeError(f"duplicate block layout generated for block {number:02d}")
        fingerprints.add(fingerprint)
        entries.append(
            {
                "block_id": payload["layout"]["block_id"],
                "instance_id": payload["instance_id"],
                "instance_file": path.name,
                "seed": seed,
                **metadata,
            }
        )

    manifest = {
        "schema_version": "1.0.0",
        "set_id": "BLOCKS_22_STACK_H_20X10X6_15OUT5IN",
        "block_count": BLOCK_COUNT,
        "layout": {"bays": BAYS, "rows": ROWS, "tiers": TIERS},
        "job_mix": {"outbound": 15, "inbound": 5},
        "instances": entries,
    }
    _write_json(output_dir / "manifest.json", manifest)
    (output_dir / "README.md").write_text(_readme(), encoding="utf-8")
    print(f"generated {BLOCK_COUNT} instances in {output_dir}")
    return 0


def build_instance(number: int, seed: int) -> tuple[dict[str, object], dict[str, int]]:
    rng = random.Random(seed)
    block_id = f"BLOCK_{number:02d}"
    prefix = f"B{number:02d}"

    outbound_stacks = _outbound_stacks(rng)
    reserved = set(outbound_stacks)
    inbound_stacks = _sample_stacks(rng, 5, reserved, exclude_bay=HANDSHAKE_BAY)
    reserved.update(inbound_stacks)

    stacks: dict[tuple[int, int], list[str]] = {}
    outbound_jobs: list[dict[str, object]] = []
    blocker_count = 0
    blocker_targets = set(rng.sample(range(15), rng.randint(6, 10)))

    for index, (bay, row) in enumerate(outbound_stacks, start=1):
        target_tier = rng.randint(1, 4)
        stack = [
            f"{prefix}_SUP_OUT_{index:02d}_T{tier}"
            for tier in range(1, target_tier)
        ]
        container_id = f"{prefix}_CONT_OUT_{index:02d}"
        stack.append(container_id)
        if index - 1 in blocker_targets:
            count = rng.randint(1, min(2, TIERS - target_tier))
            for blocker_index in range(1, count + 1):
                stack.append(
                    f"{prefix}_BLOCKER_OUT_{index:02d}_{blocker_index}"
                )
            blocker_count += count
        stacks[(bay, row)] = stack
        outbound_jobs.append(
            _job(
                job_id=f"{prefix}_JOB_OUT_{index:02d}",
                container_id=container_id,
                direction="OUTBOUND",
                origin=(bay, row),
                destination=(0, row),
            )
        )

    inbound_jobs: list[dict[str, object]] = []
    for index, (bay, row) in enumerate(inbound_stacks, start=1):
        final_tier = rng.randint(1, 5)
        stacks[(bay, row)] = [
            f"{prefix}_SUP_IN_{index:02d}_T{tier}"
            for tier in range(1, final_tier)
        ]
        container_id = f"{prefix}_CONT_IN_{index:02d}"
        inbound_jobs.append(
            _job(
                job_id=f"{prefix}_JOB_IN_{index:02d}",
                container_id=container_id,
                direction="INBOUND",
                origin=(0, row),
                destination=(bay, row),
                final_tier=final_tier,
                block_id=block_id,
            )
        )

    background_stack_count = rng.randint(16, 24)
    background_stacks = _sample_stacks(
        rng,
        background_stack_count,
        reserved,
        exclude_bay=HANDSHAKE_BAY,
    )
    for stack_index, key in enumerate(background_stacks, start=1):
        height = rng.randint(1, 4)
        stacks[key] = [
            f"{prefix}_BACKGROUND_{stack_index:02d}_T{tier}"
            for tier in range(1, height + 1)
        ]

    rng.shuffle(outbound_jobs)
    rng.shuffle(inbound_jobs)
    jobs = outbound_jobs + inbound_jobs
    initial_stacks = [
        {
            "block_id": block_id,
            "bay": bay,
            "row": row,
            "containers": containers,
        }
        for (bay, row), containers in sorted(stacks.items())
        if containers
    ]
    container_states = _container_states(
        block_id,
        initial_stacks,
        inbound_jobs,
    )

    payload: dict[str, object] = {
        "schema_version": "3.1.0",
        "instance_id": f"BLOCK_{number:02d}_STACK_H_20X10X6_15OUT5IN_RESHUFFLE",
        "layout": {
            "block_id": block_id,
            "bays": BAYS,
            "rows": ROWS,
            "tiers": TIERS,
            "handshake_bay": HANDSHAKE_BAY,
        },
        "motion": {
            "gantry_seconds_per_bay": 3.2,
            "trolley_seconds_per_row": 2.8,
            "hoist_seconds_per_tier": 1.4,
            "pickup_seconds": 12.0,
            "drop_seconds": 13.5,
        },
        "physical_rules": {
            "minimum_crane_separation_bays": 1.0,
            "maximum_handovers_per_job": 1,
        },
        "cranes": [
            {
                "id": "C_SEA",
                "side": "SEASIDE",
                "initial_position": {"bay": 0, "row": 1},
            },
            {
                "id": "C_LAND",
                "side": "LANDSIDE",
                "initial_position": {"bay": BAYS + 1, "row": ROWS},
            },
        ],
        "transfer_slots": _transfer_slots(),
        "initial_state": {
            "current_time": 0.0,
            "stacks": initial_stacks,
            "containers": container_states,
            "cranes": [
                {
                    "crane_id": "C_SEA",
                    "position": {"bay": 0, "row": 1},
                    "carrying_container": None,
                    "available_time": 0.0,
                },
                {
                    "crane_id": "C_LAND",
                    "position": {"bay": BAYS + 1, "row": ROWS},
                    "carrying_container": None,
                    "available_time": 0.0,
                },
            ],
            "transfer_slots": [
                {"slot_id": slot["id"], "containers": []}
                for slot in _transfer_slots()
            ],
        },
        "jobs": jobs,
    }
    metadata = {
        "initial_container_count": len(container_states),
        "occupied_stack_count": len(initial_stacks),
        "direct_blocker_count": blocker_count,
        "background_stack_count": background_stack_count,
    }
    return payload, metadata


def _outbound_stacks(rng: random.Random) -> list[tuple[int, int]]:
    seaside = _sample_stacks(rng, 7, set(), bay_range=range(1, HANDSHAKE_BAY))
    landside = _sample_stacks(
        rng,
        7,
        set(seaside),
        bay_range=range(HANDSHAKE_BAY + 1, BAYS + 1),
    )
    middle_row = rng.randint(1, ROWS)
    return seaside + [(HANDSHAKE_BAY, middle_row)] + landside


def _sample_stacks(
    rng: random.Random,
    count: int,
    reserved: set[tuple[int, int]],
    *,
    exclude_bay: int | None = None,
    bay_range: range = range(1, BAYS + 1),
) -> list[tuple[int, int]]:
    candidates = [
        (bay, row)
        for bay in bay_range
        for row in range(1, ROWS + 1)
        if (bay, row) not in reserved and bay != exclude_bay
    ]
    return rng.sample(candidates, count)


def _job(
    *,
    job_id: str,
    container_id: str,
    direction: str,
    origin: tuple[int, int],
    destination: tuple[int, int],
    final_tier: int | None = None,
    block_id: str | None = None,
) -> dict[str, object]:
    final_slot = None
    if final_tier is not None and block_id is not None:
        final_slot = {
            "block_id": block_id,
            "bay": destination[0],
            "row": destination[1],
            "tier": final_tier,
        }
    return {
        "id": job_id,
        "container_id": container_id,
        "direction": direction,
        "origin": {"bay": origin[0], "row": origin[1]},
        "destination": {"bay": destination[0], "row": destination[1]},
        "final_slot": final_slot,
        "release_time": 0.0,
        "agv_ready_time": 0.0,
    }


def _container_states(
    block_id: str,
    initial_stacks: list[dict[str, object]],
    inbound_jobs: list[dict[str, object]],
) -> list[dict[str, object]]:
    states: list[dict[str, object]] = []
    for stack in initial_stacks:
        containers = stack["containers"]
        assert isinstance(containers, list)
        for tier, container_id in enumerate(containers, start=1):
            states.append(
                {
                    "container_id": container_id,
                    "status": "IN_STACK",
                    "current_slot": {
                        "block_id": block_id,
                        "bay": stack["bay"],
                        "row": stack["row"],
                        "tier": tier,
                    },
                    "target_slot": None,
                }
            )
    for job in inbound_jobs:
        states.append(
            {
                "container_id": job["container_id"],
                "status": "ON_AGV",
                "current_slot": None,
                "target_slot": job["final_slot"],
            }
        )
    return states


def _transfer_slots() -> list[dict[str, object]]:
    slots = [
        {
            "id": f"H_B{HANDSHAKE_BAY}_R{row}",
            "position": {"bay": HANDSHAKE_BAY, "row": row},
            "capacity": 1,
            "enabled": True,
            "kind": "STACK_BACKED",
        }
        for row in range(1, ROWS + 1)
    ]
    slots.extend(
        {
            "id": f"ALT_B{bay}_R{row}",
            "position": {"bay": bay, "row": row},
            "capacity": 1,
            "enabled": True,
        }
        for bay, row in ((6, 1), (6, 3), (14, 2), (14, 4))
    )
    return slots


def _layout_fingerprint(payload: dict[str, object]) -> str:
    state = payload["initial_state"]
    assert isinstance(state, dict)
    jobs = payload["jobs"]
    return json.dumps(
        {"stacks": state["stacks"], "jobs": jobs},
        sort_keys=True,
        separators=(",", ":"),
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _readme() -> str:
    return r"""# 22 Block Instance Set

This directory contains 22 deterministic, distinct yard-block instances.

- Layout: 20 bays, 10 rows, 6 tiers
- Jobs per block: 15 outbound and 5 inbound
- Initial state: scheduled containers, support containers, blockers, and background stacks
- Handover bay: bay 10; each row uses the actual stack top as its transfer point
- Existing Bay 10 containers remain in place; handover uses the next free tier up to tier 6
- Motion and physical rules: identical across all blocks
- Variation: job stacks, rows, tiers, blocker counts, inbound destinations, and background occupancy

`manifest.json` records each seed and structural count. Run all three policies with:

```powershell
.\.venv\Scripts\python.exe scripts\run_22_block_batch.py
```
"""


if __name__ == "__main__":
    raise SystemExit(main())
