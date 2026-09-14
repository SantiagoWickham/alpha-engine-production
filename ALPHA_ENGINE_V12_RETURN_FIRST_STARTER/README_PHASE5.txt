ALPHA ENGINE V12 - PHASE 5
MODEL ARCHITECTURE TOURNAMENT
BUILD: V1_FIX2_GATE_SEMANTICS_2026-09-12

Extract this ZIP directly over the existing project root.
Then run in PowerShell:

  Set-ExecutionPolicy -Scope Process Bypass
  .\RUN_PHASE5.ps1

Phase 5 never opens final OOS 2025+ for model selection.
It reconstructs the feature pool from DEVELOPMENT evidence only to avoid double-using Phase 4 validation.

FIX1: prevents duplicate horizon_sessions insertion when the development-only pool already carries the horizon field. No statistical logic, split boundary, OOS firewall, model list, or cost assumption changed.
