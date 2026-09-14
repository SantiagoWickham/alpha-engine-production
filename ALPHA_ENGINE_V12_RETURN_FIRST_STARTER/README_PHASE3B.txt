ALPHA ENGINE V12 - PHASE 3B
UNRESOLVED TERMINATION AUDIT
BUILD: V1_2026-09-12

Purpose:
- Do NOT alter Phase 3 labels.
- Identify tickers whose target-price history terminates before the requested horizon without validated delisting metadata.
- Cross-check listing_lifecycle, Alpha Vantage active/delisted status, and the delisted-price cache.
- Produce a repair plan before any alpha research.

Run from project root:
  Set-ExecutionPolicy -Scope Process Bypass
  .\RUN_PHASE3B.ps1
