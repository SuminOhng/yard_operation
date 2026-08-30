# Implementation specification

## 1. Scope

Build a deterministic, testable Python implementation of:

1. BP phase weights and proportional phase durations, equations (1)-(7).
2. HDV-aware duration extension, Algorithm 1.
3. VTR station ordering and token scheduling, Algorithm 2.
4. CAV travel-time pressure and distance-constrained routing, equations (8)-(17) and Algorithm 3.
5. A TraCI adapter that applies those decisions to a reconstructed SUMO network.
6. Metrics and experiment runners for the published experiment matrix.

## 2. Explicit non-goals for the first implementation milestone

- Do not optimize parameters to match Table I before unit tests pass.
- Do not implement all four comparison baselines before IR-BP works end to end.
- Do not copy the paper PDF into Git history.
- Do not claim exact numerical reproduction without original SUMO and demand assets.
- Do not add a GUI, service, database, or distributed execution layer.

## 3. Domain model

### `RoadState`

- `edge_id: str`
- `length_m: float`
- `queue_vehicles: float`
- `remaining_capacity_vehicles: float`

Phase 1 deliberately keeps only quantities required by equations (1)-(4). Network endpoints and vehicle-ID collections belong to the later TraCI snapshot adapter.

### `VehicleState`

- `vehicle_id: str`
- `vehicle_kind: Literal["CAV", "HDV"]`
- `edge_id: str`
- `speed_mps: float`
- `remaining_distance_m: float`
- `destination_edge_id: str`

For the baseline interpretation of equation (8), `remaining_distance_m` is the literal remaining distance named in the paper prose. A TraCI adapter would derive it as `edge_length - lanePosition`. The formula also admits an upstream-lane-position interpretation, so both mappings require a later sensitivity comparison.

### `PhaseState`

- `phase_id: str`
- `station_id: str`
- `upstream_edge_id: str`
- `downstream_edge_ids: tuple[str, ...]`
- `clockwise_index: int`
- `head_vehicle_kind: Literal["CAV", "HDV"] | None`

### `IntersectionState`

- `node_id: str`
- `phases: tuple[PhaseState, ...]`
- `last_token_station_id: str`
- `cycle_length_s: float`

### `VehicleRoutingState`

- `vehicle_id: str`
- `origin_edge_id: str`
- `destination_edge_id: str`
- `distance_travelled_m: float`
- `eta_remaining_m: float`
- `destination_position_m: tuple[float, float]`

`destination_position_m` is the exact configured trip arrival position, not an assumed destination-edge endpoint. The smoke adapter resolves its declared `arrivalPos="max"` to the destination-lane endpoint; later general adapters own arbitrary arrival-position geometry.

### `RoutingCandidateState`

- `edge_id: str`
- `downstream_node_id: str`
- `length_m: float`
- `downstream_position_m: tuple[float, float]`
- `vehicles: tuple[VehicleState, ...]`
- `is_legal: bool`
- `destination_reachable: bool`

The two Boolean flags are defensive topology-precheck evidence. They reconstruct membership in the candidate set `R_ij` before equations (8)-(17); they are not new Algorithm 3 equations.

Use immutable snapshots for calculation. Keep TraCI objects outside the algorithm modules.

## 4. Pure algorithm contracts

### `compute_phase_weight(phase, roads) -> float`

- Implements (3)-(4).
- Rejects non-positive upstream length.
- Uses a single capacity unit for queue and downstream capacity.
- Returns zero when no vehicle is queued.

### `compute_proportional_phase_durations(weights, cycle_length_s) -> dict`

- Implements the continuous-time form of (5) without simulation-step rounding.
- Returns zero for zero-weight phases.
- Returns a strictly positive duration for every strictly positive weight.

### `allocate_phase_durations(weights, cycle_length_s, resolution_s) -> dict`

- Quantizes the continuous equation (5) result for discrete SUMO execution.
- Assigns at least one step to every positive-weight phase.
- Rejects a cycle with fewer available steps than positive-weight phases.
- Preserves the configured integer step count with stable largest-remainder allocation; floating-second sums are checked within numerical tolerance.
- Returns all zeros when total weight is zero. Because the paper does not define token ownership for this edge case, the reconstruction makes `build_cycle_plan` return an empty idle plan and preserves the previous holder.

### `order_token_stations(phases, weights, last_station_id) -> tuple`

- Builds clockwise order beginning after the previous holder.
- Places HDV-led phases first, preserving clockwise order.
- Places remaining positive-weight phases by descending weight.
- Breaks equal weights by clockwise order.
- Emits each station at most once.

This is the narrowest deterministic interpretation of Algorithm 2's prose. It must be isolated so another interpretation can be tested later.

### `extend_phase_for_hdv(initial_duration_s, queue_observations, increment_s, maximum_extension_s=None) -> float`

