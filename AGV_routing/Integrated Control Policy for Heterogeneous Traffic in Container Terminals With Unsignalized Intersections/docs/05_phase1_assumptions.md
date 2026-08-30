# Phase 1 reconstruction decisions

These values are explicit reconstruction defaults, not facts reported by the paper. Every value remains configurable and must be written into future run metadata. Sensitivity analysis begins only after the deterministic Python and one-intersection gates pass.

| ID | Decision | Rationale and validation trigger |
|---|---|---|
| D-01 | VTR cycle length `T = 30 s` | The paper publishes this value only in Example 1. Retain it as the method-first baseline and sweep it after the first end-to-end run. |
| D-02 | HDV extension increment `tau_bar = 1 s` | One simulation step gives deterministic observation boundaries. Sweep it with `T` during calibration. |
| D-03 | Duration resolution `1 s` with stable largest-remainder rounding | Durations sum exactly to `T`, and equal remainders follow input order. |
| D-04 | Maximum HDV extension `30 s` | This is a telemetry-failure guard, not a claim about the paper. It prevents an endless pure-controller loop. |
| D-05 | Queue and downstream capacity use vehicle-equivalent slots | `q_ij` counts queued vehicles; `z_jk` counts available downstream vehicle slots. This keeps equations (1)-(3) dimensionally compatible. |
| D-06 | A vehicle is queued at speed `<= 0.1 m/s` | This threshold will be compared with SUMO halting-number behavior during integration. |
| D-07 | HDV-priority stations remain clockwise-stable; other positive-weight stations use descending weight and clockwise ties | This is the narrowest deterministic reading of the prose around Algorithm 2. |
| D-08 | Empty candidate roads use free-flow time `edge_length / 14 m/s` | Equation (8) has an undefined maximum over an empty set. This decision is reserved for the routing milestone. |
| D-09 | Equation (8) uses a `0.1 m/s` speed floor | This avoids division by zero and is reserved for the routing milestone. |
| D-10 | Routing ties use stable edge ID order | The paper does not publish a route tie rule. This decision is reserved for the routing milestone. |
| D-11 | Phase-transition clearance is `1 s` | The pure executor inserts one no-activation step. The later TraCI adapter must enforce the corresponding all-red state. Clearance is not consumed by Algorithm 2 duration allocation. |

## Phase 1 scope boundary

This milestone implements equations (1)-(7), Algorithm 1, Algorithm 2, and one-cycle clearance execution as pure Python. It does not implement IR-BP routing, TraCI, a SUMO network, or numerical calibration.
