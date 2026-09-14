ALPHA ENGINE V12 - PHASE 2C FIX3 FLAT
Build: FIX3_FLAT_2026-09-12

IMPORTANT:
This ZIP is intentionally FLAT. Its top-level entries are:
  src/
  scripts/
  tests/
  config/
  RUN_PHASE2C.ps1

Extract these directly into ALPHA_ENGINE_V12_RETURN_FIRST_STARTER and replace existing files.

The runner refuses to execute unless the root source file contains the FIX3 build signature.
Expected console lines:
  BUILD: FIX3_FLAT_2026-09-12
  MODULE: ...\ALPHA_ENGINE_V12_RETURN_FIRST_STARTER\src\alpha_engine_v12\return_price_enrichment.py

The corrected gate:
- validates provider identity against best(raw close, adjusted close)
- allows short-history securities such as SPCX when all available history is validated
- treats a disjoint local adjusted reference as NOT_APPLICABLE, not FAIL
