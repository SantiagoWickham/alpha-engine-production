ALPHA ENGINE V12 — PHASE 2B
PRICE SEMANTICS & CORPORATE ACTION GATE

Extract this ZIP directly into the existing ALPHA_ENGINE_V12_RETURN_FIRST_STARTER root.
Then run from PowerShell:

  Set-ExecutionPolicy -Scope Process Bypass
  .\RUN_PHASE2B.ps1

This phase does NOT train a model and does NOT create forward-return targets.
It determines whether the historical price series is safe for target construction.

Validated together with Phase 1 + Phase 2 test suite: 21 tests passed.
