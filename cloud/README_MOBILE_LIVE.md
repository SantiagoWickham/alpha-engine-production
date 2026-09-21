# Alpha Engine Mobile Live

Public read-only delivery layer for Alpha Engine.

## Market
- GitHub Actions checks every 5 minutes during a broad Argentina-time window.
- A Yahoo `currentTradingPeriod` guard allows the expensive 200-asset refresh only during the US regular session.
- Manual `workflow_dispatch` forces one snapshot, useful for bootstrap/testing.
- No V13 mutation and no real orders.

## Model / Forward
- Runs Monday-Friday at 19:30 `America/Argentina/Buenos_Aires`.
- Executes sealed Phase5B, rebuilds Forward NAV, verifies the six critical sealed V13 files byte-for-byte, then publishes only safe model/Forward output.
- Manual runs are explicitly classified as bootstrap/catch-up rather than contemporaneous scheduled forward observations.

## Public mobile data
Only model/market information is published. Personal portfolio ledger, cash, purchase prices, P&L, secrets, and real orders are not published.
