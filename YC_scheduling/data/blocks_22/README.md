# 22 Block Instance Set

This directory contains 22 deterministic, distinct yard-block instances.

- Layout: 20 bays, 10 rows, 6 tiers
- Jobs per block: 15 outbound and 5 inbound
- Initial state: scheduled containers, support containers, blockers, and background stacks
- Handover bay: bay 10 with one fixed transfer slot per row
- Motion and physical rules: identical across all blocks
- Variation: job stacks, rows, tiers, blocker counts, inbound destinations, and background occupancy

`manifest.json` records each seed and structural count. Run all three policies with:

```powershell
.\.venv\Scripts\python.exe scripts\run_22_block_batch.py
```
