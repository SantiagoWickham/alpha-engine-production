ALPHA ENGINE V12 - PHASE 3C
TERMINAL OUTCOME REPAIR
BUILD V1_2026-09-12

Purpose
-------
Resolve the Phase 3 UNRESOLVED_TERMINATION gate without weakening it.

Rules
-----
1. 175 historical equity terminations are accepted only when at least three independent local evidence sources place the delisting within four calendar days of the last validated return price and the historical company identity agrees.
2. ABXL is NOT terminalized as an equity delisting. SEC evidence shows that ABXL is the 9.875% senior-notes symbol after Abacus Global Management moved common stock from ABL to ABX. The contaminated ABXL window is excluded from equity research.
3. Terminal metadata and manual data-quality exclusions are feature-forbidden. They are used only to construct/audit valid research outcomes and data eligibility.
4. Phase 3 is rebuilt automatically and must still produce zero UNRESOLVED_TERMINATION at every horizon.

Run
---
Set-ExecutionPolicy -Scope Process Bypass
.\RUN_PHASE3C.ps1
