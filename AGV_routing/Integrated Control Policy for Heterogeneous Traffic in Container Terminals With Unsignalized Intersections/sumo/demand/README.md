# Demand assets

This directory contains deterministic generated demand for the reconstructed paper grid:

- `paper_baseline.rou.xml`: SUMO vehicle types, vehicles, departure times, and initial routes.
- `paper_baseline.metadata.json`: resolved demand inputs, declared assumptions, counts, dependency hashes, and route-file hash.

Baseline: seed `1`, a `7200 s` departure horizon, `2000 vehicles/h`, and exactly `10%` HDVs. Expected totals are `4000` vehicles, `400` HDVs, and `3600` CAVs. The 24 five-minute bin quotas repeat `[166,167,167]` eight times.

Build or verify:

```powershell
uv run python scripts/build_paper_grid_demand.py
uv run python scripts/build_paper_grid_demand.py --check
```

Do not hand-edit generated files. The generator samples reachable, class-valid OD pairs, assigns exact quotas and balanced HDV speed types, and gives every vehicle a shortest-distance initial route. Gate counts are HDV OD category quotas, not observed portal flow. The paper's `20%` per-intersection HDV alternative choice remains runtime behavior for the future TraCI runner; it is not represented by static alternative routes.

See [seeded demand reconstruction](../../docs/09_seeded_demand.md) for paper facts, reconstruction decisions, invariants, and current scope.
