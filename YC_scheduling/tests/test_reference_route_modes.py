from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yard_crane_v3 import (
    CooperationPolicy,
    ReferenceOptimalityScope,
    ReferenceSearchConfig,
    ReferenceSearchLimitError,
    RouteKind,
    RouteMode,
    allowed_route_modes,
    build_explicit_route_schedule,
    constraints_for,
    load_instance,
    parse_instance,
    route_reference_result_dict,
    solve_exhaustive_reference,
    solve_route_mode_reference,
    solve_three_policy_route_reference,
    validate_schedule,
)


class ExplicitRouteModeReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.instance = load_instance(ROOT / "data" / "static_fair_micro.json")

    def test_policy_route_spaces_are_nested(self) -> None:
        job = self.instance.jobs_by_id["JOB_OUT_FAR"]
        spaces = {
            policy: set(allowed_route_modes(self.instance, policy, job))
            for policy in CooperationPolicy
        }
        self.assertTrue(
            spaces[CooperationPolicy.NO_SHARING]
            <= spaces[CooperationPolicy.HANDSHAKE_AREA]
            <= spaces[CooperationPolicy.ANY_BAY]
        )
        self.assertEqual(
            sum(
                mode.kind is RouteKind.DIRECT
                for mode in spaces[CooperationPolicy.NO_SHARING]
            ),
            2,
        )
        self.assertTrue(
            all(
                mode.transfer_slot_id in {"H_ROW_1", "H_ROW_2"}
                for mode in spaces[CooperationPolicy.HANDSHAKE_AREA]
                if mode.kind is RouteKind.HANDOVER
            )
        )

    def test_any_reference_uses_virtual_point_outside_job_corridor(self) -> None:
        payload = json.loads(
            (ROOT / "data" / "static_fair_micro.json").read_text(
                encoding="utf-8"
            )
        )
        payload["jobs"] = [
            {
                "id": "JOB_NEAR_INBOUND",
                "container_id": "CONT_NEAR_INBOUND",
                "direction": "INBOUND",
                "origin": {"bay": 0, "row": 1},
                "destination": {"bay": 2, "row": 1},
                "final_slot": {
                    "block_id": "B1",
                    "bay": 2,
                    "row": 1,
                    "tier": 1,
                },
                "release_time": 0.0,
                "agv_ready_time": 0.0,
            }
        ]
        payload["initial_state"]["stacks"] = []
        payload["initial_state"]["containers"] = [
            {
                "container_id": "CONT_NEAR_INBOUND",
                "status": "ON_AGV",
                "current_slot": None,
                "target_slot": {
                    "block_id": "B1",
                    "bay": 2,
                    "row": 1,
                    "tier": 1,
                },
            }
        ]
        instance = parse_instance(payload)
        virtual_id = "VIRTUAL::B1::BAY_5::ROW_1"
        any_modes = allowed_route_modes(
            instance,
            CooperationPolicy.ANY_BAY,
            instance.jobs[0],
        )
        self.assertIn(
            RouteMode(
                "JOB_NEAR_INBOUND",
                RouteKind.HANDOVER,
                transfer_slot_id=virtual_id,
            ),
            any_modes,
        )

        schedule = build_explicit_route_schedule(
            instance,
            CooperationPolicy.ANY_BAY,
            ("JOB_NEAR_INBOUND",),
            (
                RouteMode(
                    "JOB_NEAR_INBOUND",
                    RouteKind.HANDOVER,
                    transfer_slot_id=virtual_id,
                ),
            ),
        )
        validation = validate_schedule(
            instance,
            constraints_for(instance, CooperationPolicy.ANY_BAY),
            schedule,
        )
        self.assertTrue(validation.valid, validation.issues)

    def test_no_sharing_enumerates_orders_and_direct_crane_assignments(self) -> None:
        result = solve_route_mode_reference(
            self.instance,
            CooperationPolicy.NO_SHARING,
        )
        self.assertEqual(result.permutation_count, 2)
        self.assertEqual(result.planner_candidate_count, 2)
        self.assertEqual(result.explicit_route_candidate_count, 8)
        self.assertEqual(result.concurrent_candidate_count, 8)
        self.assertEqual(result.expected_candidate_count, 18)
        self.assertEqual(result.evaluated_candidate_count, 18)
        self.assertEqual(
            result.feasible_candidate_count + result.infeasible_candidate_count,
            18,
        )
        self.assertTrue(result.optimal_within_scope)
        self.assertFalse(result.globally_optimal)
        self.assertIs(
            result.optimality_scope,
            ReferenceOptimalityScope.JOB_ORDER_ROUTES_POLICY_PLANNER_AND_LEFT_SHIFT,
        )
        self.assertTrue(
            all(mode.kind is RouteKind.DIRECT for mode in result.best_route_modes)
        )

    def test_best_explicit_route_schedule_passes_common_validator(self) -> None:
        result = solve_route_mode_reference(
            self.instance,
            CooperationPolicy.ANY_BAY,
        )
        validation = validate_schedule(
            self.instance,
            constraints_for(self.instance, CooperationPolicy.ANY_BAY),
            result.best_schedule,
        )
        self.assertTrue(validation.valid, validation.issues)
        self.assertEqual(set(result.best_job_order), set(self.instance.jobs_by_id))
        self.assertEqual(
            {mode.job_id for mode in result.best_route_modes},
            set(self.instance.jobs_by_id),
        )

    def test_route_search_never_regresses_job_order_reference(self) -> None:
        for policy in CooperationPolicy:
            with self.subTest(policy=policy.value):
                phase_one = solve_exhaustive_reference(self.instance, policy)
                phase_two = solve_route_mode_reference(self.instance, policy)
                self.assertLessEqual(
                    phase_two.best_makespan,
                    phase_one.best_makespan,
                )

    def test_three_policy_explicit_spaces_preserve_reference_lattice(self) -> None:
        result = solve_three_policy_route_reference(self.instance)
        self.assertTrue(result.nested_reference_bounds_hold)
        counts = {
            record.policy: record.expected_candidate_count
            for record in result.records
        }
        self.assertLessEqual(
            counts[CooperationPolicy.NO_SHARING],
            counts[CooperationPolicy.HANDSHAKE_AREA],
        )
        self.assertLessEqual(
            counts[CooperationPolicy.HANDSHAKE_AREA],
            counts[CooperationPolicy.ANY_BAY],
        )

    def test_route_candidate_limit_rejects_before_search(self) -> None:
        with self.assertRaisesRegex(ReferenceSearchLimitError, "was not started"):
            solve_route_mode_reference(
                self.instance,
                CooperationPolicy.NO_SHARING,
                config=ReferenceSearchConfig(maximum_route_candidates=17),
            )

    def test_route_result_serializes_decisions_and_scope(self) -> None:
        result = solve_route_mode_reference(
            self.instance,
            CooperationPolicy.NO_SHARING,
        )
        payload = route_reference_result_dict(result)
        json.dumps(payload, allow_nan=False)
        self.assertEqual(payload["search"]["evaluated_candidate_count"], 18)
        self.assertEqual(len(payload["best"]["route_modes"]), 2)
        self.assertIn(
            payload["best"]["candidate_source"],
            {"CURRENT_POLICY_PLANNER", "EXPLICIT_SERIAL_ROUTE"},
        )
        self.assertFalse(payload["certificate"]["globally_optimal"])


if __name__ == "__main__":
    unittest.main()
