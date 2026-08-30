# Test status

Implemented Phase 1 tests:

- `test_pressure.py`: equations (1)-(4), normalization, zero weights, and validation.
- `test_phase_time.py`: equation (5), largest-remainder rounding, and Algorithm 1 stop/cap behavior.
- `test_vtr.py`: Algorithm 2 ordering, uniqueness, HDV priority, clockwise ties, the paper duration example, and equations (6)-(7).
- `test_vtr_execution.py`: one-cycle token execution, Algorithm 1 boundary checks, clearance, safety cap, zero-duration stations, and a deterministic one-intersection trace.

Later milestones will add:

- `test_irbp_routing.py`: equations (8)-(17), masks, ties, eta depletion, and edge cases.
- `test_traci_smoke.py`: one-intersection integration scenario.
- `test_reproducibility.py`: identical traces under the same seed.