- Implements Algorithm 1.
- Stops when the queue is empty or a CAV becomes leader.
- Extends only in whole `increment_s` units.
- Uses no extension cap when `maximum_extension_s` is `None`, matching Algorithm 1.
- Accepts a finite cap only for a separately reported safety variant.
- Rejects a finite observation stream that ends after an HDV without reaching a CAV, empty queue, or safety-cap stop condition.

### `VTRCycleExecutor(plan, previous_station_id, timing...)`

- Executes one Algorithm 2 plan on a deterministic discrete clock.
- Activates one phase and its matching token station at a time during `ACTIVE` states, satisfying equations (6)-(7).
- Accepts only explicitly named post-step queue observations through `advance_after_step` and re-evaluates the leader at each Algorithm 1 boundary.
- Uses zero clearance in the paper-method fidelity profile.
- Allows an optional all-red `CLEARANCE` state with no active phase or token holder only in the safety variant; this state is outside equations (6)-(7).
- Applies one configured clearance after every completed active phase, including the last phase before the next cycle, while a new executor starts directly with service and does not add a second leading clearance.
- Skips zero-duration stations without activating them or changing the last token holder.
- Returns the final token holder for the next cycle's clockwise traversal.
- Reports the nominal service budget separately from actual elapsed cycle time and records each boundary outcome, including `extension_cap_hit`, with its boundary phase and station IDs.

### `estimate_candidate_travel_time(cav, candidate, timing...) -> float`

- Implements (8) when vehicles occupy the candidate road.
- Uses `candidate.length_m / empty_road_speed_mps` only when the road is empty.
- Applies the configured positive speed floor to both the CAV and every observed road vehicle before division.
- Uses the maximum occupied-road estimate exactly as written in (8); it does not mix in the empty-road estimate.
- Retains the vehicle ID attaining that maximum in the detailed evaluation trace; equal maxima use stable vehicle-ID order.
- Rejects non-finite inputs and remaining distances outside the candidate length tolerance.
- Returns a positive finite value.

### `select_next_edge(cav, trip, candidates, timing...) -> RoutingDecision`

- Calculates (9)-(17) and Algorithm 3 without mutating the CAV or trip state.
- Uses `g_c(k) = distance_travelled_m + candidate.length_m` in (12) and the Euclidean distance from the candidate downstream node to the trip's exact configured arrival position for `h_c(k)`.
- Evaluates (15) through the algebraically equivalent detour excess `local_cost - minimum_local_cost <= eta`, avoiding cancellation by the common travelled-distance term.
- Keeps at least one candidate eligible because every minimum distance-cost candidate has zero detour excess.
- Uses a separate defensive topology precheck to reconstruct `R_ij` from legal and destination-reachable inputs; an empty set raises `NoRouteError` carrying the exclusion scores. The smoke adapter supplies direct, non-internal, destination-reachable `R_ij` members; later paper-network adapters must preserve this contract.
- Selects the largest pressure weight only among eligible candidates, which is equivalent to (16) while preventing an ineligible zero from winning a zero-weight tie.
- Breaks pressure ties by stable edge ID within declared floating-point tolerances.
- Returns the updated per-trip detour budget from (17), distance limits, and a trace for every supplied candidate. Failed candidate-set reconstruction exposes its precheck-only trace on `NoRouteError`. Traces contain precheck status and reason, the equation (8) controlling vehicle, `g`, `h`, `f`, detour excess, eligibility mask, and masked weight as applicable.
- Leaves eta unchanged in the input; the TraCI caller commits the returned value once, only after route mutation succeeds.
- Keeps the vehicle-position tolerance separate from the route-cost tolerance used by equations (15) and (17).

## 5. SUMO controller execution order

At each SUMO step:

1. Read the current controller snapshot and apply its virtual phase through the SUMO enforcement adapter.
2. Before a CAV enters an intersection, calculate its next edge with Algorithm 3 and update its TraCI route.
3. Advance SUMO by one step.
4. Read subscribed post-step vehicle, lane, and intersection state.
5. Update queue and downstream-capacity snapshots.
6. Call `advance_after_step` with the post-step queue leader; at a phase boundary, extend or release the token from that observation.
7. At a completed VTR cycle boundary, compute the next weights, station order, and initial durations from the post-step snapshot.
8. Record phase, routing, and safety decision traces. The later experiment runner must additionally record nominal service budget, actual cycle duration, total HDV extension, clearance time, extension-cap events, and network metrics.

The one-intersection smoke adapter implements steps 1-7 and the smoke-level trace portion of step 8. Full experiment telemetry remains future work. The algorithm layer does not call TraCI; the simulation adapter owns subscriptions, route mutations, and virtual phase enforcement.

## 6. SUMO representation

### Network

