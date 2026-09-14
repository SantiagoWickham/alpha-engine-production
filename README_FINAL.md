# ALPHA ENGINE — Final Production Root

## Production tracks

1. **V13 IDEAL**  
   Frozen international/reference model.

2. **BYMA TRANSFER**  
   Local model: V13 forecast surface filtered to current BYMA-accessible universe before portfolio allocation.

3. **PERSONAL**  
   Actual discretionary portfolio. Never alters either model track.

## Rejected research

`PRODUCT/archive/BYMA_NATIVE_REJECTED` documents the rejected native branch.
No further native tuning is authorized.

## Product surfaces

- `PRODUCT/web`: static dashboard / GitHub Pages.
- `PRODUCT/sheets`: Google Apps Script bridge.
- `PRODUCT/scripts/EXPORT_WEB_DATA.ps1`: refresh dashboard JSON.
- `PRODUCT/scripts/VERIFY_FINAL_STACK.ps1`: structural verification.
- `PRODUCT/scripts/PUSH_SAFE_REPO_FILES.ps1`: stage only safe GitHub files.

## Data policy

GitHub is for code/config/docs/web/manifests. Large PIT datasets, parquet files,
model bundles, and full research outputs remain local/off-repo and require a separate backup.
