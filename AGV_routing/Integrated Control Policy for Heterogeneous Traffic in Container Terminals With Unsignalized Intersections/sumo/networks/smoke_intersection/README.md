# One-intersection SUMO smoke network

This deterministic network exercises one unsignalized-intersection control
adapter and one live IR-BP route change. It is an integration fixture, not a
calibrated container-terminal model and not evidence of paper-level numerical
reproduction.

## Topology

The controlled junction has exactly two conflicting links:

- west movement: `w_in -> e_out`
- south movement: `s_in -> n_out`

The SUMO `traffic_light` node is only the TraCI actuator used to enforce VTR
token ownership. Its committed program is one all-red `rr` bootstrap phase;
the adapter pins the first command before advancing SUMO. It is not the paper's
control policy. SUMO therefore emits one expected `Missing green phase`
warning while loading the bootstrap program; live `Gr` and `rG` commands are
then supplied and verified through TraCI.

The CAV begins on `cav_src`. At `route_split` it can take the direct candidate
`w_in` or the longer `bypass_w -> bypass_s -> bypass_e` path; both rejoin before
`cav_dst`. `blocker_0`, a deterministic `slow_hdv`, begins on `w_in` and then
uses `e_out -> cav_dst`. Its low speed makes the occupied direct candidate's
routing weight lower than the empty `bypass_w` candidate at the CAV's first
decision. The blocker still reaches its destination before the 180 s horizon.
`truck_0` crosses south-to-north through the other controlled link.

The CAV's deterministic `10 m/s` maximum speed is a smoke-fixture
simplification, not a paper-calibrated parameter.

## Source and generated files

`smoke.nod.xml`, `smoke.edg.xml`, `smoke.con.xml`, and `smoke.tll.xml` are the
PlainXML network sources. `smoke.rou.xml` supplies deterministic vehicle types,
routes, and demand. `smoke.sumocfg` supplies the headless smoke configuration
without persistent simulation outputs.

`smoke.net.xml` is generated. Never edit it manually. From the project root,
rebuild it with the pinned environment:

```powershell
.\.venv\Scripts\python.exe scripts\build_smoke_network.py
```

Verify that the committed network still matches its sources without rewriting
repository files:

```powershell
.\.venv\Scripts\python.exe scripts\build_smoke_network.py --check
```

Run the complete headless TraCI smoke proof from the project root with:

```powershell
.\.venv\Scripts\python.exe scripts\run_sumo_smoke.py
```

The smoke TraCI adapter owns all mappings from live SUMO state to paper-model
state, including the queue-speed threshold, queue membership, lane capacity in
vehicle slots, CAV/HDV type mapping, remaining-distance convention, and routing
decision timing. Values used by that adapter are explicit smoke assumptions;
they are not calibrated paper parameters.