- Build 20 intersections in a four-by-five grid.
- Reconstruct 54 directed edges with 45-300 m lengths.
- Use one lane per edge.
- Encode longitudinal roads as two-way and most lateral roads as one-way.
- Add two gate areas and internal terminal origins/destinations.

### Virtual unsignalized control

Use hidden/virtual SUMO traffic-light logic as an enforcement mechanism while presenting the policy as VTR control. This avoids unsafe simultaneous entry and gives deterministic phase control. The SUMO signal is an implementation actuator, not a claim that the studied terminal has physical signals.

### Vehicle types

- `CAV`: maximum speed `14 m/s`; generated OD uses distinct strict-internal edge pairs.
- `HDV`: maximum speed assigned from globally balanced `9`, `10`, `11`, and `12 m/s` types; generated OD balances both gates and gate-to-internal/internal-to-gate directions.

Unpublished acceleration, deceleration, car-following, vehicle-length, and gap parameters remain configuration fields.

### Seeded demand assets

The deterministic demand builder reads the resolved experiment configuration and generated paper-grid network. It divides the inferred `7200 s` departure horizon into 24 `300 s` bins, uses cumulative-floor aggregate quotas, places departures at evenly spaced bin midpoints, and assigns an exact global HDV quota. Seeded uniform sampling operates only over class-valid reachable OD pairs, and every vehicle begins on a shortest-distance non-internal SUMO route. The future runner must continue beyond the last departure until the network drains under a separately declared timeout.

The committed baseline is `2000 vehicles/h`, `10%` HDV, and seed `1`: exactly `4000` vehicles, of which `400` are HDVs. The paper's `20%` HDV alternative choice is not a static-demand feature; it must be applied and traced per intersection by the later TraCI runner. Generated metadata records resolved inputs, counts, assumptions, and dependency/output hashes.

## 7. Assumption register

These are implementation defaults, not paper facts. The exact Phase 1 values, rationale, and validation triggers are locked in [Phase 1 reconstruction decisions](05_phase1_assumptions.md).

| ID | Provisional decision | Status and validation |
|---|---|---|
| A-01 | Simulation step `1.0 s` | Selected reconstruction default; pending sensitivity test. |
| A-02 | Queue means vehicles with speed at or below `0.1 m/s` | Selected reconstruction default; compare against SUMO halting-number and queue-length metrics. |
| A-03 | Queue and remaining capacity use vehicle-equivalent slots | Selected reconstruction unit; the smoke adapter records its explicit `7.5 m` effective slot length. Paper-network calibration remains pending. |
| A-04 | Empty candidate road uses `edge_length / CAV_desired_speed` in (8) | Implemented because the paper leaves the empty maximum undefined; SUMO sensitivity remains pending. |
| A-05 | Speed floor `0.1 m/s` in (8) | Implemented for the CAV and observed road vehicles; sensitivity remains pending. |
| A-06 | Duration quantization uses stable largest remainder subject to a one-step lower bound for each positive phase | Preserves the integer cycle-step budget without silently deleting a positive equation (5) duration; second-valued sums use floating tolerance. |
| A-07 | HDV-priority group is clockwise-stable; remaining group is weight-descending with clockwise tie-break | Derived from prose around Algorithm 2. |
| A-08 | Virtual TLS acts as the VTR enforcement mechanism | Smoke-tested with runtime controlled-link discovery, mutually exclusive phase commands, and no collision or teleport. Full-network validation remains pending. |
| A-09 | `g_c(k)` equals completed distance to the current intersection plus the candidate edge length | Implemented in the pure routing layer; the smoke adapter supplies the full incoming-edge distance at its route-split decision node rather than a mid-edge observation distance. |
| A-10 | Each CAV starts a trip with `eta = 500 m`; budget depletes by (17) and does not reset until the next trip | Implemented as immutable input/output state; the smoke adapter commits eta once after SUMO accepts and echoes the replacement route. |
| A-11 | Demand departure horizon `7200 s` | Inferred from figures and implemented by the demand builder; not a published simulation parameter or a full-run termination time. |
| A-12 | Baseline seed `1`; later experiments use multiple declared seeds | Original seeds are unavailable. The committed demand asset is deterministic; multi-seed runs must report mean and dispersion. |
| A-13 | Cycle `T = 30 s`, HDV increment `1 s`, duration resolution `1 s`, and no extension cap | The first three are reconstruction defaults; the uncapped extension follows Algorithm 1. A `30 s` cap is reserved for a separately reported safety variant. |
| A-14 | Paper-method clearance `0 s`; safety-variant clearance `1 s` | The paper does not define clearance. Positive clearance is excluded from Algorithm 2 allocation and equations (6)-(7). |
| A-15 | Algorithm 1 reads the queue leader after the corresponding SUMO step | Prevents a pre-step observation from controlling a post-step phase boundary. |
| A-16 | Every zero-duration station is omitted and never becomes a token holder; an all-zero cycle is therefore idle and preserves the previous holder | Algorithm 2 includes HDV-priority stations even when equation (5) gives zero time, but the paper does not define whether an instantaneous holder changes the next-cycle anchor. This reconstruction recognizes only positive-duration holders. |
| A-17 | Equation (12) uses the candidate downstream-node coordinate and the trip's exact configured arrival-position coordinate | The smoke adapter derives `arrivalPos="max"`, keeps both coordinates in meters, and validates its fixture heuristic against reachable route distance. General paper-network validation remains pending. |
| A-18 | Position bounds and route-cost comparisons use separate `1e-9 m` absolute tolerances and a shared `1e-12` relative tolerance; pressure ties use `1e-12 m/s` absolute tolerance | This prevents future TraCI position allowances from relaxing the distance budget while preserving deterministic eligibility and ties. |
| A-19 | A defensive topology precheck reconstructs `R_ij` from supplied `is_legal` and `destination_reachable` evidence | This precheck is outside equations (8)-(17). The smoke adapter discovers live outgoing candidates, checks reachable SUMO suffixes, and verifies the committed route. General-network integration remains future work. |
| A-20 | Equation (8)'s baseline distance term is literal remaining distance, mapped from TraCI as `edge_length - lanePosition` | The paper prose and formula support conflicting coordinate readings. An upstream-lane-position sensitivity run is required before numerical-fidelity claims. |

