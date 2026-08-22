from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import StackKey, parse_instance
from yard_crane_v3.planners.common import find_reshuffle_target
from yard_crane_v3.timing import TimeModel


class CommonReshuffleTests(unittest.TestCase):
    def setUp(self) -> None:
        payload = json.loads(
            (ROOT / "data" / "static_fair_micro.json").read_text(encoding="utf-8")
        )
        payload["motion"]["gantry_seconds_per_bay"] = 1.0
        payload["motion"]["trolley_seconds_per_row"] = 10.0
        self.instance = parse_instance(payload)
        self.source = StackKey("B1", 6, 1)
        self.stacks = {
            key: list(stack.containers)
            for key, stack in self.instance.initial_state.stacks_by_key.items()
        }

    def test_same_bay_is_preferred_even_when_another_bay_is_faster(self) -> None:
        state = SimpleNamespace(stacks=self.stacks)

        target = find_reshuffle_target(
            self.instance,
            state,
            TimeModel(self.instance.motion),
            self.source,
            range(4, 7),
            set(),
        )

        self.assertEqual((target.bay, target.row, target.tier), (6, 2, 1))

    def test_nearest_other_bay_is_used_when_same_bay_is_full(self) -> None:
        same_bay_alternative = StackKey("B1", 6, 2)
        capacity = self.instance.yard.stacks_by_key[same_bay_alternative].capacity
        self.stacks[same_bay_alternative] = [
            f"FULL_{tier}" for tier in range(1, capacity + 1)
        ]
        state = SimpleNamespace(stacks=self.stacks)

        target = find_reshuffle_target(
            self.instance,
            state,
            TimeModel(self.instance.motion),
            self.source,
            range(4, 7),
            set(),
        )

        self.assertEqual((target.bay, target.row, target.tier), (5, 1, 1))


if __name__ == "__main__":
    unittest.main()
