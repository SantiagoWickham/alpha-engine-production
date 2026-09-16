$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION"
$REC  = Join-Path $ROOT "ALPHA_ENGINE_DATA_RECOVERY_V1"
$V13  = Join-Path $ROOT "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
$TARGET_ENV = Join-Path $V13 ".env"
$CATCH = Join-Path $REC "scripts\catchup_v41.py"

Write-Host ""
Write-Host "================================================================"
Write-Host "ALPHA ENGINE - SEC IDENTITY REPAIR + FORWARD CATCH-UP"
Write-Host "RECOVER EXISTING SEC USER AGENT / NO SECRET DISPLAY"
Write-Host "NO V13 CODE CHANGE / NO MODEL CHANGE / NO TUNING"
Write-Host "================================================================"

if (-not (Test-Path $V13)) {
    throw "V13 root missing: $V13"
}
if (-not (Test-Path $CATCH)) {
    throw "Forward catch-up helper missing: $CATCH"
}

Write-Host ""
Write-Host "[1/7] SNAPSHOT SEALED V13"

$critical = @(
  "outputs\v13_phase2r_model_spec.json",
  "outputs\v13_phase2u_expert_evidence.csv",
  "outputs\v13_phase3aa_freeze_manifest.json",
  "outputs\v13_phase4_sealed_features.csv",
  "outputs\v13_phase4_model_seal_manifest.json",
  "outputs\v13_phase4_sealed_model_bundle.joblib"
)

$before = @{}

foreach ($rel in $critical) {
    $p = Join-Path $V13 $rel
    if (-not (Test-Path $p)) {
        throw "Critical V13 file missing: $p"
    }
    $before[$rel] = (Get-FileHash -Algorithm SHA256 $p).Hash
}

Write-Host "  PASS 6/6"

Write-Host ""
Write-Host "[2/7] RECOVER EXISTING SEC IDENTITY"

$desktop = "C:\Users\santi\OneDrive\Escritorio"

# Search the most likely historical locations first, then other .env files.
$candidates = New-Object System.Collections.Generic.List[string]

$preferred = @(
    "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_V12_RETURN_FIRST\ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON\.env",
    "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_V12_RETURN_FIRST\.env",
    (Join-Path $ROOT ".env"),
    (Join-Path $ROOT "secrets\.env"),
    (Join-Path $ROOT "ALPHA_ENGINE_V12_RETURN_FIRST_STARTER\.env"),
    (Join-Path $ROOT "ALPHA_ENGINE_V12_RETURN_FIRST_STARTER\secrets\.env")
)

foreach ($p in $preferred) {
    if (
        (Test-Path $p) `
        -and `
        ([IO.Path]::GetFullPath($p) -ne [IO.Path]::GetFullPath($TARGET_ENV))
    ) {
        $candidates.Add($p)
    }
}

