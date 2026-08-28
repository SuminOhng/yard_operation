from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    CooperationPolicy,
    MoveDirection,
    load_instance,
    run_three_policy_comparison,
)


class LargeTwentyJobInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.instance = load_instance(
            ROOT / "data" / "large_15out_5in_seed42.json"
        )

    def test_instance_has_requested_layout_and_job_mix(self) -> None:
        instance = self.instance
        self.assertEqual((instance.layout.bays, instance.layout.rows), (20, 4))
        self.assertEqual(instance.layout.tiers, 4)
        self.assertEqual(instance.layout.handshake_bay, 10)
        self.assertEqual(
            instance.yard.enabled_transfer_bays,
            frozenset({6, 10, 14}),
        )
        self.assertEqual(
            Counter(job.direction for job in instance.jobs),
            Counter(
                {
                    MoveDirection.OUTBOUND: 15,
                    MoveDirection.INBOUND: 5,
                }
            ),
        )

    def test_every_policy_produces_a_physically_valid_schedule(self) -> None:
        comparison = run_three_policy_comparison(self.instance)
        self.assertEqual(
            tuple(record.policy for record in comparison.records),
            tuple(CooperationPolicy),
        )
        self.assertTrue(all(record.metrics.valid for record in comparison.records))
        self.assertTrue(
            all(record.metrics.feasible_upper_bound is not None for record in comparison.records)
        )

    def test_true_any_preserves_nested_handshake_fallback(self) -> None:
        comparison = run_three_policy_comparison(self.instance)
        records = {record.policy: record for record in comparison.records}
        no_sharing = records[CooperationPolicy.NO_SHARING]
        handshake = records[CooperationPolicy.HANDSHAKE_AREA]
        any_bay = records[CooperationPolicy.ANY_BAY]
        self.assertGreater(
            no_sharing.metrics.feasible_upper_bound,
            handshake.metrics.feasible_upper_bound,
        )
        self.assertGreaterEqual(
            handshake.metrics.feasible_upper_bound,
            any_bay.metrics.feasible_upper_bound,
        )
        self.assertEqual(handshake.metrics.handover_count, 9)
        self.assertEqual(any_bay.metrics.handover_count, 16)
        self.assertTrue(
            all(
                slot_id.startswith("VIRTUAL::B1::")
                for slot_id in any_bay.metrics.used_transfer_slot_ids
            )
        )


if __name__ == "__main__":
    unittest.main()
