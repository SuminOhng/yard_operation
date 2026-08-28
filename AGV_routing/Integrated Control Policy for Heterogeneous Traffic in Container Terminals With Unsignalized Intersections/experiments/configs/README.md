# Experiment configurations

Store human-readable, version-controlled experiment settings here. A run must copy its fully resolved configuration into its output directory.

`paper_baseline.toml` distinguishes values stated by the paper from unresolved reconstruction decisions. It is parseable with Python 3.11's standard `tomllib`; no YAML dependency is required.
