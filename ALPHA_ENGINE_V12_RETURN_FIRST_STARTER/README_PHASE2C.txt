ALPHA ENGINE V12 - PHASE 2C
RETURN PRICE ENRICHMENT

Purpose
-------
Phase 2B proved that PRIMARY/SECONDARY close is raw-close-like and adjusted-price coverage is insufficient.
Phase 2C creates a separate TARGET-ONLY total-return price layer. It NEVER overwrites execution close.

Core separation
---------------
close                     = observable/session-close price used for information/execution semantics
target_total_return_price = adjusted price used only to construct future-return labels
target_price_feature_allowed = False

What Phase 2C does
------------------
1. Reads the tickers Phase 2B marked as needing adjusted history.
2. Downloads Yahoo chart history with close + adjclose + dividends + splits into a NEW V12 cache.
3. Validates downloaded raw close against the canonical PIT panel ticker/date series.
4. Cross-checks downloaded adjclose against data/cache/market_ohlcv_6y.parquet where available.
5. Combines existing delisted adj_close with new active-ticker adjusted histories.
6. Requires >=99.5% eligible coverage and >=99.5% per ticker before labels are allowed.
7. Does NOT construct alpha, portfolio weights, optimizer output, or trades.

Run
---
From project root:
  Set-ExecutionPolicy -Scope Process Bypass
  .\RUN_PHASE2C.ps1

The downloader is restartable: successfully downloaded ticker files are cached under data/v12/adjusted_prices_yahoo.
If a provider request fails, rerun the same command; cached successes are reused.
