# IR-BP container-terminal traffic-control replica

This project reconstructs the method in *Integrated Control Policy for Heterogeneous Traffic in Container Terminals With Unsignalized Intersections* (IEEE T-ITS, 2025, DOI: 10.1109/TITS.2025.3560067).

The first target is a method-faithful implementation of the BP-based virtual token ring (VTR) controller and the IR-BP CAV router. Numerical agreement with the paper is a later calibration target because the paper does not publish its code, exact SUMO network, demand files, random seeds, SUMO version, or every controller parameter.

## Current phase

Phase 0 is complete: paper analysis, implementation specification, project layout, and reproduction checklist.

No control algorithm or SUMO scenario is implemented yet.

## Documents

- [Paper analysis](docs/01_paper_analysis.md)
- [Implementation specification](docs/02_implementation_spec.md)
- [Project structure](docs/03_project_structure.md)
- [Reproduction checklist](docs/04_reproduction_checklist.md)

## Repository policy

The IEEE PDF is local reference material and is excluded by `.gitignore`. Commit only original code, configuration, reconstructed SUMO assets, and generated summaries that are suitable for redistribution.

## Next milestone

Implement pure-Python equations and Algorithms 1-3 with unit tests before connecting them to TraCI.
