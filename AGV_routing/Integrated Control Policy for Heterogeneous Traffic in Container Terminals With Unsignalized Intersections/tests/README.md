# Test status

Implemented Phase 1 tests:

- `test_pressure.py`: equations (1)-(4), normalization, zero weights, and validation.
- `test_phase_time.py`: continuous equation (5), positive-preserving step quantization, stable largest-remainder allocation, and uncapped/capped Algorithm 1 behavior.
- `test_vtr.py`: Algorithm 2 ordering, uniqueness, multiple-HDV priority, clockwise ties, all-zero plans, the paper duration example, and equations (6)-(7).
- `test_vtr_execution.py`: post-step Algorithm 1 boundaries, paper-fidelity execution, optional safety clearance and cap events, zero-duration stations, nominal versus actual cycle time, and repeated-cycle handoff.

Later milestones will add:

- `test_irbp_routing.py`: equations (8)-(17), masks, ties, eta depletion, and edge cases.
- `test_traci_smoke.py`: one-intersection integration scenario.
- `test_reproducibility.py`: identical traces under the same seed.
