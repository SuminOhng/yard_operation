from __future__ import annotations

import json
import sys
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    ContainerStatus,
    MoveDirection,
    TransferSlotKind,
    load_instance,
)


class TwentyTwoBlockInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data_dir = ROOT / "data" / "blocks_22_stack_h"
        cls.manifest = json.loads(
            (cls.data_dir / "manifest.json").read_text(encoding="utf-8")
        )
        cls.instances = [
            load_instance(cls.data_dir / entry["instance_file"])
            for entry in cls.manifest["instances"]
        ]

    def test_set_contains_22_distinct_blocks(self) -> None:
        self.assertEqual(len(self.instances), 22)
        self.assertEqual(len({item.instance_id for item in self.instances}), 22)
        self.assertEqual(len({item.layout.block_id for item in self.instances}), 22)

    def test_each_block_has_requested_shape_and_job_mix(self) -> None:
        for instance in self.instances:
            self.assertEqual(
                (instance.layout.bays, instance.layout.rows, instance.layout.tiers),
                (20, 10, 6),
            )
            self.assertEqual(
                Counter(job.direction for job in instance.jobs),
                Counter({MoveDirection.OUTBOUND: 15, MoveDirection.INBOUND: 5}),
            )

    def test_each_block_has_initial_occupancy_and_direct_blockers(self) -> None:
        for instance in self.instances:
            stacked = {
                state.container_id: state
                for state in instance.initial_state.containers
                if state.status is ContainerStatus.IN_STACK
            }
            self.assertGreaterEqual(len(stacked), 65)
            blocked_jobs = 0
            for job in instance.jobs:
                if job.direction is not MoveDirection.OUTBOUND:
                    continue
                state = stacked[job.container_id]
                stack = instance.initial_state.stacks_by_key[state.current_slot.stack_key]
                if stack.top_container != job.container_id:
                    blocked_jobs += 1
            self.assertGreaterEqual(blocked_jobs, 6)

    def test_h_area_uses_existing_stack_tops_within_capacity(self) -> None:
        for instance in self.instances:
            h_points = tuple(
                point
                for point in instance.yard.transfer_slots
                if point.position.bay == instance.layout.handshake_bay
            )
            self.assertEqual(len(h_points), 10)
            self.assertTrue(
                all(
                    point.kind is TransferSlotKind.STACK_BACKED
                    and point.uses_stack_storage
                    for point in h_points
                )
            )
            h_stacks = tuple(
                stack
                for stack in instance.initial_state.stacks
                if stack.key.bay == instance.layout.handshake_bay
            )
            self.assertTrue(any(stack.containers for stack in h_stacks))
            self.assertTrue(
                all(len(stack.containers) <= instance.layout.tiers for stack in h_stacks)
            )


if __name__ == "__main__":
    unittest.main()
