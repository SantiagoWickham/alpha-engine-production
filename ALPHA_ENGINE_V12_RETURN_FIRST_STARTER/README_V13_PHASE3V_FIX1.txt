V13 PHASE 3V FIX1 — CANONICAL V13 WORKSPACE RESOLUTION
BUILD: V13_P3V_FIX1_V13_WORKSPACE_RESOLUTION_2026-09-13

Fix:
- Phase3V now runs against the canonical sibling workspace:
  ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON
- It no longer looks for V13 outputs inside the V12 starter directory.
- Preflight validates Phase0 summary, Phase2U summary, Phase2U OOF scores,
  and Phase1 research targets before running portfolio research.
- Existing Phase3S execution-surface cache is reported but optional; if absent,
  the engine may rebuild its execution surface from approved source layers.
- 2025+ remains hard-blocked.

Run only:
  .\RUN_V13_PHASE3V.ps1

Do not rerun Phase0/1/2/2U.
