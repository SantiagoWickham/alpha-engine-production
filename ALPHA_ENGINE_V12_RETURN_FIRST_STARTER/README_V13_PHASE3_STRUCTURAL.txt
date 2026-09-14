ALPHA ENGINE V13 - PHASE 3S FAST STRUCTURAL REPAIR
BUILD: V13_P3S_FAST_STRUCTURAL_REPAIR_2026-09-12

Purpose
-------
Resolve the remaining Phase-3 portfolio/execution bottlenecks without retraining models.

This runner:
- reuses outputs/v13_phase3_advisor_surface.parquet;
- never loads 2025+;
- creates a cached execution surface from canonical PIT raw close + Phase2C raw close + provider raw close;
- uses adjusted/total-return prices only for mark-to-market, never for execution;
- keeps 5/10/20/60/120/252 active simultaneously;
- makes horizon weights dynamic by asset/day using a pre-2021 OOF reliability prior plus current term-structure evidence;
- searches return/alpha conviction gates and alpha-aware sizing instead of Top-N or a fixed cardinality;
- evaluates 81 policies at 20bps and 40bps round-trip costs.

Run from the V12 starter root:
    .\RUN_V13_PHASE3_STRUCTURAL.ps1

Outputs are written to the sibling V13 workspace /outputs folder.
