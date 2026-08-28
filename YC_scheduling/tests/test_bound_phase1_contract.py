from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    BoundCalculationRequest,
    BoundCalculationResult,
    BoundRequestError,
    CooperationPolicy,
    JobSubsetError,
    derive_bound_scenario,
    derive_job_subset_instance,
    load_instance,
)


class BoundPhaseOneContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.instance = load_instance(
            ROOT / "data" / "static_fair_micro.json"
        )
        self.existing_id = "JOB_IN_NEAR"
        self.new_id = "JOB_OUT_FAR"

    def _request(self, **changes) -> BoundCalculationRequest:
        values = {
            "instance": self.instance,
            "policy": CooperationPolicy.HANDSHAKE_AREA,
            "existing_job_ids": (self.existing_id,),
            "new_job_ids": (self.new_id,),
            "decision_time": 0.0,
        }
        values.update(changes)
        return BoundCalculationRequest(**values)

    def test_valid_request_classifies_every_job(self) -> None:
        request = self._request(
            existing_job_ids=[self.existing_id],
            new_job_ids=[self.new_id],
        )
        self.assertEqual(request.existing_job_ids, (self.existing_id,))
        self.assertEqual(request.new_job_ids, (self.new_id,))
        self.assertEqual(
            request.all_job_ids,
            (self.existing_id, self.new_id),
        )

    def test_scenario_preserves_physics_and_splits_only_jobs(self) -> None:
        request = self._request()
        scenario = derive_bound_scenario(request)
        self.assertEqual(
            tuple(job.id for job in scenario.existing_instance.jobs),
            (self.existing_id,),
        )
        self.assertEqual(
            tuple(job.id for job in scenario.new_instance.jobs),
            (self.new_id,),
        )
        for subset in (
            scenario.existing_instance,
            scenario.new_instance,
        ):
            self.assertIs(subset.yard, self.instance.yard)
            self.assertIs(subset.motion, self.instance.motion)
            self.assertIs(subset.physical_rules, self.instance.physical_rules)
            self.assertIs(subset.cranes, self.instance.cranes)
            self.assertIs(subset.initial_state, self.instance.initial_state)
        self.assertEqual(len(self.instance.jobs), 2)

    def test_subset_uses_original_job_order(self) -> None:
        subset = derive_job_subset_instance(
            self.instance,
            (self.new_id, self.existing_id),
        )
        self.assertEqual(
            tuple(job.id for job in subset.jobs),
            (self.existing_id, self.new_id),
        )

    def test_pending_result_contains_identity_only(self) -> None:
        request = self._request(certified_existing_lower_bound=2.0)
        result = BoundCalculationResult.pending(request)
        self.assertEqual(result.instance_id, self.instance.instance_id)
        self.assertIs(result.policy, CooperationPolicy.HANDSHAKE_AREA)
        self.assertIsNone(result.strict_append_upper_bound)
        self.assertIsNone(result.combined_lower_bound)
        self.assertIsNone(result.append_valid)
        self.assertFalse(result.upper_bound_validated)
        self.assertFalse(result.lower_bound_certified)

    def test_request_rejects_overlap(self) -> None:
        with self.assertRaisesRegex(BoundRequestError, "overlap"):
            self._request(new_job_ids=(self.existing_id, self.new_id))

    def test_request_rejects_duplicate_ids(self) -> None:
        with self.assertRaisesRegex(BoundRequestError, "must be unique"):
            self._request(
                existing_job_ids=(self.existing_id, self.existing_id)
            )

    def test_request_rejects_unknown_and_unclassified_jobs(self) -> None:
        with self.assertRaisesRegex(BoundRequestError, "unknown jobs"):
            self._request(new_job_ids=("UNKNOWN_JOB",))
        with self.assertRaisesRegex(BoundRequestError, "missing"):
            self._request(existing_job_ids=(), new_job_ids=(self.new_id,))

    def test_request_requires_existing_and_new_work(self) -> None:
        with self.assertRaisesRegex(BoundRequestError, "existing job"):
            self._request(existing_job_ids=(), new_job_ids=(self.new_id,))
        with self.assertRaisesRegex(BoundRequestError, "new job"):
            self._request(
                existing_job_ids=(self.existing_id, self.new_id),
                new_job_ids=(),
            )

    def test_request_rejects_invalid_time_policy_and_bound(self) -> None:
        with self.assertRaisesRegex(BoundRequestError, "decision_time"):
            self._request(decision_time=math.nan)
        with self.assertRaisesRegex(BoundRequestError, "CooperationPolicy"):
            self._request(policy="HANDSHAKE_AREA")
        with self.assertRaisesRegex(
            BoundRequestError,
            "certified_existing_lower_bound",
        ):
            self._request(certified_existing_lower_bound=-1.0)

    def test_subset_rejects_empty_duplicate_and_unknown_ids(self) -> None:
        with self.assertRaisesRegex(JobSubsetError, "must not be empty"):
            derive_job_subset_instance(self.instance, ())
        with self.assertRaisesRegex(JobSubsetError, "must be unique"):
            derive_job_subset_instance(
                self.instance,
                (self.existing_id, self.existing_id),
            )
        with self.assertRaisesRegex(JobSubsetError, "unknown jobs"):
            derive_job_subset_instance(self.instance, ("UNKNOWN_JOB",))


if __name__ == "__main__":
    unittest.main()

