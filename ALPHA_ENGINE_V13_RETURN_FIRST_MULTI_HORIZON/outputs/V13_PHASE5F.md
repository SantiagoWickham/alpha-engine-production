ALPHA ENGINE V13 - PHASE 5F

Purpose
-------
Remove the only remaining portfolio-weight basis ambiguity before any execution proposal.

What it does
------------
1. Reads the existing MMM_ALPHA_VANTAGE_API_KEY from .env. It never prints or stores the key.
2. Fetches USD/ARS using Alpha Vantage CURRENCY_EXCHANGE_RATE as the certified primary source.
3. Attempts a non-blocking Yahoo Finance ARS=X corroboration.
4. Stores an auditable FX record with timestamps and hashes.
5. Converts ARS cash to USD.
6. Rebuilds CURRENT weights on total NAV (positions + cash).
7. Calls the original sealed Phase3Z economic-target translator again on that total-NAV basis.
8. Produces USD target values and shadow trade values.

It does NOT
-----------
- change the sealed predictor
- change Phase3Z
- tune on live data
- send orders
- append operations
- mutate cash
- write to Google Sheets

Run
---
.\RUN_V13_PHASE5F_FX_TOTAL_NAV_SIZING.ps1
