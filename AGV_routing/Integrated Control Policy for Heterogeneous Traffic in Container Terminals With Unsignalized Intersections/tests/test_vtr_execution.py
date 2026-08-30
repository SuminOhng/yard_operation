from __future__ import annotations

import unittest
from collections import Counter

from irbp_replica.control.execution import VTRCycleExecutor
from irbp_replica.control.vtr import (
    TokenSlot,
    build_cycle_plan,
    validate_single_activation,
)
from irbp_replica.domain.models import PhaseState, RoadState


def paper_plan() -> tuple[TokenSlot, ...]:
    roads = {
        "l_ij": RoadState("l_ij", 100, 2, 0),
        "l_nj": RoadState("l_nj", 100, 3, 0),
        "l_mj": RoadState("l_mj", 100, 1, 0),
        "l_jk": RoadState("l_jk", 100, 0, 10),
        "l_jn": RoadState("l_jn", 100, 0, 10),
        "l_jm": RoadState("l_jm", 100, 0, 10),
    }
    return build_cycle_plan(paper_phases(), roads, "s_ij", 30, 1)


def paper_phases() -> tuple[PhaseState, ...]:
    return (
        PhaseState("p_ij", "s_ij", "l_ij", ("l_jk",), 0, "HDV"),
        PhaseState("p_nj", "s_nj", "l_nj", ("l_jn",), 1, "CAV"),
        PhaseState("p_mj", "s_mj", "l_mj", ("l_jm",), 2, "CAV"),
    )


class VTRCycleExecutionTests(unittest.TestCase):
    def test_paper_plan_runs_with_hdv_extension_and_clearance(self) -> None:
        executor = VTRCycleExecutor(
            paper_plan(),
            "s_ij",
            step_length_s=1,
            extension_increment_s=1,
            maximum_extension_s=30,
            clearance_time_s=1,
        )
        trace = []
        while not executor.is_complete:
            snapshot = executor.snapshot()
            trace.append(snapshot)
            queue_leader = None
            if snapshot.active_phase_id == "p_ij" and snapshot.time_remaining_s == 1:
                queue_leader = "HDV" if snapshot.extension_used_s == 0 else "CAV"
            executor.advance(queue_leader)

        active_counts = Counter(
            snapshot.active_phase_id
            for snapshot in trace
            if snapshot.mode == "ACTIVE"
        )
        self.assertEqual(active_counts, {"p_ij": 11, "p_nj": 15, "p_mj": 5})
        self.assertEqual(sum(snapshot.mode == "CLEARANCE" for snapshot in trace), 3)
        self.assertEqual(executor.snapshot().time_s, 34)
        self.assertEqual(executor.last_completed_station_id, "s_mj")

        phases = paper_phases()
        for snapshot in trace:
            if snapshot.mode == "ACTIVE":
                validate_single_activation(
                    phases,
                    (snapshot.active_phase_id,),
                    (snapshot.token_station_id,),
                )
            else:
                self.assertIsNone(snapshot.active_phase_id)
                self.assertIsNone(snapshot.token_station_id)

    def test_cav_at_expiry_prevents_extension(self) -> None:
        executor = VTRCycleExecutor(
            (TokenSlot("p", "s", 1, 2, False),),
            "previous",
            step_length_s=1,
            extension_increment_s=1,
            maximum_extension_s=30,
            clearance_time_s=0,
        )
        executor.advance(None)
        executor.advance("CAV")
        self.assertTrue(executor.is_complete)
        self.assertEqual(executor.snapshot().time_s, 2)

    def test_hdv_extension_stops_at_safety_cap(self) -> None:
        executor = VTRCycleExecutor(
            (TokenSlot("p", "s", 1, 1, True),),
            "previous",
            step_length_s=1,
            extension_increment_s=1,
            maximum_extension_s=2,
            clearance_time_s=0,
        )
        while not executor.is_complete:
            executor.advance("HDV")
        self.assertEqual(executor.snapshot().time_s, 3)

    def test_zero_duration_station_is_passed_without_activation(self) -> None:
        executor = VTRCycleExecutor(
            (
                TokenSlot("zero", "s_zero", 0, 0, True),
                TokenSlot("active", "s_active", 1, 1, False),
            ),
            "previous",
            step_length_s=1,
            extension_increment_s=1,
            maximum_extension_s=0,
            clearance_time_s=0,
        )
        self.assertEqual(executor.snapshot().active_phase_id, "active")
        self.assertEqual(executor.last_completed_station_id, "s_zero")
        executor.advance(None)
        self.assertEqual(executor.last_completed_station_id, "s_active")

    def test_non_step_aligned_duration_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            VTRCycleExecutor(
                (TokenSlot("p", "s", 1, 1.5, False),),
                "previous",
                step_length_s=1,
                extension_increment_s=1,
                maximum_extension_s=0,
                clearance_time_s=0,
            )

    def test_completed_cycle_cannot_advance(self) -> None:
        executor = VTRCycleExecutor(
            (),
            "previous",
            step_length_s=1,
            extension_increment_s=1,
            maximum_extension_s=0,
            clearance_time_s=0,
        )
        self.assertTrue(executor.is_complete)
        with self.assertRaises(RuntimeError):
            executor.advance(None)


if __name__ == "__main__":
    unittest.main()
