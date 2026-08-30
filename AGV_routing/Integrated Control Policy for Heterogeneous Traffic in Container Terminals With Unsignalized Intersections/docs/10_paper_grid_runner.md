# Full paper-grid TraCI runner

## Scope

`src/irbp_replica/simulation/paper_grid_runner.py` connects the existing pure BP/VTR and IR-BP functions to the reconstructed 20-intersection network and seed-1 baseline demand. It does not duplicate policy equations.

Every global tick has one fixed order:

1. discover or continue one `VTRCycleExecutor` per intersection;
2. command all 20 virtual traffic lights before the clock moves;
3. make at most one CAV or HDV routing decision per external-edge encounter inside the configured 30 m decision zone;
4. call `simulationStep()` exactly once;
5. collect departures, arrivals, collisions, and teleport events;
6. advance all active executors with post-step queue-leader observations.

The runner verifies the live `20 TLS / 54 phases / 102 controlled links` topology against generated metadata. A successful result also requires exact equality of the expected, departed, and arrived 4,000-vehicle ID sets, 3,600 CAVs and 400 HDVs, `minExpected=0`, and no collision or teleport event.

## Explicit reconstruction assumptions

The paper does not publish several adapter parameters. The baseline TOML now declares:

- `30 m` route-decision trigger distance;
- `7.5 m` vehicle-equivalent capacity slot;
- `3600 s` drain timeout after the reconstructed `7200 s` departure horizon;
- a dedicated seed-1 HDV routing random stream;
- legal, destination-reachable, non-U-turn HDV candidates;
- a draw only when at least one non-shortest alternative exists;
- `u < 0.20` as the strict alternative threshold and stable sorted uniform choice;
- the destination edge's downstream intersection as the paper-equation coordinate, while SUMO still uses `arrivalPos="max"` for vehicle removal.

The destination-coordinate split is necessary because SUMO lanes stop several meters before a junction center. Using that lane-shape endpoint as a road-node coordinate makes the Euclidean heuristic fail admissibility when the candidate road is itself the destination.

## Runtime routing

CAVs call the existing `select_next_edge` implementation at each encounter. Completed external-road lengths form equation (12)'s cumulative distance. Eta changes only after SUMO accepts and echoes the requested remaining route, and it must remain non-increasing and non-negative.

The paper states only that an HDV selects an alternative road with probability 20%. The exact candidate and draw rules above are therefore a labeled reconstruction, not an author-released implementation. Every HDV decision records its candidate lengths, shortest ties, eligible alternatives, random draw, choice, and route before and after mutation. The observed fraction is reported as `chosen / eligible`; it is not forced to equal 0.20.

## Reproducibility evidence

Success artifacts contain resolved configuration, SUMO/Python/platform versions, Git commit and dirty state, hashes for inputs and policy source files, topology counts, observed TraCI departure bins, controller summaries, route counters, safety sets, and canonical event/result digests. Failure artifacts contain the same provenance plus live road occupancy, queued vehicles, remaining slots, controller boundaries, and the last arrival time.

Run:

```powershell
uv run python scripts/run_paper_grid.py
```

The default artifact path is `experiments/outputs/paper_grid_seed1.json`, which is intentionally ignored by Git.

## Current seed-1 finding

A diagnostic run to `4500 s` reached a persistent physical gridlock without collisions or teleports:

- departed: `2077`;
- arrived: `670`;
- active: `1407`;
- last arrival: `3917 s`;
- most occupied roads were at their vehicle-slot capacity;
- one intersection accumulated `1472` one-second HDV extensions, and another accumulated `769`.

This is not reported as a successful reproduction. The paper-fidelity profile intentionally keeps HDV extension unbounded, so the runner does not add a hidden cap to force completion. The next experiment decision must compare declared sensitivity variants—especially a finite HDV extension cap, cycle length, network geometry/capacity, and internal-origin demand—without mixing them with paper-fidelity results.

Metrics, plots, baselines, parameter sweeps, and numerical comparison with the paper remain outside this milestone.
