$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION"
$REC  = Join-Path $ROOT "ALPHA_ENGINE_DATA_RECOVERY_V1"
$V13  = Join-Path $ROOT "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"

$ACTUAL_STARTER = Join-Path $ROOT "ALPHA_ENGINE_V12_RETURN_FIRST_STARTER"
$ACTUAL_OUTPUTS = Join-Path $ACTUAL_STARTER "outputs"

$LEGACY_PARENT = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_V12_RETURN_FIRST"
$LEGACY_STARTER = Join-Path $LEGACY_PARENT "ALPHA_ENGINE_V12_RETURN_FIRST_STARTER"

$VERIFY = Join-Path $REC "scripts\verify_forward_source_alias.py"
$CATCH  = Join-Path $REC "scripts\catchup_v41.py"

$CANON = "phase2_canonical_pit_panel.parquet"
$RET   = "phase2c_return_price_layer.parquet"

Write-Host ""
Write-Host "================================================================"
Write-Host "ALPHA ENGINE - FORWARD SOURCE REPAIR"
Write-Host "COMPATIBILITY JUNCTION + PHASE 5B CATCH-UP"
Write-Host "NO V13 CODE CHANGE / NO MODEL CHANGE / NO TUNING"
Write-Host "================================================================"

if (-not (Test-Path $ACTUAL_OUTPUTS)) {
    throw "Actual V12 outputs folder missing: $ACTUAL_OUTPUTS"
}

foreach ($name in @($CANON,$RET)) {
    $p = Join-Path $ACTUAL_OUTPUTS $name
    if (-not (Test-Path $p)) {
        throw "Required V12 input missing: $p"
    }
}

if (-not (Test-Path $CATCH)) {
    throw "V4.1 catch-up helper missing: $CATCH"
}

Write-Host ""
Write-Host "[1/7] SNAPSHOT SEALED V13 + V12 SOURCE HASHES"

$critical = @(
  "outputs\v13_phase2r_model_spec.json",
  "outputs\v13_phase2u_expert_evidence.csv",
  "outputs\v13_phase3aa_freeze_manifest.json",
  "outputs\v13_phase4_sealed_features.csv",
  "outputs\v13_phase4_model_seal_manifest.json",
  "outputs\v13_phase4_sealed_model_bundle.joblib"
)

$v13Before = @{}
foreach($rel in $critical) {
    $p = Join-Path $V13 $rel
    if (-not (Test-Path $p)) {
        throw "Critical V13 file missing: $p"
    }
    $v13Before[$rel] = (Get-FileHash -Algorithm SHA256 $p).Hash
}

$v12Before = @{}
foreach($name in @($CANON,$RET)) {
    $p = Join-Path $ACTUAL_OUTPUTS $name
    $v12Before[$name] = (Get-FileHash -Algorithm SHA256 $p).Hash
}

Write-Host "  PASS V13 6/6"
Write-Host "  PASS V12 source 2/2"

Write-Host ""
Write-Host "[2/7] CREATE LEGACY SOURCE COMPATIBILITY"

New-Item `
    -ItemType Directory `
    -Force `
    -Path $LEGACY_PARENT |
    Out-Null

if (Test-Path $LEGACY_STARTER) {

    $requiredLegacy = @(
        (Join-Path $LEGACY_STARTER "outputs\$CANON"),
        (Join-Path $LEGACY_STARTER "outputs\$RET")
    )

    $allGood = $true
    foreach($p in $requiredLegacy) {
        if (-not (Test-Path $p)) {
            $allGood = $false
        }
    }

    if (-not $allGood) {
        throw (
            "Legacy starter path already exists but is incomplete. " +
            "Nothing was deleted: $LEGACY_STARTER"
        )
    }

    Write-Host "  existing compatible path accepted"
}
else {
    New-Item `
        -ItemType Junction `
        -Path $LEGACY_STARTER `
        -Target $ACTUAL_STARTER |
        Out-Null

    Write-Host "  junction created"
}

