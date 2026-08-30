# Reproduction checklist

Legend: `[x]` complete, `[ ]` pending, `[!]` blocked by unpublished information or an explicit project decision.

## 1. Source control and provenance

- [x] Record paper title, authors, venue, year, pages, and DOI.
- [x] Keep the licensed PDF outside Git tracking through `.gitignore`.
- [x] Separate paper facts from reconstruction assumptions.
- [x] Commit this Phase 0 scaffold.
- [ ] Record every future run's commit SHA and asset hashes.

## 2. Environment

- [!] Select SUMO version; paper does not publish one.
- [ ] Install SUMO and confirm `sumo --version` and `sumo-gui --version`.
- [ ] Create Python virtual environment.
- [ ] Install matching `traci` and `sumolib`.
- [ ] Add and lock Python dependencies after first end-to-end run.
- [ ] Save Python, SUMO, OS, and dependency versions with every experiment.

## 3. Network reconstruction

- [x] Record four-by-five grid, 20 intersections, and 54 directed roads.
- [x] Record 45-300 m road-length range.
- [x] Record single-lane, longitudinal two-way, and mostly lateral one-way rules.
- [x] Record two HDV gates and internal CAV-only operating area.
- [!] Reconstruct exact node coordinates from Fig. 6; original coordinates are unavailable.
- [!] Reconstruct edge directions and lengths; original edge table is unavailable.
- [ ] Define conflict-free movements and phases for all intersections.
- [ ] Validate exactly one active phase per intersection.
- [ ] Validate all OD pairs are connected.
- [ ] Save source `.nod.xml`, `.edg.xml`, `.con.xml`, and generation command.

## 4. Vehicle and demand model

- [x] Record CAV maximum speed 14 m/s.
- [x] Record HDV maximum speed range 9-12 m/s.
- [x] Record demand levels 1600, 2000, and 2400 vehicles/h.
- [x] Record HDV alternative-route probability 20%.
- [x] Record main HDV penetration 10% and sweep 20%, 30%, and 50%.
- [!] Define five-minute progressive loading process; paper description is incomplete.
- [!] Choose unpublished acceleration, deceleration, length, gap, and car-following parameters.
- [ ] Implement deterministic OD generator with explicit seed.
- [ ] Implement gate-to-internal and internal-to-gate HDV trips.
- [ ] Implement internal-to-internal CAV trips.
- [ ] Verify generated demand rate and penetration numerically.

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
- [x] Split zero-clearance paper fidelity from optional deterministic safety clearance; TraCI enforcement remains pending.
- [x] Omit zero-duration holders and preserve the previous holder for an all-zero idle cycle.
- [x] Prove no duplicate station and no overlapping active phase in the pure controller.
- [x] Prove repeated-cycle holder handoff adds no duplicate leading clearance.
- [x] Report nominal service budget separately from actual elapsed cycle time.
- [x] Reproduce paper example `{1/3, 1/2, 1/6}`, `T=30`, durations `{10,15,5}`.

## 6. IR-BP CAV routing

- [x] Transcribe equations (8)-(17) and Algorithm 3.
- [ ] Implement candidate downstream-edge discovery.
- [x] Implement occupied-road travel-time estimate using the paper prose's literal remaining-distance interpretation.
- [!] Resolve equation (8)'s remaining-distance versus upstream-lane-position contradiction through a sensitivity test before claiming numerical fidelity.
- [x] Implement empty-road behavior for equation (8) as configured free-flow time.
- [x] Implement zero-speed floor `0.1 m/s` for equation (8).
- [x] Implement pressure weight.
- [x] Implement Euclidean heuristic against the configured trip arrival position.
- [ ] Verify that the Euclidean heuristic is admissible for reconstructed edge lengths and arrival positions.
- [x] Implement cumulative actual-distance cost.
- [x] Implement eta eligibility mask.
- [x] Implement deterministic tie-breaking.
- [x] Implement eta depletion as immutable per-trip input/output state.
- [x] Apply a traced legality/reachability precheck when reconstructing the Algorithm 3 candidate set.
- [ ] Verify TraCI-applied routes remain SUMO-legal and reach the destination.
- [x] Verify eta never becomes negative.

## 7. SUMO integration

- [ ] Build one-intersection smoke scenario.
- [ ] Implement TraCI subscriptions for vehicles, lanes, and signals.
- [ ] Implement virtual TLS enforcement of VTR phases.
- [ ] Implement legal CAV route replacement before intersection entry.
- [ ] Record phase and routing decisions.
- [ ] Verify fixed seed gives identical decision traces.
- [ ] Run the full 20-intersection scenario without collision or deadlock.

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

- [x] Unit tests for equations (1)-(17), Algorithms 1-3, and selected declared edge cases.
- [x] Pure-Python integration test for one BP/VTR intersection cycle; SUMO integration remains pending.
- [ ] End-to-end deterministic smoke test.
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
