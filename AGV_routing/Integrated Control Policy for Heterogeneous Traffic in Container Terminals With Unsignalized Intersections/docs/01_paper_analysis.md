# Paper analysis

## 1. Source and reproduction objective

- Paper: Shuo Wang, Weimin Wu, Jiliang Luo, Jiazhong Zhou, and Tao Zhang, "Integrated Control Policy for Heterogeneous Traffic in Container Terminals With Unsignalized Intersections."
- Journal: IEEE Transactions on Intelligent Transportation Systems, vol. 26, no. 7, pp. 10795-10807, July 2025.
- DOI: `10.1109/TITS.2025.3560067`.
- Objective: reconstruct the proposed IR-BP policy from the published equations, algorithms, figures, and experimental descriptions.

The paper does not provide a public code repository, supplementary implementation, exact SUMO assets, or a data-availability statement. Therefore, this project separates paper facts from reconstruction assumptions.

## 2. Problem definition

The terminal traffic network is a directed graph `G = (N, L)`. Vehicles are split into human-driven vehicles (HDVs) and connected automated vehicles (CAVs):

\[
C = C_h \cup C_c, \qquad C_h \cap C_c = \varnothing.
\]

Each vehicle has an origin road and destination road. A movement `(l_ij, l_jk)` moves from upstream road `l_ij` through intersection `j` to downstream road `l_jk`. A phase is a conflict-free set of movements.

Core control tasks:

1. Select the activation order of phases at each unsignalized intersection.
2. Select each active phase duration from local traffic state.
3. Re-route CAVs at intersections while preserving a bounded detour from a shortest-distance route.

Paper assumptions relevant to implementation:

- Roads are modeled as FIFO systems.
- Vehicle position and speed are known.
- HDVs are slower and their route decisions are uncertain.
- HDVs receive priority when they lead an inbound queue.
- Only one station and its corresponding phase are active at an intersection.
- CAVs may change their next road at each intersection; HDVs follow their own route logic.

## 3. BP-based virtual token ring intersection control

Each intersection has one virtual station per phase and one token. A station may activate its phase only while holding the token. The paper gives two delivery rules:

1. Traverse the station ring clockwise from the previous token holder.
2. Prioritize phases whose queue-leading vehicle is an HDV.

Let `q_ij(t)` be the upstream queue length and `z_jk(t)` the remaining downstream capacity. Movement pressure is

\[
BP_{ij,jk}(t) = \min\{q_{ij}(t), z_{jk}(t)\}. \tag{1}
\]

Normalized movement pressure is

\[
BP^*_{ij,jk}(t) = \frac{\min\{q_{ij}(t), z_{jk}(t)\}}{|l_{ij}|}. \tag{2}
\]

The phase pressure aggregates downstream remaining capacity:

\[
BP^*_{ij}(t) =
\frac{\min\left\{q_{ij}(t), \sum_{jk \in R_{ij}} z_{jk}(t)\right\}}
{|l_{ij}|}. \tag{3}
\]

Its non-negative weight is

\[
w_{ij}(t) = \max\{BP^*_{ij}(t), 0\}. \tag{4}
\]

For cycle length `T`, initial token-holding time is

\[
t^*_{ij} =
\begin{cases}
\dfrac{w_{ij}(t)T}{\sum_{ij \in \Omega_j} w_{ij}(t)}, & w_{ij}(t) > 0,\\
0, & w_{ij}(t) = 0.
\end{cases} \tag{5}
\]

The mutual-exclusion constraints are

\[
\sum_{p_{ij} \in P_j} p_{ij}(t) = 1, \tag{6}
\]

\[
\sum_{s_{ij} \in S_j} s_{ij}(t) = 1. \tag{7}
\]

### Algorithm 1: HDV-aware phase extension

After the initial duration expires, keep the phase active in increments of `tau_bar` while an HDV still leads the queue. Stop extending when a CAV becomes the leader or all queued vehicles have passed.

