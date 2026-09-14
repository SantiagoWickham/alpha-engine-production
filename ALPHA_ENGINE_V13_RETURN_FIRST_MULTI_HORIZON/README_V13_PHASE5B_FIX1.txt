ALPHA ENGINE V13 - PHASE 5B FIX1
SEC transport/cache integrity repair only.

Changes:
- Decompresses gzip/deflate HTTP bodies before JSON decoding.
- Uses a declared SEC User-Agent (override with ALPHA_ENGINE_SEC_USER_AGENT).
- Refuses to treat an empty/failed legacy parquet as a valid SEC cache.
- Persists outputs/live_shadow/v13_live_sec_audit.csv before a SEC quality gate raises.
- Does NOT modify the sealed V13 model, features, policy, thresholds, scores, or portfolio mechanics.

Run the same command:
  .\\RUN_V13_PHASE5B_LIVE_SHADOW.ps1
