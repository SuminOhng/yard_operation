# Reproducible SUMO environment

The paper does not publish its SUMO or Python version. This reconstruction therefore selects a modern, fixed environment and treats it as an explicit assumption rather than a paper fact.

## Pinned components

| Component | Version | Role |
|---|---:|---|
| CPython | 3.13.13 | Project interpreter managed by `uv` |
| uv | 0.11.16 | Resolver and virtual-environment manager |
| Eclipse SUMO | 1.27.1 | Official Windows x86-64 application wheel |
| sumo-data | 1.27.1 | SUMO data files required by the application wheel |
| traci | 1.27.1 | Python client for the SUMO process |
| sumolib | 1.27.1 | SUMO network and artifact utilities |
| setuptools | 84.0.0 | Isolated editable-build backend |

SUMO 1.27.1 is the latest stable release available when this decision was recorded on 2026-08-30. All four SUMO distributions are pinned independently because their dependency ranges permit newer companion releases; silently mixing versions would weaken reproducibility. This baseline is explicitly Windows AMD64 because that is the platform under test.

Official references:

- [SUMO downloads and Python-package installation](https://eclipse.dev/sumo/docs/Downloads.html)
- [Eclipse SUMO 1.27.1 Windows wheel](https://pypi.org/project/eclipse-sumo/1.27.1/)
- [TraCI Python integration](https://eclipse.dev/sumo/docs/TraCI/Interfacing_TraCI_from_Python.html)
- [SUMO randomness and fixed seeds](https://eclipse.dev/sumo/docs/Simulation/Randomness.html)

## Setup

Install `uv 0.11.16`, enter the repository directory, and run:

```powershell
uv python install 3.13.13
uv sync --extra dev --frozen
uv run python scripts/verify_environment.py
```

The official `eclipse-sumo` wheel keeps binaries inside `.venv`. The verifier checks Windows AMD64, uv, Python, the lock hash, all pinned packages, imported-file ownership, and four SUMO executables. It derives `SUMO_HOME` from installed distribution metadata and invokes exact executable paths, so no permanent user-level `PATH` or `SUMO_HOME` change is required. If `SUMO_HOME` is already set to another installation, verification fails instead of silently mixing installations.

Run the unit gate through the locked interpreter:

```powershell
uv run python -m unittest discover -s tests -p "test_*.py" -v
```

## Experiment provenance

Every run must save the verifier's JSON output plus:

- Git commit SHA and `uv.lock` hash.
- Resolved experiment configuration and seed.
- Full SUMO command line, step length, begin/end times, and thread count.
- Input `.net.xml`, `.rou.xml`, `.sumocfg`, and additional-file hashes.
- Output file hashes.

Use explicit seeds and never use SUMO's `--random` option for reproduction runs. A future sensitivity run must separate software-version effects from policy-parameter effects.
