---
status: accepted
---

# Atomically publish versioned signal profiles

Users will edit and validate a draft Signal Profile Version before explicitly publishing it. A Managed Instance switches to the complete published version at a scan-cycle boundary, preserves state for retained symbols, establishes a Live Baseline for added symbols, archives removed-symbol history, and remains on the previous version if publication fails; this prevents partially applied configurations from changing Signal semantics mid-cycle.