Write-Host "  legacy : $LEGACY_STARTER"
Write-Host "  target : $ACTUAL_STARTER"

Write-Host ""
Write-Host "[3/7] PARQUET STRUCTURE GATE"

[IO.File]::WriteAllBytes(
    $VERIFY,
    [Convert]::FromBase64String("CmZyb20gX19mdXR1cmVfXyBpbXBvcnQgYW5ub3RhdGlvbnMKaW1wb3J0IGpzb24KZnJvbSBwYXRobGliIGltcG9ydCBQYXRoCmltcG9ydCBweWFycm93LnBhcnF1ZXQgYXMgcHEKCmFjdHVhbCA9IFBhdGgociJDOlxVc2Vyc1xzYW50aVxPbmVEcml2ZVxFc2NyaXRvcmlvXEFMUEhBX0VOR0lORV9QUk9EVUNUSU9OXEFMUEhBX0VOR0lORV9WMTJfUkVUVVJOX0ZJUlNUX1NUQVJURVJcb3V0cHV0cyIpCmNvbXBhdCA9IFBhdGgociJDOlxVc2Vyc1xzYW50aVxPbmVEcml2ZVxFc2NyaXRvcmlvXEFMUEhBX0VOR0lORV9WMTJfUkVUVVJOX0ZJUlNUXEFMUEhBX0VOR0lORV9WMTJfUkVUVVJOX0ZJUlNUX1NUQVJURVJcb3V0cHV0cyIpCgpmaWxlcyA9IFsKICAgICJwaGFzZTJfY2Fub25pY2FsX3BpdF9wYW5lbC5wYXJxdWV0IiwKICAgICJwaGFzZTJjX3JldHVybl9wcmljZV9sYXllci5wYXJxdWV0IiwKXQoKcmVwb3J0ID0ge30KCmZvciBuYW1lIGluIGZpbGVzOgogICAgYSA9IGFjdHVhbCAvIG5hbWUKICAgIGMgPSBjb21wYXQgLyBuYW1lCgogICAgaWYgbm90IGEuZXhpc3RzKCk6CiAgICAgICAgcmFpc2UgU3lzdGVtRXhpdChmIkFDVFVBTF9NSVNTSU5HOiB7YX0iKQogICAgaWYgbm90IGMuZXhpc3RzKCk6CiAgICAgICAgcmFpc2UgU3lzdGVtRXhpdChmIkNPTVBBVF9NSVNTSU5HOiB7Y30iKQoKICAgIHBhID0gcHEuUGFycXVldEZpbGUoYSkKICAgIHBjID0gcHEuUGFycXVldEZpbGUoYykKCiAgICBpZiBwYS5tZXRhZGF0YS5udW1fcm93cyA8PSAwIG9yIHBjLm1ldGFkYXRhLm51bV9yb3dzIDw9IDA6CiAgICAgICAgcmFpc2UgU3lzdGVtRXhpdChmIkVNUFRZX1BBUlFVRVQ6IHtuYW1lfSIpCgogICAgaWYgcGEuc2NoZW1hLm5hbWVzICE9IHBjLnNjaGVtYS5uYW1lczoKICAgICAgICByYWlzZSBTeXN0ZW1FeGl0KGYiU0NIRU1BX01JU01BVENIOiB7bmFtZX0iKQoKICAgIGlmIHBhLm1ldGFkYXRhLm51bV9yb3dzICE9IHBjLm1ldGFkYXRhLm51bV9yb3dzOgogICAgICAgIHJhaXNlIFN5c3RlbUV4aXQoZiJST1dDT1VOVF9NSVNNQVRDSDoge25hbWV9IikKCiAgICByZXBvcnRbbmFtZV0gPSB7CiAgICAgICAgImFjdHVhbCI6IHN0cihhKSwKICAgICAgICAiY29tcGF0Ijogc3RyKGMpLAogICAgICAgICJyb3dzIjogcGEubWV0YWRhdGEubnVtX3Jvd3MsCiAgICAgICAgImNvbHVtbnMiOiBsZW4ocGEuc2NoZW1hLm5hbWVzKSwKICAgIH0KCnByaW50KGpzb24uZHVtcHMocmVwb3J0LCBpbmRlbnQ9MikpCg==")
)

