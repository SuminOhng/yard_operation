# One-intersection TraCI smoke gate

## Scope

This scenario proves that the verified pure BP/VTR and IR-BP functions can consume live SUMO state and apply legal commands through TraCI. It is a deterministic integration fixture, not the authors' unpublished terminal network and not evidence of numerical agreement with the paper.

The network contains one virtual traffic light with two conflicting controlled links:

- west: `w_in -> e_out`, signal state `Gr`;
- south: `s_in -> n_out`, signal state `rG`.

A CAV reaches an upstream route split with candidates `w_in` and `bypass_w`. A slow HDV on `w_in` creates a repeatable pressure difference, so Algorithm 3 selects the longer bypass while eta permits it. The blocker and a crossing truck keep both VTR phases observable after the CAV bypasses the controlled junction.

## Adapter contract

The smoke runner:

1. resolves the pinned wheel-bundled `sumo.exe`, starts a uniquely labelled TraCI connection, and verifies protocol and server versions;
2. pins the virtual signal before the first simulation step, discovers controlled-link indexes, and never relies on the bootstrap static schedule;
3. subscribes to signal, lane, and departed-vehicle state, uses those caches for live snapshots, and validates them against direct TraCI reads;
4. maps queued vehicles and downstream free slots into immutable `RoadState` values, then calls `build_cycle_plan` and `VTRCycleExecutor` without duplicating their equations;
5. applies one active phase, advances SUMO exactly once, reads the post-step queue leader, and only then advances Algorithm 1;
6. maps the equation (8) baseline distance to `edge_length - lanePosition`;
7. discovers legal outgoing candidates and reachable SUMO route suffixes, calls `select_next_edge`, applies a full route beginning with the CAV's current edge, verifies the accepted route, and commits eta once;
8. fails on a collision, teleport, missing arrival, duplicate route update, phase overlap, version mismatch, or step-cap exhaustion.

The fixture uses one vehicle-equivalent slot of `7.5 m` for lane-capacity snapshots and the selected `0.1 m/s` queue threshold. Those are smoke reconstruction parameters, not published paper values. The run uses paper-profile zero clearance and no HDV-extension cap. Idle all-zero snapshots use `rr` while retaining the previous token holder.

## Assets and commands

Editable inputs and the generated network live in `sumo/networks/smoke_intersection/`. `smoke.net.xml` is generated only; never edit it by hand.

```powershell
uv sync --extra dev --frozen
uv run python scripts/verify_environment.py
uv run python scripts/build_smoke_network.py --check
uv run python scripts/run_sumo_smoke.py
uv run python -m unittest discover -s tests -p "test_traci_smoke.py" -v
```

`scripts/run_sumo_smoke.py` prints canonical JSON. The integration test executes the scenario twice with the same seed and compares normalized trace digests in addition to checking routing, phase, safety, and arrival invariants.

## What remains

The smoke gate does not resolve equation (8)'s coordinate-interpretation ambiguity, prove heuristic admissibility for the paper-scale network, define the paper's exact queue-length-in-meters metric, reconstruct the four-by-five terminal, generate paper demand, or calibrate results against figures and tables.