### Algorithm 2: token sequence and durations

Reconstruction of the prose and pseudocode:

1. Build a one-cycle clockwise station list immediately after the previous token holder.
2. Compute every station weight with (3)-(4).
3. Append HDV-led stations first.
4. Append remaining positive-weight stations in descending weight order.
5. Use clockwise order as deterministic tie-breaker.
6. Allocate durations with (5), then apply Algorithm 1 during execution.

The paper example uses `T = 30 s`, weights `{1/3, 1/2, 1/6}`, and resulting durations `{10, 15, 5}`.

## 4. IR-BP dynamic routing for CAVs

For candidate downstream road `l_jk`, vehicle-specific estimated travel time is

\[
t^f_{jk}(c) =
\max_{c' \in C_{jk}}
\left\{
\frac{|l_{jk}| - |l^{c'}_{jk}(t)|}{v_{c'}(t)}
+ \frac{|l^{c'}_{jk}(t)|}{v_c(t)}
\right\}. \tag{8}
\]

Here `|l^{c'}_{jk}(t)|` is the remaining distance of vehicle `c'` on the candidate road. The vehicle-specific road pressure and weight are

\[
BP^c_{jk} = \frac{|l_{jk}|}{t^f_{jk}(c)}, \qquad l_{jk} \in R_{ij}, \tag{9}
\]

\[
w^c_{jk} = BP^c_{jk}. \tag{10}
\]

Without a distance constraint, choose the largest pressure-release weight:

\[
r^c_j = \arg\max_{l_{jk} \in R_{ij}} w^c_{jk}. \tag{11}
\]

The A*-inspired distance cost is

\[
f_c(k) = g_c(k) + h_c(k), \tag{12}
\]

where `g_c(k)` is cumulative distance from origin through candidate node `k` and `h_c(k)` is Euclidean distance from `k` to destination. Let

\[
f'_c(j) = \min_{l_{jk} \in R_{ij}} f_c(k), \tag{13}
\]

\[
f^*_c(j) = f'_c(j) + \eta_c. \tag{14}
\]

Candidate eligibility is

\[
\lambda_{jk}(c) =
\begin{cases}
0, & f_c(k) > f^*_c(j),\\
1, & f_c(k) \leq f^*_c(j).
\end{cases} \tag{15}
\]

The selected road maximizes pressure among eligible candidates:

\[
r^c_j = \arg\max_{l_{jk} \in R_{ij}}
\left\{w^c_{jk}\lambda_{jk}(c)\right\}. \tag{16}
\]

If selected downstream node is `s`, update the remaining detour budget:

\[
\eta_c \leftarrow
\max\left\{\eta_c - \left(f_c(s) - f'_c(j)\right), 0\right\}. \tag{17}
\]

Algorithm 3 is the direct evaluation of (12)-(17) at every CAV routing decision.

## 5. Published experimental design

### Network

- Simplified real container-terminal layout.
- Four-by-five grid, 20 unsignalized intersections, and 54 directed roads.
- Road lengths from 45 m to 300 m.
- Most roads are single lane.
- Longitudinal roads are two-way; most lateral roads are one-way.
- Two perimeter gates for HDV entry and exit.
- CAVs remain inside the terminal.

### Demand and vehicles

- Demand levels: 1600, 2000, and 2400 vehicles/h.
- Demand is described as progressively loaded at five-minute intervals; the exact generation process is not published.
- HDV ODs connect a gate and an internal road in either direction.
- CAV ODs connect terminal roads.
- HDVs use shortest routing but choose an alternative with probability 20% at each intersection.
- HDV maximum speed is sampled between 9 and 12 m/s.
- CAV maximum speed is 14 m/s.
- Main demand comparison uses 10% HDV penetration.
- Penetration experiment uses 20%, 30%, and 50% HDVs at demand level 2.
- Figures show a 7200 s horizon; this is inferred from figure axes, not stated as a configuration value.

### Distance relaxation

The paper evaluates `eta` values 100, 200, 400, 500, 600, 700, 800, and 1000, then uses `eta = 500` for later experiments.

### Compared methods

- FX-STR: fixed signal control plus shortest-travel-time routing.
- MC-BP: multi-commodity BP signal control plus fixed shortest routing.
- AR-BP: multi-commodity BP signal control plus dynamic routing.
- MCSR: integrated signal control and multi-commodity routing.
- IR-BP: proposed VTR intersection control plus distance-constrained BP routing.

Comparison methods use equal 20 s green time per phase. The proposed method is virtual-token controlled, while comparison methods are represented with traffic signals.

### Metrics

- Total network queue length in meters.
- Average travel distance in meters.
- Average travel time in seconds.
- Average speed in m/s.
- Waiting time in seconds for eight case studies.

### Table I numerical targets

| Case | MCSR travel time (s) | MCSR distance (m) | MCSR waiting (s) | IR-BP travel time (s) | IR-BP distance (m) | IR-BP waiting (s) |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 407 | 1373 | 139 | 335 | 1327 | 92 |
| 2 | 373 | 1360 | 121 | 327 | 1333 | 84 |
| 3 | 401 | 1454 | 164 | 371 | 1412 | 121 |
| 4 | 468 | 1432 | 132 | 383 | 1384 | 126 |
| 5 | 385 | 1361 | 131 | 333 | 1312 | 78 |
| 6 | 438 | 1429 | 165 | 337 | 1341 | 114 |
| 7 | 392 | 1358 | 140 | 317 | 1370 | 98 |
| 8 | 415 | 1415 | 174 | 325 | 1340 | 106 |

These values are calibration targets, not initial pass/fail gates, because the eight OD cases and their start times are not published.

## 6. Reproducibility gaps and paper ambiguities

| ID | Missing or ambiguous item | Consequence |
|---|---|---|
| G-01 | Exact node coordinates, edge list, direction, and per-edge lengths | Figure 6 supports approximation only. |
| G-02 | SUMO version | Simulator behavior cannot be matched exactly. Earlier project discussion mentioned SUMO 1.8.0, but the paper itself does not state that version. |
| G-03 | Car-following, acceleration, deceleration, vehicle length, and gap parameters | Queue and travel-time values may shift materially. |
| G-04 | Random seeds and exact OD samples | Exact plots and Table I cannot be regenerated directly. |
| G-05 | Exact interpretation and units of `q_ij` and `z_jk` | Equations require compatible capacity units. |
| G-06 | Cycle length `T` and HDV extension increment `tau_bar` | Phase timing remains under-specified. |
| G-07 | Empty-road and zero-speed behavior in (8) | The maximum over an empty set and division by zero are undefined. |
| G-08 | Algorithm 2 removal, sorting, and tie-breaking operations | Pseudocode omits operations described in prose. |
| G-09 | Phase transition safety time | Yellow/all-red or clearance logic is not described. |
| G-10 | Route-choice tie-breaking | Multiple candidates may have equal masked weight. |
| G-11 | Whether `eta_c` resets during a trip | Equation (17) implies depletion, but lifecycle is not explicit. |
| G-12 | Demand loading at five-minute intervals | Arrival distribution and rate transitions are unclear. |
| G-13 | Text refers to a `DSP` method although figures and the comparison list use `MCSR` | Treat `DSP` as a likely editorial mismatch pending contrary evidence. |
| G-14 | Exact definition of reported queue length in meters | SUMO has several plausible queue metrics. |

## 7. Reproduction strategy

Use two fidelity levels:

1. **Method fidelity:** equations, ordering rules, constraints, edge-case behavior, and qualitative trends are reproduced on a reconstructed network.
2. **Numerical calibration:** network geometry, demand, vehicle parameters, and controller timing are tuned transparently toward Figs. 7-14 and Table I without claiming access to original assets.

Every assumption must remain configurable and recorded with each run.
