# Reproduction checklist

Legend: `[x]` complete, `[ ]` pending, `[!]` blocked by unpublished information or an explicit project decision.

## 1. Source control and provenance

- [x] Record paper title, authors, venue, year, pages, and DOI.
- [x] Keep the licensed PDF outside Git tracking through `.gitignore`.
- [x] Separate paper facts from reconstruction assumptions.
- [x] Commit this Phase 0 scaffold.
- [ ] Record every future run's commit SHA and asset hashes.

## 2. Environment

- [x] Select SUMO 1.27.1 as an explicit reconstruction version; the paper does not publish one.
- [x] Install the official SUMO application wheel and confirm `sumo`, `sumo-gui`, `netconvert`, and `netgenerate` report 1.27.1.
- [x] Create a project-local CPython 3.13.13 virtual environment with `uv`.
- [x] Install matching `sumo-data`, `traci`, and `sumolib` 1.27.1.
- [x] Commit the exact `uv.lock` dependency and artifact hashes.
- [x] Pin the setuptools build backend used for the editable project install.
- [x] Add a verifier for Windows AMD64, Python, uv, lock hash, packages, binaries, import ownership, and conflicting `SUMO_HOME` values.
- [ ] Save Python, SUMO, OS, and dependency versions with every experiment.

## 3. Network reconstruction

- [x] Record four-by-five grid, 20 intersections, and 54 directed roads.
- [x] Record 45-300 m road-length range.
- [x] Record single-lane, longitudinal two-way, and mostly lateral one-way rules.
- [x] Record two HDV gates and internal CAV-only operating area.
- [!] Reconstruct exact node coordinates from Fig. 6; original coordinates are unavailable.
- [!] Reconstruct edge directions and lengths; original edge table is unavailable.
- [x] Declare reconstruction coordinates, directions, lengths, gate-count convention, and their non-paper status.
- [x] Define legal non-U-turn movements and one-incoming-approach virtual phases for all intersections.
- [x] Validate each controlled link belongs to exactly one phase, no phase mixes incoming approaches, and no active movement pair is marked as foes by SUMO.
- [x] Validate strong connectivity of the directed network and reachability of every demand-generator OD candidate.
- [x] Save manifest, source `.nod.xml`, `.edg.xml`, `.con.xml`, `.tll.xml`, metadata, and generation command.
- [x] Verify deterministic rebuild equality for the 20-intersection/54-road network.
- [x] Build the separate one-intersection smoke network from committed PlainXML and verify its generated topology.

## 4. Vehicle and demand model

- [x] Record CAV maximum speed 14 m/s.
- [x] Record HDV maximum speed range 9-12 m/s.
- [x] Record demand levels 1600, 2000, and 2400 vehicles/h.
- [x] Record HDV alternative-route probability 20%.
- [x] Record main HDV penetration 10% and sweep 20%, 30%, and 50%.
- [!] Reconstruct the authors' five-minute progressive loading process; paper description and original demand files are incomplete.
- [!] Choose unpublished acceleration, deceleration, length, gap, and car-following parameters.
- [x] Implement deterministic OD generator with explicit baseline seed `1`.
- [x] Implement gate-to-internal and internal-to-gate HDV trips with balanced OD gate/direction quotas.
- [x] Implement distinct internal-to-internal CAV trips.
- [x] Implement 24 exact cumulative-floor loading bins with evenly spaced midpoint departures.
- [x] Verify generated aggregate count, bin quotas, class counts, penetration, speed-type balance, OD constraints, reachability, and initial shortest routes numerically.
- [x] Save deterministic route assets and metadata with configuration, network, and output hashes.
- [ ] Verify observed departure rate and penetration in a full live SUMO run.
- [ ] Apply and verify the HDV 20% alternative-road choice at each intersection at runtime.

## 5. BP/VTR intersection control

- [x] Transcribe equations (1)-(7).
- [x] Specify Algorithm 1 and Algorithm 2 interpretation.
- [x] Select reconstruction cycle length `T = 30 s`; the paper provides this only as an example.
- [x] Select reconstruction HDV extension increment `tau_bar = 1 s`; the paper does not provide it.
- [x] Implement compatible queue and downstream-capacity units.
- [x] Implement phase pressure and weights.
- [x] Separate continuous equation (5) durations from discrete execution quantization.
- [x] Implement duration allocation with deterministic rounding and a one-step minimum for every positive phase.
- [x] Reject cycles with fewer steps than positive-weight phases.
- [x] Implement clockwise ring state from previous token holder.
- [x] Implement HDV-led priority.
- [x] Implement descending-weight ordering for remaining phases.
- [x] Implement uncapped paper-fidelity HDV duration extension and an optional traced safety cap.
- [x] Use post-step queue-leader observations at Algorithm 1 boundaries.
- [x] Split zero-clearance paper fidelity from optional deterministic safety clearance; enforce the zero-clearance profile in the smoke adapter.
- [x] Omit zero-duration holders and preserve the previous holder for an all-zero idle cycle.
- [x] Prove no duplicate station and no overlapping active phase in the pure controller.
- [x] Prove repeated-cycle holder handoff adds no duplicate leading clearance.
- [x] Report nominal service budget separately from actual elapsed cycle time.
- [x] Reproduce paper example `{1/3, 1/2, 1/6}`, `T=30`, durations `{10,15,5}`.

