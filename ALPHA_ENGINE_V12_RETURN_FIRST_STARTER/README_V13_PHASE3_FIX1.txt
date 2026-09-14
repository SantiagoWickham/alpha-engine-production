ALPHA ENGINE V13 - PHASE 3 FIX1
BUILD: V13_P3_FIX1_ABSOLUTE_RETURN_KELLY_2026-09-12

WHY THIS FIX EXISTS
The original Phase 3 used robust benchmark excess as the Kelly mean vector and
also used the lower-confidence bound itself for sizing. That imposed two layers
of conservatism: every individual holding effectively had to beat the strongest
benchmark before entry, and uncertainty was subtracted again inside sizing.
The result on the real pre-2025 selection window was 0 qualified policies,
median 1 holding, max 2, and validation 100% cash.

FIX1 CONTRACT
- All 6 horizons remain simultaneous and are re-evaluated every session.
- 2025+ remains hard-blocked.
- Phase 2 champions are unchanged.
- Score calibration now exports BOTH:
    (a) expected absolute future return + HAC uncertainty, used for admission/sizing
    (b) expected robust benchmark alpha, retained as alpha diagnostics
- Entry eligibility uses expected-return LCB > economic hurdle.
- Kelly sizing uses posterior mean expected return, NOT the LCB (no double penalty).
- SPY/QQQ/Universe-EW remain portfolio-level qualification gates.
- No fixed Top-N, min weight, max weight, or holding period.
- The PASS standard is NOT relaxed: robust net excess CAGR must be >0 at base and stress costs in 2021-2022.

RUN
Extract over the V12 starter root (same place as previous V13 runner files), then:
  Set-ExecutionPolicy -Scope Process Bypass
  .\RUN_V13_PHASE3.ps1

Expected build signature:
  V13_P3_FIX1_ABSOLUTE_RETURN_KELLY_2026-09-12