All assumptions belong in experiment configuration and run metadata.

## 8. Configuration contract

`experiments/configs/paper_baseline.toml` stores paper-known values, exact reconstruction-environment versions, explicit reconstruction defaults for the paper-method fidelity profile, and remaining unresolved fields under `unresolved.items`. `uv.lock` owns dependency artifacts and hashes. `scripts/verify_environment.py` must pass before a SUMO run. Safety-variant overrides must be resolved into a separate run configuration. Later implementation must reject unresolved fields rather than silently inventing them.

Each run must write:

- Source commit SHA.
- SUMO and Python versions.
- Full resolved configuration.
- Random seed.
- Network and demand file hashes.
- Per-vehicle trip metrics.
- Per-step queue metrics.
- VTR and routing decision traces.

## 9. Verification gates

### Unit gate

- Equations (1)-(5) match hand-calculated cases.
- Paper example: `T = 30 s` and weights `{1/3, 1/2, 1/6}` allocate `{10, 15, 5}` before HDV extension.
- Every positive equation (5) weight survives step quantization, or allocation fails when the cycle has too few steps.
- During every paper-fidelity service step, one and only one station is active.
- HDV phase extension stops correctly.
- Distance mask in (15) always retains the shortest-distance candidate.
- Eta never becomes negative.
- Empty-road, zero-speed, empty-queue, all-zero-weight, and tie cases are deterministic.
- A complete BP/VTR cycle never exposes more than one active phase or token holder.
- All-zero plans are idle and preserve the previous token holder.
- Post-step HDV observations, extension-cap events, and optional clearance produce deterministic decision traces.
- Consecutive cycles preserve holder order and add no duplicate leading clearance.
- Nominal service budget and actual elapsed cycle duration are reported separately.
- Equations (8)-(17) match occupied-road, empty-road, distance-mask, and eta hand calculations.
- An ineligible high-pressure road is never selected, and pressure ties are independent of candidate input order.
- Empty usable candidate sets, duplicate edges, invalid measurements, and state mismatches fail explicitly.
- Generated demand has exact aggregate, bin, class, penetration, HDV OD gate/direction, and HDV speed-type quotas.
- Every generated OD follows its vehicle-class rule, is reachable, and receives a connected shortest-distance initial route.
- A clean fixed-seed demand rebuild is byte-identical to committed route and metadata assets.

### Integration gate

- Minimal intersection runs without collisions or deadlock.
- CAV route changes are legal and reach their destinations.
- 20-intersection scenario finishes with complete metric output.
- Fixed seed produces identical decision traces.

### Reproduction gate

- Increasing `eta` reduces queueing tendency and increases distance tendency.
- Travel time shows a tunable non-monotonic response near the selected region.
- IR-BP outperforms MCSR-like baseline in mean travel and waiting time after documented calibration.
- Quantitative comparison reports error against Table I without presenting calibrated values as original data.

## 10. Implementation sequence

1. Pure domain models and equations (equations (1)-(7) complete).
2. Algorithms 1-3 and pure unit tests (complete).
3. One-intersection TraCI adapter (complete).
4. Reconstructed 20-intersection network (complete).
5. Deterministic seeded demand generation (complete).
6. Full IR-BP TraCI runner and metrics.
7. MCSR-like comparison baseline.
8. Calibration and sensitivity analysis.
