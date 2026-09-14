ALPHA ENGINE V12 - PHASE 3: RETURN TARGET ENGINE
BUILD: V1_2026-09-12

PURPOSE
Build future-return labels only after Phase 2C has validated a target-only total-return-price layer.
No alpha features are created and no model is trained in this phase.

KEY POLICY
- Signal information timestamp: session close.
- Research entry anchor: NEXT SESSION CLOSE.
- Target returns: adjusted total-return-price space.
- Raw close remains the observable/execution reference and is never replaced.
- Future target data is stored in a physically separate parquet file.
- Phase 3 target columns are NEVER allowed as model features.

HORIZONS
1, 5, 10, 20, 40, 60, 120, 252 trading sessions after the entry anchor.

TARGETS PER HORIZON
- simple forward total return
- log forward total return
- MFE / MAE
- target end date and status
- cross-sectional future return rank
- top-decile and top-quintile winner labels

DELISTINGS
If a security is known to delist before the requested horizon, the target terminates at its last available validated total-return price and is explicitly marked TERMINAL_DELISTING.

RIGHT CENSORING
Signals whose horizon has not yet matured are marked RIGHT_CENSORED and receive no return label.

RUN
  Set-ExecutionPolicy -Scope Process Bypass
  .\RUN_PHASE3.ps1
