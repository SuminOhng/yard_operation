from __future__ import annotations

import unittest
from collections import Counter

from irbp_replica.control.execution import VTRCycleExecutor
from irbp_replica.control.vtr import (
    TokenSlot,
    build_cycle_plan,
    clockwise_phases_after,
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
    def test_paper_fidelity_plan_has_one_activation_at_every_service_step(self) -> None:
        executor = VTRCycleExecutor(
            paper_plan(),
            "s_ij",
            step_length_s=1,
            extension_increment_s=1,
            maximum_extension_s=None,
            clearance_time_s=0,
        )
        trace = []
        while not executor.is_complete:
            snapshot = executor.snapshot()
            trace.append(snapshot)
            post_step_queue_leader = None
            if snapshot.active_phase_id == "p_ij" and snapshot.time_remaining_s == 1:
                post_step_queue_leader = (
                    "HDV" if snapshot.extension_used_s == 0 else "CAV"
                )
            executor.advance_after_step(
                post_step_queue_leader=post_step_queue_leader
            )

        active_counts = Counter(
            snapshot.active_phase_id
            for snapshot in trace
            if snapshot.mode == "ACTIVE"
        )
        self.assertEqual(active_counts, {"p_ij": 11, "p_nj": 15, "p_mj": 5})
        self.assertEqual(sum(snapshot.mode == "CLEARANCE" for snapshot in trace), 0)
        self.assertEqual(executor.nominal_service_budget_s, 30)
        self.assertEqual(executor.actual_cycle_duration_s, 31)
        self.assertEqual(executor.snapshot().cycle_extension_used_s, 1)
        self.assertEqual(executor.last_completed_station_id, "s_mj")

        phases = paper_phases()
        for snapshot in trace:
            validate_single_activation(
                phases,
                (snapshot.active_phase_id,),
                (snapshot.token_station_id,),
            )

    def test_safety_clearance_is_all_red_outside_equations_6_and_7(self) -> None:
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
            post_step_queue_leader = None
            if snapshot.active_phase_id == "p_ij" and snapshot.time_remaining_s == 1:
                post_step_queue_leader = (
                    "HDV" if snapshot.extension_used_s == 0 else "CAV"
                )
            executor.advance_after_step(
                post_step_queue_leader=post_step_queue_leader
            )

        clearance = [snapshot for snapshot in trace if snapshot.mode == "CLEARANCE"]
        self.assertEqual(len(clearance), 3)
        self.assertTrue(
            all(
                snapshot.active_phase_id is None
                and snapshot.token_station_id is None
                for snapshot in clearance
            )
        )
        self.assertEqual(executor.actual_cycle_duration_s, 34)

    def test_post_step_leader_at_expiry_controls_extension(self) -> None:
        executor = VTRCycleExecutor(
            (TokenSlot("p", "s", 1, 2, False),),
            "previous",
            step_length_s=1,
            extension_increment_s=1,
            maximum_extension_s=30,
            clearance_time_s=0,
        )
        executor.advance_after_step(post_step_queue_leader="HDV")
        self.assertEqual(executor.snapshot().extension_used_s, 0)
        executor.advance_after_step(post_step_queue_leader="CAV")
        self.assertTrue(executor.is_complete)
        self.assertEqual(executor.snapshot().time_s, 2)
        self.assertEqual(executor.snapshot().boundary_outcome, "cav_leader")
        self.assertEqual(executor.snapshot().boundary_phase_id, "p")
        self.assertEqual(executor.snapshot().boundary_station_id, "s")

    def test_zero_clearance_boundary_event_names_the_completed_phase(self) -> None:
        executor = VTRCycleExecutor(
            (
                TokenSlot("p1", "s1", 1, 1, False),
                TokenSlot("p2", "s2", 1, 1, False),
            ),
            "previous",
            step_length_s=1,
            extension_increment_s=1,
        )
        snapshot = executor.advance_after_step(post_step_queue_leader=None)
        self.assertEqual(snapshot.active_phase_id, "p2")
        self.assertEqual(snapshot.boundary_outcome, "queue_empty")
        self.assertEqual(snapshot.boundary_phase_id, "p1")
        self.assertEqual(snapshot.boundary_station_id, "s1")

    def test_unlimited_fidelity_extension_stops_only_for_cav(self) -> None:
        executor = VTRCycleExecutor(
            (TokenSlot("p", "s", 1, 1, True),),
            "previous",
            step_length_s=1,
            extension_increment_s=1,
        )
        for _ in range(3):
            snapshot = executor.advance_after_step(post_step_queue_leader="HDV")
            self.assertEqual(snapshot.boundary_outcome, "extended")
        snapshot = executor.advance_after_step(post_step_queue_leader="CAV")
        self.assertTrue(executor.is_complete)
        self.assertEqual(snapshot.boundary_outcome, "cav_leader")
        self.assertEqual(snapshot.cycle_extension_used_s, 3)
        self.assertEqual(snapshot.actual_cycle_duration_s, 4)

    def test_hdv_extension_stops_at_safety_cap(self) -> None:
        executor = VTRCycleExecutor(
            (TokenSlot("p", "s", 1, 1, True),),
            "previous",
            step_length_s=1,
            extension_increment_s=1,
            maximum_extension_s=2,
            clearance_time_s=0,
        )
        executor.advance_after_step(post_step_queue_leader="HDV")
        executor.advance_after_step(post_step_queue_leader="HDV")
        snapshot = executor.advance_after_step(post_step_queue_leader="HDV")
        self.assertEqual(executor.snapshot().time_s, 3)
        self.assertEqual(snapshot.boundary_outcome, "extension_cap_hit")
        self.assertEqual(snapshot.boundary_phase_id, "p")
        self.assertEqual(snapshot.boundary_station_id, "s")
        self.assertEqual(snapshot.cycle_extension_used_s, 2)

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
        self.assertEqual(executor.last_completed_station_id, "previous")
        executor.advance_after_step(post_step_queue_leader=None)
        self.assertEqual(executor.last_completed_station_id, "s_active")

    def test_completed_holder_seeds_the_next_clockwise_cycle(self) -> None:
        executor = VTRCycleExecutor(
            paper_plan(),
            "s_ij",
            step_length_s=1,
            extension_increment_s=1,
        )
        while not executor.is_complete:
            executor.advance_after_step(post_step_queue_leader=None)
        next_order = clockwise_phases_after(
            paper_phases(),
            executor.last_completed_station_id,
        )
        self.assertEqual(
            tuple(phase.station_id for phase in next_order),
            ("s_ij", "s_nj", "s_mj"),
        )

    def test_cycle_handoff_does_not_add_leading_clearance(self) -> None:
        first = VTRCycleExecutor(
            (TokenSlot("p1", "s1", 1, 1, False),),
            "previous",
            step_length_s=1,
            extension_increment_s=1,
            clearance_time_s=1,
        )
        first.advance_after_step(post_step_queue_leader=None)
        self.assertEqual(first.snapshot().mode, "CLEARANCE")
        first.advance_after_step(post_step_queue_leader=None)
        self.assertTrue(first.is_complete)

        second = VTRCycleExecutor(
            (TokenSlot("p2", "s2", 1, 1, False),),
            first.last_completed_station_id,
            step_length_s=1,
            extension_increment_s=1,
            clearance_time_s=1,
        )
        self.assertEqual(second.snapshot().mode, "ACTIVE")
        self.assertEqual(second.snapshot().time_s, 0)

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
        self.assertEqual(executor.last_completed_station_id, "previous")
        self.assertEqual(executor.actual_cycle_duration_s, 0)
        with self.assertRaises(RuntimeError):
            executor.advance_after_step(post_step_queue_leader=None)


if __name__ == "__main__":
    unittest.main()
