ALPHA ENGINE V13 - PHASE 3W
PRE-HOLDOUT STRESS + FREEZE

Purpose
-------
This phase does NOT retune the predictor or portfolio. It reuses the exact Phase3V selected policy, replaces the legacy all-six-row OOF completeness gate with a maturity-aware dynamic-routing audit, stress-tests the fixed policy at 20/40/60/80/100 bps, and writes a cryptographic freeze manifest before 2025+ is opened.

Run from the STARTER directory:
  .\RUN_V13_PHASE3W.ps1

2025+ remains hard-blocked in this phase.
