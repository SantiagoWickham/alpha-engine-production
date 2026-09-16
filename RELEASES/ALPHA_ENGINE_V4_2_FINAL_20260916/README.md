# Alpha Engine V4.2 — Final Local Production Freeze

Freeze date: 2026-09-16

## Production root

C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION

## Runtime state at freeze

- Web: V4.2
- Market: automatic every 5 minutes during regular US session
- Forward model session: 2026-09-15
- Latest completed market session: 2026-09-15
- Forward stale: False
- Forward NAV: 2026-09-04 -> 2026-09-15
- Holdout parity: PASS
- Recommendations: PENDING_REAL_PORTFOLIO
- LLM: PAUSED
- Real orders: NO
- V13 sealed core: unchanged

## Canonical local runtime files

- web\run_alpha_engine_v4.py
- web\v4\
- START_ALPHA_ENGINE_V4.ps1
- ALPHA_ENGINE_DATA_RECOVERY_V1\scripts\build_forward_nav_v42.py
- ALPHA_ENGINE_DATA_RECOVERY_V1\scripts\smoke_v42.py
- PRODUCT\AlphaEngine_Cartera_Real.xlsx (LOCAL RUNTIME / future personal data)
- PRODUCT\personal_portfolio_ledger_v4.json (LOCAL RUNTIME / future personal data)
- PRODUCT\personal_portfolio_ledger_v4.csv (LOCAL RUNTIME / future personal data)

## Personal portfolio policy

Personal operations are intentionally NOT included in this release snapshot.
After this freeze, real operations can be loaded through the V4.2 interface.
Do not publish personal ledger data to a public repository.

## Secrets excluded

Never commit:

- .env
- secrets\
- *.clixml
- API keys / tokens
- MMM_SEC_USER_AGENT value
- Groq credentials

## Execution scripts

See docs\EXECUTION_SCRIPT_INDEX.csv.
Scripts tagged USED_IN_FINAL_CHAIN are the ones that materially led to the final V4.2 state.
Older scripts are retained only as history and should not be used as current deployment entrypoints.

## Git

This release is frozen in-place in the existing production repository.
The RELEASES folder is documentation/snapshot material only; the live code remains in its canonical paths.
