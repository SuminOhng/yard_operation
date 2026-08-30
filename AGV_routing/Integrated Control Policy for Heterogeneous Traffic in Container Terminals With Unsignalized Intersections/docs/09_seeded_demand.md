# Seeded paper-grid demand reconstruction

## 1. Result

`scripts/build_paper_grid_demand.py` deterministically builds the baseline demand for the reconstructed 20-intersection network. Its committed outputs are:

- `sumo/demand/paper_baseline.rou.xml`: SUMO vehicle types, vehicles, departure times, and initial routes.
- `sumo/demand/paper_baseline.metadata.json`: resolved inputs, paper-fact/reconstruction labels, eligible-edge counts, quotas, realized counts, pinned toolchain, and output/dependency hashes.

The baseline uses seed `1`, a `7200 s` departure horizon, `2000 vehicles/h`, and `10%` HDVs. It therefore contains exactly `4000` vehicles: `400` HDVs and `3600` CAVs. This milestone proves deterministic demand construction and static route validity. It does not yet prove observed departures, collision freedom, deadlock freedom, or controller behavior in a full SUMO run.

## 2. Paper facts

The paper reports:

- Aggregate loading levels of `1600`, `2000`, and `2400 vehicles/h`.
- Demand is described as progressively loaded at `300 s` intervals; the exact sequence is unpublished.
- A main demand comparison with `10%` HDVs.
- HDV-penetration comparisons of `20%`, `30%`, and `50%` at `2000 vehicles/h`.
- HDV trips between a terminal gate and an internal road.
- CAV trips between different, randomly selected terminal roads.
- CAV maximum speed `14 m/s` and HDV maximum speeds from `9` to `12 m/s`.
- An HDV alternative-road choice probability of `20%` at each intersection.

The paper does not publish its route files, random seeds, exact origin-destination sampler, precise five-minute loading sequence, or SUMO vehicle-dynamics parameters.

## 3. Reconstruction decisions

The generator makes every missing choice explicit in `experiments/configs/paper_baseline.toml` and records the resolved values in metadata:

- The `7200 s` departure horizon is inferred from figure axes, not published as a simulation parameter. A future runner must continue after the last departure until the network drains, with a separately declared timeout.
- Seed `1` is the deterministic baseline seed.
- The departure horizon is divided into `24` bins of `300 s`.
- Each bin quota is the difference between consecutive cumulative floors of the ideal aggregate count. At `2000 vehicles/h`, quotas repeat `[166, 167, 167]` eight times. Corresponding exact patterns are `[133, 133, 134]` repeated eight times at `1600 vehicles/h`, and `[200]` repeated 24 times at `2400 vehicles/h`.
- Departures use evenly spaced bin midpoints, avoiding artificial simultaneous releases at bin boundaries.
- The global HDV quota is rounded once and assigned exactly; remaining vehicles are CAVs. This gives exact configured penetration for the published experiment totals.
- A strict internal edge has two non-gate endpoints. The reconstructed network contains `42` strict internal edges, `6` edges leaving gates, and `6` edges entering gates.
- CAV origins and destinations are distinct strict-internal roads.
- CAV shortest paths may traverse gate-incident grid roads. Gate portals label existing intersections and add no outside connector edge, so this does not leave the modeled terminal; it is an explicit reconstruction choice.
- HDV shortest paths use the same full grid and may cross a gate-labeled junction before their OD endpoint. Because the reconstruction has no gate connector edge, only an HDV trip endpoint counts as gate entry/exit; metadata names these quotas `hdv_od_gate_counts`, not observed gate flows.
- HDV categories balance the two gates and both travel directions: gate-to-internal and internal-to-gate. Category counts differ by at most one when a quota is not divisible by four.
- OD pairs are sampled uniformly from the corresponding reachable-pair set with the configured seed.
- Every vehicle receives the shortest-distance non-internal route returned by pinned `sumolib 1.27.1`. The builder verifies the imported module belongs to that distribution; metadata records tool versions and hashes `uv.lock`, network inputs, and generator source. Byte-level rebuild checks make this choice reproducible without claiming an unpublished tie rule.
- HDVs are assigned four globally balanced maximum-speed types: `9`, `10`, `11`, and `12 m/s`. CAV maximum speed is `14 m/s`; speed deviation is zero for reproducibility.
- Unpublished acceleration, deceleration, vehicle length, minimum gap, and car-following values remain SUMO defaults and stay listed as unresolved.

The `20%` HDV alternative-road behavior is intentionally absent from the static route file. It is a per-intersection runtime behavior and belongs in the future TraCI runner. Encoding it as a one-time static reroute would change the paper's stated behavior.

## 4. OD sets

The gate nodes are the reconstruction choices `j_0_1` and `j_0_3`.

- CAV: distinct ordered pairs from the `42` strict internal edges.
- HDV inbound: an origin edge leaving one selected gate and a strict-internal destination edge.
- HDV outbound: a strict-internal origin edge and a destination edge entering one selected gate.

Only pairs for which SUMO finds a non-internal route are eligible. Generated routes begin with the declared origin edge, end with the declared destination edge, contain no internal junction edges, and use only connected directed-edge transitions.

## 5. Quota and departure invariant

For rate `r` and horizon `H`, let `N` be the configured half-up rounding of `rH/3600`. With `M = H/B` bins, cumulative target at bin boundary `n` is:

```text
floor(n * N / M)
```

Bin `n` receives the difference between its cumulative target and the previous boundary. For a bin containing `q` vehicles, zero-based vehicle position `k` departs at:

```text
bin_start + (k + 0.5) * B / q
```

This preserves exact aggregate totals, keeps every departure strictly inside its bin, and makes the generated schedule reproducible.

## 6. Build and check

Build committed demand assets:

```powershell
uv run python scripts/build_paper_grid_demand.py
```

Check that committed assets exactly match a clean deterministic rebuild:

```powershell
uv run python scripts/build_paper_grid_demand.py --check
```

The check also asks SUMO to parse the complete route file and separately verifies every adjacent edge pair against the generated connection table. It does not simulate insertion or trip completion; those remain full-run gates.

Run the focused and full test gates:

```powershell
uv run python -m unittest tests.test_paper_grid_demand -v
uv run python -m unittest discover -s tests -p "test_*.py" -v
```

Do not hand-edit either generated file. Change the explicit configuration or generator, rebuild, review the metadata and diff, then run `--check`.

## 7. Proven and pending

Proven by this milestone:

- Fixed seed produces byte-identical route and metadata files.
- Aggregate count, 300-second bin quotas, HDV/CAV count, HDV penetration, HDV OD gate/direction balance, and four HDV speed-type counts satisfy their declared invariants.
- Every generated OD pair follows the class rule and is reachable.
- Every initial route is a connected shortest-distance route returned by pinned `sumolib 1.27.1` for the reconstructed SUMO graph.
- Metadata distinguishes paper facts from reconstruction assumptions and hashes its dependencies and route output.

Still pending:

- Reconstructing the authors' unpublished five-minute loading process.
- Defining the full-run drain timeout after the `7200 s` departure horizon.
- Applying the HDV `20%` alternative choice at each intersection.
- Loading all `4000` baseline vehicles in the general 20-intersection TraCI runner.
- Measuring observed departures and realized flow inside SUMO.
- Collision, teleport, and deadlock checks for the full scenario.
- Queue, travel-time, distance, waiting-time, and speed metrics.
- Multiple-seed sweeps, calibration, and numerical comparison with the paper.
