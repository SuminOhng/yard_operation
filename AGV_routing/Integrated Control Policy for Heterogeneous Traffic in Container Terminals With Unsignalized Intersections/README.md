# IR-BP container-terminal traffic-control replica

This project reconstructs the method in *Integrated Control Policy for Heterogeneous Traffic in Container Terminals With Unsignalized Intersections* (IEEE T-ITS, 2025, DOI: 10.1109/TITS.2025.3560067).

The first target is a method-faithful implementation of the BP-based virtual token ring (VTR) controller and the IR-BP CAV router. Numerical agreement with the paper is a later calibration target because the paper does not publish its code, exact SUMO network, demand files, random seeds, SUMO version, or every controller parameter.

## Current phase

Phase 0 is complete. The pure-algorithm milestone now includes equations (1)-(17), HDV-aware phase extension (Algorithm 1), deterministic BP/VTR scheduling (Algorithm 2), distance-constrained IR-BP CAV routing (Algorithm 3), and a discrete one-cycle executor.

The paper-method fidelity profile uses no clearance interval and no HDV extension cap. A separate safety variant may add all-red clearance and a finite extension cap, but its results must not be reported as the paper method. The configured cycle length `T` is the nominal phase-service budget; HDV extension and optional clearance increase actual elapsed cycle time.

The selected deterministic BP/VTR and IR-BP unit gates pass. Equation (8) still requires a documented sensitivity test because the paper's prose and formula admit conflicting physical interpretations. Live downstream-candidate discovery, TraCI route mutation, SUMO integration, and the reconstructed terminal network are not implemented yet.

## Documents

- [Paper analysis](docs/01_paper_analysis.md)
- [Implementation specification](docs/02_implementation_spec.md)
- [Project structure](docs/03_project_structure.md)
- [Reproduction checklist](docs/04_reproduction_checklist.md)
- [Phase 1 reconstruction decisions](docs/05_phase1_assumptions.md)

## Repository policy

The IEEE PDF is local reference material and is excluded by `.gitignore`. Commit only original code, configuration, reconstructed SUMO assets, and generated summaries that are suitable for redistribution.

## Verification

Run the dependency-free Phase 1 test gate from this directory:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -p "test_*.py" -v
```

## Next milestone

Pin the SUMO/Python environment, then build a one-intersection TraCI smoke scenario that connects the verified pure control and routing policies to simulation state.
