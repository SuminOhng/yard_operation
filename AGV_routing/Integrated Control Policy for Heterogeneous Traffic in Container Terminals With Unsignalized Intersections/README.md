# IR-BP container-terminal traffic-control replica

This project reconstructs the method in *Integrated Control Policy for Heterogeneous Traffic in Container Terminals With Unsignalized Intersections* (IEEE T-ITS, 2025, DOI: 10.1109/TITS.2025.3560067).

The first target is a method-faithful implementation of the BP-based virtual token ring (VTR) controller and the IR-BP CAV router. Numerical agreement with the paper is a later calibration target because the paper does not publish its code, exact SUMO network, demand files, random seeds, SUMO version, or every controller parameter.

## Current phase

The algorithm, first simulator-integration, paper-grid topology, and seeded baseline-demand milestones are complete. The pure layer includes equations (1)-(17), HDV-aware phase extension (Algorithm 1), deterministic BP/VTR scheduling (Algorithm 2), distance-constrained IR-BP CAV routing (Algorithm 3), and a discrete one-cycle executor. A deterministic one-intersection smoke scenario connects those functions to live SUMO state through TraCI. Separate deterministic builders reconstruct the Fig. 6 topology as 20 intersections and 54 directed roads, then create exact-quota CAV/HDV demand with explicit, reviewable time-bin, OD, vehicle-class, speed, and initial-route assumptions.

The paper-method fidelity profile uses no clearance interval and no HDV extension cap. A separate safety variant may add all-red clearance and a finite extension cap, but its results must not be reported as the paper method. The configured cycle length `T` is the nominal phase-service budget; HDV extension and optional clearance increase actual elapsed cycle time.

The selected deterministic BP/VTR and IR-BP unit gates pass. The project environment is pinned to CPython 3.13.13 and SUMO/traci/sumolib 1.27.1 through `uv.lock`. The smoke gate discovers downstream candidates, applies and verifies one CAV route mutation, enforces mutually exclusive virtual phases, rejects collisions and teleports, and compares two fixed-seed decision traces. The paper-grid gate proves its declared `20/54` topology, and the demand gate proves deterministic exact counts, OD-class constraints, reachability, initial shortest routes, and metadata provenance. Gate balance means HDV OD category quotas, not observed portal flow. These are reconstruction proofs, not the authors' unpublished assets or a numerical reproduction. Equation (8) still requires the declared coordinate-interpretation sensitivity test.

## Documents

- [Paper analysis](docs/01_paper_analysis.md)
- [Implementation specification](docs/02_implementation_spec.md)
- [Project structure](docs/03_project_structure.md)
- [Reproduction checklist](docs/04_reproduction_checklist.md)
- [Phase 1 reconstruction decisions](docs/05_phase1_assumptions.md)
- [Reproducible SUMO environment](docs/06_environment.md)
- [One-intersection TraCI smoke](docs/07_traci_smoke.md)
- [Paper-grid network reconstruction](docs/08_paper_grid_reconstruction.md)
- [Seeded paper-grid demand reconstruction](docs/09_seeded_demand.md)

## Repository policy

The IEEE PDF is local reference material and is excluded by `.gitignore`. Commit only original code, configuration, reconstructed SUMO assets, and generated summaries that are suitable for redistribution.

## Verification

Create and verify the locked environment, then run the Phase 1 test gate:

```powershell
uv sync --extra dev --frozen
uv run python scripts/verify_environment.py
uv run python scripts/build_smoke_network.py --check
uv run python scripts/build_paper_grid_network.py --check
uv run python scripts/build_paper_grid_demand.py --check
uv run python scripts/run_sumo_smoke.py
uv run python -m unittest discover -s tests -p "test_*.py" -v
```

## Next milestone

Add the general 20-intersection TraCI runner, including runtime HDV alternative choices and observed-flow checks, then add metrics and calibration. Keep reconstructed demand assumptions separate from paper facts.
