# Paper-grid network reconstruction

## 1. Scope and fidelity claim

This milestone turns the topology visible in Fig. 6 into deterministic SUMO PlainXML. It is a **method-faithful topology reconstruction**, not the authors' unpublished network and not a numerical reproduction of the paper's results.

The paper reports a four-by-five grid with 20 unsignalized intersections, 54 directed roads, mostly single-lane roads, two-way longitudinal roads, mostly one-way lateral streets, road lengths from 45 m to 300 m, and two peripheral HDV gates. It does not publish node coordinates, an edge table, road-by-road lengths, exact gate connectors, turn permissions, or SUMO signal/link mappings.

The current milestone covers only network topology, legal movements, virtual phase construction, reproducible generation, and structural checks. Demand generation, the full 20-intersection TraCI runner, collision/deadlock runs, metrics, and numerical calibration remain later work.

## 2. Explicit reconstruction decisions

| Item | Reconstruction decision | Status |
|---|---|---|
| Node layout | Four rows by five columns, with IDs `j_<row>_<column>` | Assumption consistent with Fig. 6 |
| Coordinates | `x = [0, 300, 600, 900, 1200] m`; `y = [600, 400, 200, 0] m` | Assumption; exact coordinates are unpublished |
| Vertical roads | Every adjacent vertical pair is bidirectional | Paper-constrained reconstruction |
| Boundary horizontal roads | Top and bottom rows are bidirectional | Assumption from Fig. 6 arrows |
| Interior horizontal roads | Both middle rows are eastbound, from lower to higher `x` | Assumption from Fig. 6 arrows |
| Gate representation | `j_0_1` and `j_0_3` are gate portals; no extra gate edge is added | Assumption preserving the reported `20/54` count |
| Road lengths | Source lengths equal coordinate distance: 300 m horizontal and 200 m vertical | Assumption within the reported 45-300 m range |
| Lane count | Every reconstructed road has one lane | Assumption applying the paper's predominant single-lane pattern uniformly |
| Road speed | Every source road uses `14 m/s` | Reconstruction fixture value aligned with the reported CAV maximum speed; road speed limits are unpublished |
| Turn permissions | Every legal outgoing non-U-turn movement is generated | Assumption; permissions are unpublished |
| Virtual phases | One incoming approach per phase, ordered clockwise `N, E, S, W` | Method-faithful actuator mapping; exact SUMO mapping is unpublished |
| Bootstrap phase behavior | Every static virtual phase uses `3600 s` and `next` points back to that same phase | SUMO placeholder only; it prevents automatic cycling and runtime VTR must override phase state and service duration |

The selected geometry does not reproduce the paper's unpublished distribution down to 45 m. The reported 45-300 m interval remains a paper fact; this fixture uses only 200 m and 300 m roads. Geometry and road-length sensitivity therefore remain calibration work.

## 3. Directed-edge count

The 54-road convention counts only roads between the 20 intersections. Gate portals label existing boundary nodes and add no connector edges.

```text
vertical:                 3 gaps x 5 columns x 2 directions = 30
top/bottom horizontal:    2 rows x 4 gaps x 2 directions    = 16
middle-row horizontal:    2 rows x 4 gaps x 1 direction     =  8
total directed roads:                                             54
```

All roads have one lane. The two bidirectional boundary rows and five bidirectional vertical corridors keep the directed graph strongly connected despite the eastbound-only middle rows.

## 4. Gates and future demand ownership

`j_0_1` and `j_0_3` are metadata-level gate portals, not extra SUMO junctions or roads. Future demand code will use them to construct HDV gate-to-internal and internal-to-gate trips. CAV trips will remain internal. This decision is reversible: if stronger evidence later shows separate gate connectors, a new explicitly versioned network variant must change both topology and the 54-road count convention.

## 5. Movements and virtual VTR phases

At each intersection, the generator creates every topology-legal movement from an incoming road to an outgoing road except the direct U-turn back to the upstream node. The full network has 102 such controlled movements. One virtual phase contains all generated movements from one incoming approach, giving 54 phases across 20 intersections. Approaches are ordered clockwise as `N, E, S, W`; missing approaches are skipped.

Only one incoming approach can be green at a time. Movements within that phase share one entering lane and therefore do not create a cross-approach conflict. The validator also resolves every controlled `linkIndex` to SUMO's junction-request index and rejects any active movement pair marked as foes by the compiled network. SUMO `traffic_light` junctions are used only as TraCI actuators for this mutual-exclusion contract. They do **not** claim that the paper's intersections contain physical traffic signals. Each static phase lasts `3600 s` and has a `next` value equal to its own phase index, so SUMO cannot silently cycle through approaches before an adapter connects. SUMO may print a self-loop phase warning when loading this intentional actuator program; that warning alone is not a build or runtime failure. Runtime BP/VTR logic must supply token order, phase state, and service duration for the unsignalized-control method.

## 6. Source and generated assets

- `paper_grid.manifest.toml`: human-readable source of paper constraints and reconstruction assumptions.
- `paper_grid.nod.xml`: 20 source nodes and coordinates.
- `paper_grid.edg.xml`: 54 directed, single-lane source roads.
- `paper_grid.con.xml`: legal non-U-turn connections.
- `paper_grid.tll.xml`: controlled-link indices and virtual phases.
- `paper_grid.net.xml`: generated SUMO network; never hand-edit it.
- `paper_grid.metadata.json`: generated count, gate, phase, and provenance summary.

Build or verify the committed artifacts from the repository root:

```powershell
uv run python scripts/build_paper_grid_network.py
uv run python scripts/build_paper_grid_network.py --check
```

`--check` rebuilds into a temporary directory, compares deterministic artifacts, and rejects structural drift. Edit the manifest or generator, rebuild, inspect the diff, and rerun the complete test gate; never patch `paper_grid.net.xml` directly.

## 7. Acceptance boundary

The network gate must prove:

- exactly 20 source intersections and 54 non-internal directed roads;
- one lane per road and source lengths within 45-300 m;
- bidirectional vertical links, bidirectional top/bottom links, and eastbound-only middle links;
- exactly two declared gate portals with no extra gate roads;
- strong connectivity and no isolated source node or road;
- no U-turn connection and complete coverage of legal non-U-turn movements;
- exactly 102 controlled movements and 54 one-approach virtual phases;
- one virtual phase per incoming approach and each controlled link assigned to exactly one such phase;
- no phase activates movements from two incoming approaches or a pair marked as foes by SUMO;
- deterministic rebuild equality.

Passing this gate proves the declared reconstruction internally consistent. It does not establish original-network identity, demand fidelity, collision-free full runs, or agreement with the paper's numerical figures.
