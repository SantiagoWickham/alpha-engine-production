ALPHA ENGINE V12 - PHASE 3 FIX1
BUILD: V2_TICKER_SESSIONS_2026-09-12

WHY THIS FIX EXISTS
Phase 3 V1 measured H sessions on one global union calendar and required a ticker price on the exact global exit date. That created artificial MISSING_EXIT rows for assets whose observed trading dates do not perfectly match the union calendar.

V2 POLICY
- signal timestamp remains session close
- requested_entry_date remains the PIT panel's next global session
- actual entry_date is the first observed tradable ticker session on/after requested_entry_date
- H-session targets count the ticker's own observed tradable sessions
- known delisting => TERMINAL_DELISTING with terminal validated target price
- sample boundary => RIGHT_CENSORED_SAMPLE_END, no label
- early unexplained end of ticker history => UNRESOLVED_TERMINATION, no label AND BLOCKING gate
- no gate threshold is relaxed to make the phase pass
- target_total_return_price remains target-only and feature-forbidden

RUN
Set-ExecutionPolicy -Scope Process Bypass
.\RUN_PHASE3.ps1