## 6. IR-BP CAV routing

- [x] Transcribe equations (8)-(17) and Algorithm 3.
- [x] Implement live candidate downstream-edge discovery for the smoke adapter; general paper-network discovery remains future work.
- [x] Implement occupied-road travel-time estimate using the paper prose's literal remaining-distance interpretation.
- [!] Resolve equation (8)'s remaining-distance versus upstream-lane-position contradiction through a sensitivity test before claiming numerical fidelity.
- [x] Implement empty-road behavior for equation (8) as configured free-flow time.
- [x] Implement zero-speed floor `0.1 m/s` for equation (8).
- [x] Implement pressure weight.
- [x] Implement Euclidean heuristic against the configured trip arrival position.
- [x] Verify reconstructed paper-grid source edge lengths equal Euclidean endpoint distance.
- [ ] Verify the Euclidean heuristic is admissible for configured trip arrival positions in the full paper-grid runner.
- [x] Implement cumulative actual-distance cost.
- [x] Implement eta eligibility mask.
- [x] Implement deterministic tie-breaking.
- [x] Implement eta depletion as immutable per-trip input/output state.
- [x] Apply a traced legality/reachability precheck when reconstructing the Algorithm 3 candidate set.
- [x] Verify the smoke TraCI route begins on the current edge, uses a reachable SUMO suffix, is accepted, and reaches the destination.
- [x] Verify eta never becomes negative.

## 7. SUMO integration

- [x] Build one-intersection smoke scenario.
- [x] Implement TraCI subscriptions for vehicles, lanes, and signals in the smoke adapter.
- [x] Implement virtual TLS enforcement of VTR phases in the smoke adapter.
- [x] Implement legal CAV route replacement before the route split.
- [x] Record phase and routing decisions in a deterministic smoke trace.
- [x] Verify two fixed-seed smoke runs give identical normalized traces.
- [x] Build and structurally validate the full 20-intersection SUMO network.
- [x] Build and statically validate seeded baseline demand for the full network.
- [ ] Run the full 20-intersection scenario without collision or deadlock.
- [ ] Continue beyond the `7200 s` departure horizon until the network drains, with a declared timeout and incomplete-run failure.

## 8. Metrics

- [!] Choose and document queue-length-in-meters definition.
- [ ] Record cumulative network queue length per step.
- [ ] Record per-trip travel time, distance, waiting time, and speed.
- [ ] Verify units against paper labels.
- [ ] Exclude warm-up traffic only through explicit configuration.
- [ ] Save raw metrics separately from summaries.

## 9. Experiment matrix

- [ ] Eta sweep: 100, 200, 400, 500, 600, 700, 800, 1000.
- [ ] Demand sweep: 1600, 2000, 2400 vehicles/h at 10% HDV.
- [ ] HDV sweep: 20%, 30%, 50% at 2000 vehicles/h.
- [ ] Eight case-study OD scenarios.
- [ ] Multiple seeds per stochastic scenario.
- [ ] FX-STR baseline.
- [ ] MC-BP baseline.
- [ ] AR-BP baseline.
- [ ] MCSR-like baseline.
- [!] Resolve paper's `DSP` versus `MCSR` terminology mismatch.

## 10. Validation and reporting

- [x] Unit tests for equations (1)-(17), Algorithms 1-3, seeded demand generation, and selected declared edge cases.
- [x] Pure-Python integration test for one BP/VTR intersection cycle.
- [x] End-to-end deterministic SUMO/TraCI smoke test.
- [ ] Confirm larger eta tends to reduce queueing and increase distance.
- [ ] Confirm travel-time response can be non-monotonic.
- [ ] Compare reconstructed results with Figs. 7-14.
- [ ] Compare eight cases with Table I.
- [ ] Report absolute and relative error, seed count, mean, and dispersion.
- [ ] Label calibrated results as reconstructed, never original.
- [ ] Document every deviation from the paper.

## 11. Phase 0 completion criteria

- [x] Paper analysis exists.
- [x] Implementation specification exists.
- [x] Python/SUMO project boundaries exist.
- [x] Reproduction checklist exists.
- [x] Licensed PDF is ignored by the project.
- [x] User reviews and authorizes Phase 1 assumption selection and BP/VTR implementation.
