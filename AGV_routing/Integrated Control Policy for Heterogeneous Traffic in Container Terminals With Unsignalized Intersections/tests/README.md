# Test plan

Planned focused tests:

- `test_pressure.py`: equations (1)-(5), normalization, zero weights, and rounding.
- `test_phase_extension.py`: Algorithm 1 stop and extension conditions.
- `test_vtr.py`: Algorithm 2 ordering, uniqueness, HDV priority, and clockwise ties.
- `test_irbp_routing.py`: equations (8)-(17), masks, ties, eta depletion, and edge cases.
- `test_traci_smoke.py`: one-intersection integration scenario.
- `test_reproducibility.py`: identical traces under the same seed.
