ALPHA ENGINE V13 - PHASE 1 FIX2
BUILD: V13_P1_FIX2_CANONICAL_PIT_PANEL_2026-09-12

ROOT CAUSE
Phase 1 FIX1 compared Phase 3 research keys against only production_market_ohlcv + market_ohlcv_extended.
Those raw caches omit a material set of historical/delisted names. Phase 2 had already integrated primary,
secondary and delisted market sources into outputs/phase2_canonical_pit_panel.parquet, then applied the
trading calendar, historical universe snapshots and lifecycle eligibility before any model research.

FIX2
- Formally adds outputs/phase2_canonical_pit_panel.parquet to the V13 Phase 0 allowed-source contract.
- Phase 1 uses research_eligible rows from the Phase 2 canonical PIT panel as the market surface.
- Adjusted feature-price enrichment remains backward-looking and scale-invariant; no price level is exported.
- The >=99.5% research-key price coverage gate is unchanged.
- Missing research-key prices remain blocking and are exported for audit.
- 2025+ remains hard-blocked for all research selection.
- No V12 Phase 4+ feature/model/policy/OOS artifact is admitted.

INSTALL/RUN
1) Extract over the existing V12 starter root.
2) Run .\RUN_V13_PHASE0.ps1 once to amend the formal allowed-source contract.
3) Run .\RUN_V13_PHASE1.ps1.
