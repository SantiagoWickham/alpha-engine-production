ALPHA ENGINE V13 - PHASE 5B FIX4
SEC FACT SCHEMA ALIGNMENT / PARQUET SAFETY

Cause fixed:
Historical SEC facts and live SEC facts could represent date metadata with different
Python/pandas types (e.g. historical `end` as numeric YYYYMMDD and live `end` as an
ISO string). After concat, pandas produced object columns and pyarrow refused to
write the runtime parquet.

FIX4 changes DATA TRANSPORT ONLY:
- Canonicalizes SEC `start`, `end`, `filed` to nullable ISO YYYY-MM-DD strings.
- Canonicalizes `value` to float64 and `fy` to nullable Int64.
- Canonicalizes SEC categorical metadata to nullable pandas string dtype.
- Aligns any extra SEC columns deterministically to a common parquet-safe dtype.
- Does NOT modify the sealed predictor, features, Phase3Z policy, horizon weights,
  costs, thresholds, scores, or portfolio rules.

The included test exercises the mixed historical/live schema. On machines with
pyarrow installed it also performs an actual parquet write/read round-trip before
5B can proceed.

Run the same command:
  .\RUN_V13_PHASE5B_LIVE_SHADOW.ps1
