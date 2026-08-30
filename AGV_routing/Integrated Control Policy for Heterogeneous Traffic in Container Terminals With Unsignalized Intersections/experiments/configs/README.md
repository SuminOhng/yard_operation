# Experiment configurations

Store human-readable, version-controlled experiment settings here. A run must copy its fully resolved configuration into its output directory.

`paper_baseline.toml` distinguishes values stated by the paper from unresolved reconstruction decisions. It is parseable with the standard `tomllib`; no YAML dependency is required.

The `[environment]` table records the selected reconstruction runtime. Exact dependency artifacts and hashes are locked in the repository's `uv.lock`; the paper itself does not publish these versions.
