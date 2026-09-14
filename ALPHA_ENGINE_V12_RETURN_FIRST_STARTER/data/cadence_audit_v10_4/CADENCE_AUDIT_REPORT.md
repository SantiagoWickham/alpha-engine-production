# V10.4 Cadence Shootout — Result

- Audit version: `CADENCE_RC1_3`
- Model core: `V10.4_FROZEN_UNCHANGED`
- Preregistration SHA-256: `d08ae2d0228faf348d56189204d94b39ae5b86d347ffbf3171b7e6152bc2054a`
- Common sample: `2014-02-03` to `2026-08-31`
- Universe intersections: `181` tickers
- Selection cost: `60 bps one-way`
- SPY benchmark source: `data\v10_2\benchmark_monthly_returns.parquet`; status: `PASS_PERSISTED_MONTHLY_BENCHMARK`; daily SPY download: `NO`

## Pre-registered decision
**Selected cadence: MONTHLY**

No more-frequent cadence passed every preregistered replacement gate.

## Scientific status
This shootout changes cadence only. It does not solve survivorship, historical data-vintage, research-trial inventory, local CEDEAR capacity, or future-alpha uncertainty.
A cadence selected here must still receive the full final audit before official forward capital starts.

## Same-close monthly replication diagnostic
```json
{
  "status": "DIAGNOSTIC_ONLY",
  "matched_periods": 150,
  "mean_abs_error_bps": 8.645417113835146,
  "p95_abs_error_bps": 17.465786734661386,
  "max_abs_error_bps": 514.1346174136961,
  "warning": "Cadence audit rebuilds PIT states from SEC facts; crosscheck is a calibration diagnostic, not a selection metric."
}
```

## Primary 60 bps comparison

```text
cadence     cagr  spy_cagr  cagr_spread_vs_spy  ann_vol_daily  max_drawdown  annual_turnover_target_convention  ff5_mom_alpha_ann  ff5_mom_alpha_hac_t
MONTHLY 0.211896  0.138896            0.073000       0.217918     -0.311919                           1.896698           0.075533             2.257338
 WEEKLY 0.177253  0.138896            0.038357       0.214181     -0.310365                           4.289051           0.053766             1.398301
  DAILY 0.123423  0.138896           -0.015473       0.212765     -0.343805                           8.981081           0.008682             0.215510
```

## Monthly intramonth giveback
```json
{
  "intervals": 151,
  "mean_mfe": 0.047964919333773705,
  "median_mfe": 0.039910444968641434,
  "mean_giveback": 0.02819378802847685,
  "median_giveback": 0.015821346562542297,
  "p90_giveback": 0.07143245222397841,
  "share_giveback_gt_10pp": 0.046357615894039736,
  "share_mfe_gt_20pct": 0.006622516556291391,
  "interpretation": "Descriptive portfolio-level excursion audit. It does not imply that an optimal take-profit exists or should be added."
}
```
