ALPHA ENGINE V13 - PHASE 1 FIX1
BUILD: V13_P1_FIX1_RESEARCH_KEY_PRICE_COVERAGE_2026-09-12

WHY THIS FIX EXISTS
The original FEATURE_PRICE_COVERAGE gate measured adjusted-price coverage over the entire
pre-2025 raw market table. That denominator includes warm-up/stale/non-target rows that do
not enter V13 feature research. The gate must measure coverage on the exact (signal_date,
ticker) keys that enter the Phase 1 research feature panel.

WHAT CHANGED
- FEATURE_PRICE_COVERAGE still requires >= 0.995.
- The threshold was NOT lowered.
- The blocking gate now uses research_key_price_coverage.
- raw_market_price_coverage remains reported as a diagnostic.
- Missing research keys are exported to:
  outputs/v13_phase1_missing_research_price_audit.csv
- If research-key coverage remains below 0.995, Phase 1 still FAILS.

WHAT DID NOT CHANGE
- 2025+ remains blocked.
- Development/validation partitions unchanged.
- 95-feature design unchanged.
- Multi-horizon 5/10/20/60/120/252 unchanged.
- Candidate FDR / IC criteria unchanged.
- Size treatment unchanged.
- Benchmark logic unchanged.

RUN
Extract over the existing V12 starter root and run:
  .\RUN_V13_PHASE1.ps1

No need to delete previous Phase 1 outputs; the rerun overwrites Phase 1 outputs.