python $VERIFY

if ($LASTEXITCODE -ne 0) {
    throw "Forward source Parquet verification failed."
}

Write-Host "  PASS compatibility pair is readable"

Write-Host ""
Write-Host "[4/7] CURRENT FORWARD CLOCK"

try {
    $job = Invoke-RestMethod `
        -Uri "http://127.0.0.1:8765/api/v4/forward/job" `
        -TimeoutSec 40

    Write-Host "  model session : $($job.current_model_session)"
    Write-Host "  market session: $($job.latest_completed_market_session)"
    Write-Host "  stale         : $($job.stale)"
}
catch {
    throw "V4.1 server is not reachable on port 8765."
}

Write-Host ""
Write-Host "[5/7] PHASE 5B FORWARD CATCH-UP"

Set-Location $ROOT

python $CATCH

if ($LASTEXITCODE -ne 0) {
    throw (
        "Phase 5B still failed after repairing the historical source path. " +
        "Do not change model parameters."
    )
}

Write-Host ""
Write-Host "[6/7] FINAL FORWARD CLOCK"

$finalJob = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8765/api/v4/forward/job" `
    -TimeoutSec 40

$finalV13 = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8765/api/v4/v13" `
    -TimeoutSec 40

Write-Host "  model session : $($finalJob.current_model_session)"
Write-Host "  market session: $($finalJob.latest_completed_market_session)"
Write-Host "  stale         : $($finalJob.stale)"
Write-Host "  V13 status    : $($finalV13.status)"
Write-Host "  entry eligible: $($finalV13.entry_eligible)"
Write-Host "  targets +     : $($finalV13.positive_targets)"

if ($finalJob.stale -eq $true) {
    throw "Forward remains stale after successful runner."
}

if ($finalV13.status -ne "PASS") {
    throw "V13 live-shadow status is not PASS."
}

Write-Host ""
Write-Host "[7/7] IMMUTABILITY VERIFY"

foreach($rel in $critical) {
    $p = Join-Path $V13 $rel
    $after = (Get-FileHash -Algorithm SHA256 $p).Hash
    if ($after -ne $v13Before[$rel]) {
        throw "SEALED V13 MUTATION DETECTED: $rel"
    }
}

foreach($name in @($CANON,$RET)) {
    $p = Join-Path $ACTUAL_OUTPUTS $name
    $after = (Get-FileHash -Algorithm SHA256 $p).Hash
    if ($after -ne $v12Before[$name]) {
        throw "V12 SOURCE INPUT MUTATION DETECTED: $name"
    }
}

Write-Host "  PASS V13 sealed 6/6 unchanged"
Write-Host "  PASS V12 source 2/2 unchanged"

Write-Host ""
Write-Host "================================================================"
Write-Host "FORWARD SOURCE REPAIR + CATCH-UP: PASS"
Write-Host "================================================================"
Write-Host "COMPATIBILITY PATH : ACTIVE"
Write-Host "MODEL SESSION      : $($finalJob.current_model_session)"
Write-Host "MARKET SESSION     : $($finalJob.latest_completed_market_session)"
Write-Host "FORWARD STALE      : $($finalJob.stale)"
Write-Host "V13 SEALED CORE    : UNCHANGED"
Write-Host "V12 SOURCE INPUTS  : UNCHANGED"
Write-Host "AUTO WATCHDOG      : ACTIVE VIA V4.1"
Write-Host "================================================================"

Start-Process "http://127.0.0.1:8765/"
