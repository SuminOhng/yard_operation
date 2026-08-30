# Python/SUMO project structure

## 1. Current repository tree

```text
.
|-- .gitignore
|-- README.md
|-- pyproject.toml
|-- docs/
|   |-- 01_paper_analysis.md
|   |-- 02_implementation_spec.md
|   |-- 03_project_structure.md
|   |-- 04_reproduction_checklist.md
|   `-- 05_phase1_assumptions.md
|-- experiments/
|   |-- configs/
|   |   |-- README.md
|   |   `-- paper_baseline.toml
|   `-- outputs/
|       `-- .gitkeep
|-- src/
|   `-- irbp_replica/
|       |-- __init__.py
|       |-- control/
|       |   |-- __init__.py
|       |   |-- execution.py
|       |   |-- phase_time.py
|       |   |-- pressure.py
|       |   `-- vtr.py
|       |-- domain/
|       |   |-- __init__.py
|       |   `-- models.py
|       |-- routing/
|       |   |-- __init__.py
|       |   |-- distance.py
|       |   |-- irbp.py
|       |   `-- travel_time.py
|       `-- simulation/
|           `-- __init__.py
|-- sumo/
|   |-- config/
|   |   `-- README.md
|   |-- demand/
|   |   `-- README.md
|   `-- networks/
|       `-- paper_grid/
|           `-- README.md
`-- tests/
    |-- README.md
    |-- test_irbp_routing.py
    |-- test_phase_time.py
    |-- test_pressure.py
    |-- test_vtr_execution.py
    `-- test_vtr.py
```

The control, domain, and routing modules now implement the pure-Python BP/VTR and IR-BP milestones. Simulation and SUMO folders retain package or asset boundaries only.

## 2. Planned module ownership

```text
src/irbp_replica/
|-- domain/
|   |-- models.py        # Current roads, phases, vehicles, trips, and routing candidates
|   |-- network.py       # Later directed-network topology
|   |-- state.py         # Immutable traffic snapshots
|   `-- vehicles.py      # CAV/HDV and per-trip routing state
|-- control/
|   |-- pressure.py      # Equations (1)-(4)
|   |-- phase_time.py    # Equation (5) and Algorithm 1
|   |-- vtr.py           # Algorithm 2 and mutual-exclusion validation
|   `-- execution.py     # Discrete token, extension, and clearance lifecycle
|-- routing/
|   |-- travel_time.py   # Current equations (8)-(10)
|   |-- distance.py      # Current equations (12)-(15)
|   `-- irbp.py          # Current equations (11), (16)-(17), Algorithm 3
|-- simulation/
|   |-- traci_adapter.py # SUMO state reads and commands
|   |-- runner.py        # Step loop and lifecycle
|   |-- metrics.py       # Queue, trip, speed, waiting metrics
|   `-- traces.py        # Reproducible decision logs
`-- cli.py               # Experiment entry point
```

Add these files only when implementing their corresponding behavior. Avoid empty placeholder modules beyond package boundaries.

## 3. SUMO asset ownership

- `sumo/networks/paper_grid/`: editable source nodes, edges, connections, routes, and generated `.net.xml`.
- `sumo/demand/`: demand-generation settings and generated route files suitable for committing when small and deterministic.
- `sumo/config/`: `.sumocfg` files and output declarations.
- `experiments/configs/`: policy and experiment parameters independent of raw SUMO XML.
- `experiments/outputs/`: generated results; ignored except `.gitkeep`.

Generated network files must record the source files and command that created them. Never hand-edit a generated `.net.xml` without documenting why.

## 4. Dependency strategy

The paper names SUMO but does not state a version. Do not pin a guessed version in this scaffold. During environment setup:

1. Choose and record a SUMO version.
2. Match `traci` and `sumolib` to that installation.
3. Add numerical, tabular, plotting, and YAML packages only when their first use is implemented.
4. Produce a lock file after the end-to-end scenario runs.

## 5. Intended commands

The first command is active. Later commands become active after their corresponding modules exist:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -p "test_*.py" -v
python -m irbp_replica.cli validate-network experiments/configs/paper_baseline.toml
python -m irbp_replica.cli run experiments/configs/paper_baseline.toml --seed 1
python -m irbp_replica.cli summarize experiments/outputs/<run-id>
```

## 6. Boundaries

- Pure algorithms must not import TraCI.
- SUMO adapter must not reimplement equations.
- Experiment configuration owns tunable assumptions.
- Metrics code observes simulation state and must not affect control decisions.
- Generated outputs must not be inputs to a run unless explicitly declared.