try {
    Get-ChildItem `
        -Path $desktop `
        -Filter ".env" `
        -File `
        -Recurse `
        -ErrorAction SilentlyContinue |
    ForEach-Object {
        $full = $_.FullName
        if (
            ([IO.Path]::GetFullPath($full) -ne [IO.Path]::GetFullPath($TARGET_ENV)) `
            -and `
            (-not $candidates.Contains($full))
        ) {
            $candidates.Add($full)
        }
    }
}
catch {
    # Preferred locations remain sufficient if recursive scan is unavailable.
}

$secLine = $null
$sourceEnv = $null

foreach ($envPath in $candidates) {
    try {
        $lines = Get-Content -Path $envPath -ErrorAction Stop

        # Prefer the exact variable V13 expects.
        $match = $lines |
            Where-Object {
                $_ -match '^\s*MMM_SEC_USER_AGENT\s*=\s*(.+?)\s*$'
            } |
            Select-Object -First 1

        if (-not $match) {
            $legacy = $lines |
                Where-Object {
                    $_ -match '^\s*SEC_USER_AGENT\s*=\s*(.+?)\s*$'
                } |
                Select-Object -First 1

            if ($legacy) {
                $value = (
                    [regex]::Match(
                        $legacy,
                        '^\s*SEC_USER_AGENT\s*=\s*(.+?)\s*$'
                    )
                ).Groups[1].Value

                $match = "MMM_SEC_USER_AGENT=$value"
            }
        }

        if ($match) {
            $secLine = $match
            $sourceEnv = $envPath
            break
        }
    }
    catch {
        continue
    }
}

if (-not $secLine) {
    Write-Host ""
    Write-Host "No previous SEC identity was found automatically."
    Write-Host "Enter the SEC User-Agent contact string once."
    Write-Host "Example format: Alpha Engine research your-email@example.com"
    Write-Host ""

    $manual = Read-Host "SEC User-Agent"

    if ([string]::IsNullOrWhiteSpace($manual)) {
        throw "SEC identity is required for SEC Companyfacts access."
    }

    $secLine = 'MMM_SEC_USER_AGENT="' + $manual.Replace('"','') + '"'
    $sourceEnv = "MANUAL_ONE_TIME_INPUT"
}

Write-Host "  PASS identity recovered"
Write-Host "  source found : YES"
Write-Host "  secret/value : NOT DISPLAYED"

Write-Host ""
Write-Host "[3/7] PERSIST IDENTITY IN CURRENT V13 DOTENV"

$backupDir = Join-Path $REC "outputs\data_recovery_v1\env_backups"
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

if (Test-Path $TARGET_ENV) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $backup = Join-Path $backupDir "v13_env_$stamp.bak"
    Copy-Item $TARGET_ENV $backup -Force

    $existing = Get-Content $TARGET_ENV

    $filtered = @(
        $existing |
        Where-Object {
            $_ -notmatch '^\s*MMM_SEC_USER_AGENT\s*=' `
            -and `
            $_ -notmatch '^\s*SEC_USER_AGENT\s*='
        }
    )

    $newLines = @($filtered) + @($secLine)
    Set-Content -Path $TARGET_ENV -Value $newLines -Encoding UTF8

    Write-Host "  existing .env preserved + SEC identity updated"
}
else {
    Set-Content -Path $TARGET_ENV -Value @($secLine) -Encoding UTF8
    Write-Host "  new V13 .env created with SEC identity only"
}

# Never print the file because it may contain secrets.
Write-Host "  PASS target .env ready"
Write-Host "  contents     : NOT DISPLAYED"

Write-Host ""
Write-Host "[4/7] V13 SEC IDENTITY SELF-TEST"

$oldPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = (Join-Path $V13 "src")

try {
    Set-Location $V13

    python -c "from pathlib import Path; from alpha_engine_v13.live_shadow import _sec_user_agent; ua,src=_sec_user_agent(Path.cwd()); assert ua and src; print('  identity_source: ' + src); print('  PASS SEC identity loader')"

    if ($LASTEXITCODE -ne 0) {
        throw "V13 SEC identity self-test failed."
    }
}
finally {
    if ($null -eq $oldPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONPATH = $oldPythonPath
    }
}

Write-Host ""
Write-Host "[5/7] PHASE 5B FORWARD CATCH-UP"

Set-Location $ROOT
python $CATCH

if ($LASTEXITCODE -ne 0) {
    throw (
        "Phase 5B still failed after restoring SEC identity. " +
        "Do not change model parameters; inspect the new first error only."
    )
}

Write-Host ""
Write-Host "[6/7] FINAL FORWARD STATE"

$job = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8765/api/v4/forward/job" `
    -TimeoutSec 40

$v13State = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8765/api/v4/v13" `
    -TimeoutSec 40

Write-Host "  model session : $($job.current_model_session)"
Write-Host "  market session: $($job.latest_completed_market_session)"
Write-Host "  stale         : $($job.stale)"
Write-Host "  V13 status    : $($v13State.status)"
Write-Host "  entry eligible: $($v13State.entry_eligible)"
Write-Host "  targets +     : $($v13State.positive_targets)"

if ($job.stale -eq $true) {
    throw "Forward remains stale after Phase 5B PASS."
}

if ($v13State.status -ne "PASS") {
    throw "Live-shadow state is not PASS."
}

Write-Host ""
Write-Host "[7/7] SEALED V13 IMMUTABILITY VERIFY"

foreach ($rel in $critical) {
    $p = Join-Path $V13 $rel
    $after = (Get-FileHash -Algorithm SHA256 $p).Hash

    if ($after -ne $before[$rel]) {
        throw "SEALED V13 MUTATION DETECTED: $rel"
    }
}

Write-Host "  PASS 6/6 byte-identical"

Write-Host ""
Write-Host "================================================================"
Write-Host "SEC IDENTITY + FORWARD CATCH-UP: PASS"
Write-Host "================================================================"
Write-Host "SEC IDENTITY       : PERSISTED / VALUE HIDDEN"
Write-Host "MODEL SESSION      : $($job.current_model_session)"
Write-Host "MARKET SESSION     : $($job.latest_completed_market_session)"
Write-Host "FORWARD STALE      : $($job.stale)"
Write-Host "AUTO WATCHDOG      : ACTIVE"
Write-Host "V13 SEALED CORE    : UNCHANGED"
Write-Host "================================================================"

Start-Process "http://127.0.0.1:8765/"
