# Phase 2 - Canonical Point-in-Time Research Panel

Purpose: create the first V12 research table from data only, without inheriting any V10/V11 alpha, portfolio, optimizer or execution logic.

## Timing rules

- Market data is observed at session close.
- A close-based signal can execute no earlier than the next trading session.
- SEC facts are keyed by `filed` date.
- Because the current normalized source does not carry a reliable acceptance timestamp, a filing is usable only on the next trading session strictly after `filed`.
- The monthly PIT fundamental file is not the primary event clock; it is retained for later cross-checking.
- Historical universe membership uses the latest global monthly universe snapshot available at or before each date. No per-ticker stale membership carry-forward is allowed.

## Outputs

The canonical panel is not an alpha model. It contains point-in-time information and eligibility flags only. Forward returns, targets, features, model fitting, portfolio construction and execution are later phases.
