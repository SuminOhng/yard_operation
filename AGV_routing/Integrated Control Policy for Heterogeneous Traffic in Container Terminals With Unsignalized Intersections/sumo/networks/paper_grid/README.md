# Reconstructed paper grid

This directory contains an original, deterministic reconstruction of the paper's Fig. 6 topology. It is not the authors' unpublished SUMO network and must not be described as a numerical reproduction.

## Declared topology

- 20 nodes in a four-row by five-column grid.
- 54 directed, single-lane roads.
- All vertical links bidirectional.
- Top and bottom horizontal rows bidirectional.
- Two middle horizontal rows eastbound only.
- Coordinates `x = [0,300,600,900,1200] m`, `y = [600,400,200,0] m`.
- Source road lengths 300 m horizontal and 200 m vertical.
- Source road speed `14 m/s`.
- Gate portals `j_0_1` and `j_0_3`; no separate gate connector roads.
- All legal non-U-turn movements.
- 102 legal movements and 54 one-incoming-approach virtual phases in clockwise `N,E,S,W` order.
- Static virtual phase duration `3600 s` with each `next` index pointing to itself, preventing automatic cycling; runtime VTR must override it.

The paper reports the grid size, counts, one-lane tendency, road-direction tendencies, two gates, a 45-300 m range, and CAV maximum speed. Exact coordinates, road table, speed limits, gate connectors, turn permissions, and SUMO mappings are unpublished; every exact choice above is a reconstruction assumption.

## Files

- `paper_grid.manifest.toml`: editable source of constraints and assumptions.
- `paper_grid.nod.xml`, `paper_grid.edg.xml`, `paper_grid.con.xml`, `paper_grid.tll.xml`: generated PlainXML sources.
- `paper_grid.net.xml`: generated SUMO network.
- `paper_grid.metadata.json`: generated structural and provenance summary.

Never hand-edit generated assets. Edit the manifest or builder, then run:

```powershell
uv run python scripts/build_paper_grid_network.py
uv run python scripts/build_paper_grid_network.py --check
```

This milestone excludes demand, a full-network TraCI runner, collision/deadlock evidence, metrics, and numerical calibration. See `docs/08_paper_grid_reconstruction.md` for the fidelity boundary and acceptance checks.

SUMO may emit a self-loop phase warning when loading the network. This is expected for the intentional TraCI-only actuator program; a nonzero process exit or failed structural check is not expected.
