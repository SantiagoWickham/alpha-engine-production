V13 Phase 3R FAST CACHED PORTFOLIO RESEARCH

Purpose: stop retraining/rebuilding the expensive six-horizon scores for every portfolio fix.
Requires existing outputs/v13_phase3_advisor_surface.parquet from Phase 3 FIX2.

Key corrections/research in one run:
1) Execution availability uses raw observable close on ALL market rows, never research_eligible.
2) Total-return price remains for valuation/returns when available; raw close is fallback return only.
3) Universe equal-weight benchmark uses previous-session research eligibility (causal membership).
4) Six horizons remain active. Reliability weights use only pre-2021 OOF evidence; no mechanical 252D precision domination.
5) Dynamic sparsity uses an opportunity-cost penalty selected in 2021-2022; no fixed Top-N.
6) 2023-2024 is confirmation only. 2025+ remains blocked.

Run: .\RUN_V13_PHASE3_FAST.ps1
