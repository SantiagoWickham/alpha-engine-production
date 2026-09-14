ALPHA ENGINE V13 - PHASE 5B FIX3
SEC CIK CANONICALIZATION

Cause fixed:
- SEC mapping CSV/history may expose integer CIKs as floats (example 789019.0).
- Previous string cleanup removed punctuation and turned 789019.0 into 7890190,
  producing the invalid SEC URL CIK0007890190.json.

Fix:
- preserve CSV CIK columns as strings where possible;
- canonical numeric normalization before zero-padding;
- supports int, float, quoted decimal, zero-padded and scientific notation;
- validates exact 10-digit canonical CIK before any SEC request;
- keeps FIX1 gzip/cache integrity and FIX2 .env identity/preflight behavior.

NO model/features/scores/policy/cost/seal change.
Run the same command:
  .\\RUN_V13_PHASE5B_LIVE_SHADOW.ps1
