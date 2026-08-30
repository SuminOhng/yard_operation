# Phase 1 reconstruction decisions

These values are explicit reconstruction defaults, not facts reported by the paper. Every value remains configurable and must be written into future run metadata. Sensitivity analysis begins only after the deterministic Python and one-intersection gates pass.

| ID | Decision | Rationale and validation trigger |
|---|---|---|
| D-01 | VTR cycle length `T = 30 s` | The paper publishes this value only in Example 1. Retain it as the paper-method reconstruction baseline and sweep it after the first end-to-end run. |
| D-02 | HDV extension increment `tau_bar = 1 s` | One simulation step gives deterministic observation boundaries. Sweep it with `T` during calibration. |
| D-03 | Duration resolution `1 s` with minimum-constrained stable largest-remainder allocation | Quantized durations preserve the integer step budget, every positive phase receives at least one step, equal remainders follow input order, and allocation fails when fewer steps than positive phases are available. Floating-second sums are compared within numerical tolerance. |
| D-04 | No HDV extension cap in the paper-method fidelity profile | Algorithm 1 extends until a CAV leads or the queue empties. A `30 s` telemetry-failure cap is allowed only in a separately labeled safety variant, and hitting it must be traced. |
| D-05 | Queue and downstream capacity use vehicle-equivalent slots | `q_ij` counts queued vehicles; `z_jk` counts available downstream vehicle slots. This keeps equations (1)-(3) dimensionally compatible. |
| D-06 | A vehicle is queued at speed `<= 0.1 m/s` | This threshold will be compared with SUMO halting-number behavior during integration. |
| D-07 | HDV-priority stations remain clockwise-stable; other positive-weight stations use descending weight and clockwise ties | This is the narrowest deterministic reading of the prose around Algorithm 2. |
| D-08 | Empty candidate roads use free-flow time `edge_length / 14 m/s` | Equation (8) has an undefined maximum over an empty set. This decision is reserved for the routing milestone. |
| D-09 | Equation (8) uses a `0.1 m/s` speed floor | This avoids division by zero and is reserved for the routing milestone. |
| D-10 | Routing ties use stable edge ID order | The paper does not publish a route tie rule. This decision is reserved for the routing milestone. |
| D-11 | Phase-transition clearance is `0 s` in the paper-method fidelity profile | The paper requires one active phase and token station in equations (6)-(7) and does not publish an all-red clearance. A `1 s` all-red interval is allowed only as a separately labeled safety variant and is not consumed by Algorithm 2 duration allocation. |
| D-12 | Algorithm 1 uses the queue leader observed after the matching simulation step | The enforcement adapter must apply the current phase, advance SUMO, read the post-step leader, and then evaluate the duration boundary. |
| D-13 | Every zero-duration station is omitted and never becomes a token holder; an all-zero cycle retains the previous holder | Algorithm 2 can list an HDV-priority station whose equation (5) time is zero, but the paper does not define whether this instantaneous handoff changes the next-cycle anchor. This reconstruction recognizes only positive-duration holders. |

## Phase 1 scope boundary

This milestone implements equations (1)-(7), Algorithm 1, Algorithm 2, paper-fidelity one-cycle execution, and an optional safety-clearance execution path as pure Python. Fidelity and safety-variant results must never be combined. It does not implement IR-BP routing, TraCI, a SUMO network, or numerical calibration.
