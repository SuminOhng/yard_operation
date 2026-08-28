from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    CooperationPolicy,
    CraneSide,
    RouteKind,
    RouteMode,
    build_explicit_route_schedule,
    build_left_shifted_candidate,
    load_instance,
    route_reference_result_dict,
    solve_route_mode_reference,
)


class ReferenceConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.instance = load_instance(
            ROOT / "data" / "benchmarks" / "01_balanced_local_4jobs.json"
        )
        cls.order = tuple(job.id for job in cls.instance.jobs)
        cls.modes = (
            RouteMode("JOB_LOCAL_IN_SEA", RouteKind.DIRECT, CraneSide.SEASIDE),
            RouteMode("JOB_LOCAL_OUT_LAND", RouteKind.DIRECT, CraneSide.LANDSIDE),
            RouteMode("JOB_LOCAL_OUT_SEA", RouteKind.DIRECT, CraneSide.SEASIDE),
            RouteMode("JOB_LOCAL_IN_LAND", RouteKind.DIRECT, CraneSide.LANDSIDE),
        )

    def test_left_shift_overlaps_independent_crane_sequences(self) -> None:
        serial = build_explicit_route_schedule(
            self.instance,
            CooperationPolicy.NO_SHARING,
            self.order,
            self.modes,
        )
        concurrent = build_left_shifted_candidate(
            self.instance,
            CooperationPolicy.NO_SHARING,
            serial,
        )
        self.assertTrue(concurrent.validation.valid, concurrent.validation.issues)
        self.assertGreater(concurrent.shifted_operation_count, 0)
        self.assertLess(
            concurrent.validation.makespan,
            concurrent.original_makespan,
        )
        sequences = {
            sequence.crane_id: sequence.job_ids
            for sequence in concurrent.crane_sequences
        }
        self.assertEqual(
            sequences["C_SEA"],
            ("JOB_LOCAL_IN_SEA", "JOB_LOCAL_OUT_SEA"),
        )
        self.assertEqual(
            sequences["C_LAND"],
            ("JOB_LOCAL_OUT_LAND", "JOB_LOCAL_IN_LAND"),
        )

    def test_route_solver_records_concurrent_search_and_sequences(self) -> None:
        result = solve_route_mode_reference(
            self.instance,
            CooperationPolicy.NO_SHARING,
        )
        self.assertGreater(result.concurrent_candidate_count, 0)
        self.assertEqual(
            result.expected_candidate_count,
            result.planner_candidate_count
            + result.explicit_route_candidate_count
            + result.concurrent_candidate_count,
        )
        self.assertTrue(result.best_crane_job_sequences)
        payload = route_reference_result_dict(result)
        self.assertEqual(
            len(payload["best"]["crane_job_sequences"]),
            2,
        )


if __name__ == "__main__":
    unittest.main()
