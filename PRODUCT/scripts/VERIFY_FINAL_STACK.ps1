param(
  [string]$Root = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_V12_RETURN_FIRST"
)
$ErrorActionPreference="Stop"

$checks = @(
  (Join-Path $Root "ALPHA_ENGINE_V12_RETURN_FIRST_STARTER"),
  (Join-Path $Root "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"),
  (Join-Path $Root "ALPHA_ENGINE_BYMA"),
  (Join-Path $Root "PRODUCT\web\index.html"),
  (Join-Path $Root "PRODUCT\sheets\Code.gs"),
  (Join-Path $Root "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON\outputs\v13_phase3z_nav_20bps.csv"),
  (Join-Path $Root "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON\outputs\v13_phase4_holdout_nav_20bps.csv"),
  (Join-Path $Root "ALPHA_ENGINE_BYMA\outputs\byma_pre2025_nav_20bps.csv"),
  (Join-Path $Root "ALPHA_ENGINE_BYMA\outputs\byma_holdout_nav_20bps.csv"),
  (Join-Path $Root "ALPHA_ENGINE_BYMA\outputs\byma_current_target.csv")
)

$fail=@()
foreach($p in $checks){
  if(Test-Path $p){ Write-Host "PASS  $p" }
  else { Write-Host "FAIL  $p"; $fail += $p }
}

if($fail.Count -gt 0){
  Write-Host ""
  Write-Host "FINAL_VERIFY: FAIL"
  exit 2
}

Write-Host ""
Write-Host "FINAL_VERIFY: PASS"
Write-Host "V13 IDEAL + BYMA TRANSFER + PRODUCT are structurally present."
