# Experiment configurations

Store human-readable, version-controlled experiment settings here. A run must copy its fully resolved configuration into its output directory.

`paper_baseline.toml` distinguishes values stated by the paper from unresolved reconstruction decisions. It is parseable with the standard `tomllib`; no YAML dependency is required.

The `[network]` table records paper-level constraints. `[network.reconstruction]` records the exact Fig. 6 topology choices implemented by `sumo/networks/paper_grid/paper_grid.manifest.toml`: coordinates, direction pattern, source lengths, gate portals, legal-turn rule, and virtual-phase rule. These values are explicit reconstruction assumptions, not recovered author inputs. The manifest remains the network builder's source of truth; a run must preserve both the resolved experiment configuration and the manifest/artifact hashes.

The `[environment]` table records the selected reconstruction runtime. Exact dependency artifacts and hashes are locked in the repository's `uv.lock`; the paper itself does not publish these versions.

The full runner also consumes the explicit drain timeout, 30 m route-decision trigger, 7.5 m vehicle slot, downstream-intersection destination coordinate, and seeded HDV alternative-route rules. These are reconstruction assumptions. The `paper_method_fidelity` control profile remains zero-clearance and unbounded for HDV extension; any finite-cap experiment requires a separately labeled safety profile.
