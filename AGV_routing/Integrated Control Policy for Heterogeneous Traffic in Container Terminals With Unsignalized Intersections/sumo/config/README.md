# SUMO configurations

`paper_baseline.sumocfg` connects the reconstructed paper-grid network to the deterministic seed-1 baseline demand. It fixes the one-second clock, seed, single SUMO thread, `10800 s` hard end, collision reporting, junction checks, and disabled teleport escape. The Python runner still owns the authoritative completion, collision, teleport, and exact-ID gates.
