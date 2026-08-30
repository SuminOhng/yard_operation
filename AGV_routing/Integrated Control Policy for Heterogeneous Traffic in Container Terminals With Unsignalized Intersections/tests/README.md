# Test status

Implemented Phase 1 tests:

- `test_pressure.py`: equations (1)-(4), normalization, zero weights, and validation.
- `test_phase_time.py`: continuous equation (5), positive-preserving step quantization, stable largest-remainder allocation, and uncapped/capped Algorithm 1 behavior.
- `test_vtr.py`: Algorithm 2 ordering, uniqueness, multiple-HDV priority, clockwise ties, all-zero plans, the paper duration example, and equations (6)-(7).
- `test_vtr_execution.py`: post-step Algorithm 1 boundaries, paper-fidelity execution, optional safety clearance and cap events, zero-duration stations, nominal versus actual cycle time, and repeated-cycle handoff.
- `test_irbp_routing.py`: selected cases for equations (8)-(17) and Algorithm 3, including the literal remaining-distance interpretation of equation (8), occupied and empty roads, speed floors, Euclidean distance, eligibility, eta depletion, candidate prechecks, full decision traces, separate position/cost tolerances, stable ties, and invalid inputs.
- `test_traci_smoke.py`: two fixed-seed SUMO/TraCI runs covering live subscriptions, mutually exclusive VTR phase enforcement, post-step execution, downstream-candidate discovery, one verified route replacement and eta commit, complete arrivals, and identical normalized traces.
- `test_paper_grid_network.py`: deterministic paper-grid generation, 20-node/54-road counts, single lanes, declared direction and length pattern, gate-count convention, strong connectivity, legal non-U-turn coverage, virtual-phase partition, generated SUMO-foe checks, manifest/config consistency, and generated-artifact equality.
- `test_paper_grid_demand.py`: deterministic seeded demand generation, exact departure-horizon/bin/class quotas, HDV OD gate and direction balance, HDV speed-type balance, CAV/HDV OD rules, route connectivity, shortest-distance initial routes, metadata hashes, and generated-artifact equality.
- `test_paper_baseline_config.py`: explicit full-run reconstruction assumptions, resolved drain timeout, baseline SUMO asset paths, deterministic timing/seed settings, and collision/deadlock exposure settings.
- `test_paper_grid_runner.py`: explicit runner parameters, strict seeded HDV threshold and stable candidate selection, revisited-edge encounter accounting, and a short live 20-intersection topology/termination gate.

Later milestones will add metrics, sensitivity profiles, and multi-seed reproducibility gates. The smoke test is an adapter proof; the live paper-grid runner currently exposes a seed-1 gridlock rather than establishing numerical agreement with the paper.
