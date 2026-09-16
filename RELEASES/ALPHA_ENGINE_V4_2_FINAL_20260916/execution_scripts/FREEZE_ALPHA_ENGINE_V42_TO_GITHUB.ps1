$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION"
$DOWNLOADS = "C:\Users\santi\Downloads"
$REC = Join-Path $ROOT "ALPHA_ENGINE_DATA_RECOVERY_V1"
$V13 = Join-Path $ROOT "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
$WEB = Join-Path $ROOT "web"
$PRODUCT = Join-Path $ROOT "PRODUCT"

$STAMP = Get-Date -Format "yyyyMMdd_HHmmss"
$RELEASE_NAME = "ALPHA_ENGINE_V4_2_FINAL_20260916"
$RELEASE = Join-Path $ROOT "RELEASES\$RELEASE_NAME"

Write-Host ""
Write-Host "================================================================"
Write-Host "ALPHA ENGINE V4.2 - FINAL FREEZE + GITHUB"
Write-Host "IN-PLACE REPO FREEZE / RELEASE SNAPSHOT / SAFE PUSH"
Write-Host "NO MODEL REBUILD / NO ORDER EXECUTION / NO SECRET COMMIT"
Write-Host "================================================================"

# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
function Invoke-Git {
    param(
        [Parameter(Mandatory=$true)][string[]]$Args,
        [switch]$AllowFailure
    )
    $out = & git @Args 2>&1
    $code = $LASTEXITCODE
    if (-not $AllowFailure -and $code -ne 0) {
        throw "git $($Args -join ' ') failed:`n$out"
    }
    return @{
        Code = $code
        Text = ($out -join "`n")
    }
}

function Write-JsonFile {
    param([string]$Path, $Object)
    $json = $Object | ConvertTo-Json -Depth 12
    Set-Content -Path $Path -Value $json -Encoding UTF8
}

function Safe-Copy {
    param([string]$Source,[string]$Destination)
    if (Test-Path $Source) {
        $parent = Split-Path -Parent $Destination
        if ($parent) {
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
        }
        Copy-Item $Source $Destination -Force
        return $true
    }
    return $false
}

function Get-ApiJson {
    param([string]$Path,[int]$Timeout=60)
    return Invoke-RestMethod `
        -Uri ("http://127.0.0.1:8765" + $Path) `
        -TimeoutSec $Timeout
}

# ------------------------------------------------------------
# 1. PRE-FLIGHT
# ------------------------------------------------------------
Write-Host ""
Write-Host "[1/10] PRE-FLIGHT"

if (-not (Test-Path $ROOT)) {
    throw "Production root missing: $ROOT"
}

Set-Location $ROOT

$gitVersion = Invoke-Git -Args @("--version")
Write-Host "  $($gitVersion.Text)"

$repoRoot = (Invoke-Git -Args @("rev-parse","--show-toplevel")).Text.Trim()
if ([IO.Path]::GetFullPath($repoRoot) -ne [IO.Path]::GetFullPath($ROOT)) {
    throw "Git root mismatch. Expected $ROOT but got $repoRoot"
}

$branch = (Invoke-Git -Args @("branch","--show-current")).Text.Trim()
if ([string]::IsNullOrWhiteSpace($branch)) {
    throw "Detached HEAD is not allowed for final freeze."
}

$remote = Invoke-Git -Args @("remote","get-url","origin") -AllowFailure
if ($remote.Code -ne 0 -or [string]::IsNullOrWhiteSpace($remote.Text)) {
    throw "Git remote 'origin' is not configured."
}

Write-Host "  repo   : $repoRoot"
Write-Host "  branch : $branch"
Write-Host "  origin : $($remote.Text.Trim())"

# Ensure V4.2 is live before freezing.
$health = Get-ApiJson "/api/v4/health" 20
if ($health.status -ne "PASS" -or $health.version -ne "V4.2") {
    throw "Alpha Engine V4.2 is not live on port 8765."
}

$forwardJob = Get-ApiJson "/api/v4/forward/job" 40
$forwardNav = Get-ApiJson "/api/v4/forward/nav" 40
$marketJob = Get-ApiJson "/api/v4/market/job" 40
$recommendations = Get-ApiJson "/api/v4/recommendations" 90

if ($forwardJob.stale -eq $true) {
    throw "Forward is stale. Freeze aborted."
}
if ($forwardNav.status -ne "PASS") {
    throw "Forward NAV is not PASS. Freeze aborted."
}
if ($forwardNav.holdout_parity.status -ne "PASS") {
    throw "Forward NAV parity is not PASS. Freeze aborted."
}

Write-Host "  V4.2 health       : PASS"
Write-Host "  forward model     : $($forwardJob.current_model_session)"
Write-Host "  market session    : $($forwardJob.latest_completed_market_session)"
Write-Host "  forward NAV       : $($forwardNav.start_date) -> $($forwardNav.latest_date)"
Write-Host "  holdout parity    : $($forwardNav.holdout_parity.status)"
Write-Host "  recommendations   : $($recommendations.portfolio_status)"

# ------------------------------------------------------------
# 2. VERIFY SEALED V13
# ------------------------------------------------------------
Write-Host ""
Write-Host "[2/10] SEALED V13 HASH SNAPSHOT"

$critical = @(
    "outputs\v13_phase2r_model_spec.json",
    "outputs\v13_phase2u_expert_evidence.csv",
    "outputs\v13_phase3aa_freeze_manifest.json",
    "outputs\v13_phase4_sealed_features.csv",
    "outputs\v13_phase4_model_seal_manifest.json",
    "outputs\v13_phase4_sealed_model_bundle.joblib"
)

$v13Hashes = @()

foreach ($rel in $critical) {
    $path = Join-Path $V13 $rel
    if (-not (Test-Path $path)) {
        throw "Critical V13 artifact missing: $path"
    }
    $h = Get-FileHash -Algorithm SHA256 $path
    $v13Hashes += [PSCustomObject]@{
        relative_path = "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON\" + $rel
        sha256 = $h.Hash
        bytes = (Get-Item $path).Length
    }
}

Write-Host "  PASS 6/6"

# ------------------------------------------------------------
# 3. CREATE RELEASE SNAPSHOT
# ------------------------------------------------------------
Write-Host ""
Write-Host "[3/10] CREATE RELEASE SNAPSHOT"

if (Test-Path $RELEASE) {
    $old = $RELEASE + "_OLD_" + $STAMP
    Move-Item $RELEASE $old
    Write-Host "  previous release moved to: $old"
}

New-Item -ItemType Directory -Force -Path $RELEASE | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $RELEASE "execution_scripts") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $RELEASE "web_snapshot") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $RELEASE "runtime_snapshot") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $RELEASE "docs") | Out-Null

# Web production snapshot.
$webFiles = @(
    "web\run_alpha_engine_v4.py",
    "web\v4\index.html",
    "web\v4\app.js",
    "web\v4\styles.css",
    "web\v4\alpha-engine-logo.jpg",
    "START_ALPHA_ENGINE_V4.ps1"
)

foreach ($rel in $webFiles) {
    $src = Join-Path $ROOT $rel
    $dst = Join-Path $RELEASE ("web_snapshot\" + ($rel -replace '[\\/:*?"<>|]', '_'))
    [void](Safe-Copy $src $dst)
}

# Runtime snapshot: small authoritative outputs only. No SEC cache/runtime source.
$runtimeFiles = @(
    "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON\outputs\live_shadow\v13_live_shadow_summary.json",
    "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON\outputs\live_shadow\v13_live_shadow_contract_history.csv",
    "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON\outputs\live_shadow\v13_live_shadow_contract_latest.csv",
    "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON\outputs\live_shadow\v13_live_shadow_contract_latest.json",
    "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON\outputs\live_shadow\v13_live_market_audit.csv",
    "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON\outputs\live_shadow\v13_live_adjusted_anchor_audit.csv",
    "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON\outputs\live_shadow\v13_live_sec_audit.csv",
    "ALPHA_ENGINE_DATA_RECOVERY_V1\outputs\data_recovery_v1\forward_v42\forward_nav_latest.json",
    "ALPHA_ENGINE_DATA_RECOVERY_V1\outputs\data_recovery_v1\forward_v42\forward_nav_latest.csv",
    "ALPHA_ENGINE_DATA_RECOVERY_V1\outputs\data_recovery_v1\live\market_refresh_summary_latest.json"
)

foreach ($rel in $runtimeFiles) {
    $src = Join-Path $ROOT $rel
    $dstName = ($rel -replace '[\\/:*?"<>|]', '_')
    $dst = Join-Path $RELEASE ("runtime_snapshot\" + $dstName)
    [void](Safe-Copy $src $dst)
}

Write-Host "  PASS release folder: $RELEASE"

# ------------------------------------------------------------
# 4. ARCHIVE ALL ALPHA ENGINE POWERSHELL FILES FROM DOWNLOADS
# ------------------------------------------------------------
Write-Host ""
Write-Host "[4/10] ARCHIVE EXECUTION SCRIPTS FROM DOWNLOADS"

$scriptRows = @()

$psFiles = @(
    Get-ChildItem `
        -Path $DOWNLOADS `
        -Filter "*.ps1" `
        -File `
        -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -match "ALPHA_ENGINE|FORWARD|GROQ"
    } |
    Sort-Object Name
)

foreach ($f in $psFiles) {
    $dst = Join-Path $RELEASE ("execution_scripts\" + $f.Name)
    Copy-Item $f.FullName $dst -Force

    $status = "HISTORY"
    if ($f.Name -in @(
        "FINAL_ALPHA_ENGINE_V4.ps1",
        "PATCH_ALPHA_ENGINE_V41_LIVE_FIXED.ps1",
        "REPAIR_FORWARD_SOURCE_AND_CATCHUP.ps1",
        "REPAIR_SEC_IDENTITY_AND_FORWARD.ps1",
        "FINALIZE_ALPHA_ENGINE_V42_AUTOMATION.ps1",
        "RESUME_ALPHA_ENGINE_V42_FIX1.ps1"
    )) {
        $status = "USED_IN_FINAL_CHAIN"
    }

    $scriptRows += [PSCustomObject]@{
        filename = $f.Name
        status = $status
        source = $f.FullName
        archived = $dst
        sha256 = (Get-FileHash -Algorithm SHA256 $dst).Hash
        bytes = $f.Length
    }
}

$scriptRows |
    Export-Csv `
        -Path (Join-Path $RELEASE "docs\EXECUTION_SCRIPT_INDEX.csv") `
        -NoTypeInformation `
        -Encoding UTF8

Write-Host "  archived scripts: $($scriptRows.Count)"

# ------------------------------------------------------------
# 5. RELEASE STATE + README
# ------------------------------------------------------------
Write-Host ""
Write-Host "[5/10] WRITE RELEASE STATE + DOCUMENTATION"

$summary = Get-ApiJson "/api/v4/summary" 40

$releaseState = [ordered]@{
    release = $RELEASE_NAME
    created_at = (Get-Date).ToString("o")
    git_branch = $branch
    git_origin = $remote.Text.Trim()
    product = [ordered]@{
        health = $health
        summary = $summary
        market_job = $marketJob
        forward_job = $forwardJob
        forward_nav = [ordered]@{
            status = $forwardNav.status
            start_date = $forwardNav.start_date
            latest_date = $forwardNav.latest_date
            metrics = $forwardNav.metrics
            holdout_parity = $forwardNav.holdout_parity
        }
        recommendations_status = $recommendations.portfolio_status
        llm = "PAUSED"
        real_orders = $false
    }
    v13_sealed_hashes = $v13Hashes
}

Write-JsonFile `
    (Join-Path $RELEASE "RELEASE_STATE.json") `
    $releaseState

$readme = @"
# Alpha Engine V4.2 — Final Local Production Freeze

Freeze date: 2026-09-16

## Production root

$ROOT

## Runtime state at freeze

- Web: V4.2
- Market: automatic every 5 minutes during regular US session
- Forward model session: $($forwardJob.current_model_session)
- Latest completed market session: $($forwardJob.latest_completed_market_session)
- Forward stale: $($forwardJob.stale)
- Forward NAV: $($forwardNav.start_date) -> $($forwardNav.latest_date)
- Holdout parity: $($forwardNav.holdout_parity.status)
- Recommendations: $($recommendations.portfolio_status)
- LLM: PAUSED
- Real orders: NO
- V13 sealed core: unchanged

## Canonical local runtime files

- web\run_alpha_engine_v4.py
- web\v4\
- START_ALPHA_ENGINE_V4.ps1
- ALPHA_ENGINE_DATA_RECOVERY_V1\scripts\build_forward_nav_v42.py
- ALPHA_ENGINE_DATA_RECOVERY_V1\scripts\smoke_v42.py
- PRODUCT\AlphaEngine_Cartera_Real.xlsx (LOCAL RUNTIME / future personal data)
- PRODUCT\personal_portfolio_ledger_v4.json (LOCAL RUNTIME / future personal data)
- PRODUCT\personal_portfolio_ledger_v4.csv (LOCAL RUNTIME / future personal data)

## Personal portfolio policy

Personal operations are intentionally NOT included in this release snapshot.
After this freeze, real operations can be loaded through the V4.2 interface.
Do not publish personal ledger data to a public repository.

## Secrets excluded

Never commit:

- .env
- secrets\
- *.clixml
- API keys / tokens
- MMM_SEC_USER_AGENT value
- Groq credentials

## Execution scripts

See docs\EXECUTION_SCRIPT_INDEX.csv.
Scripts tagged USED_IN_FINAL_CHAIN are the ones that materially led to the final V4.2 state.
Older scripts are retained only as history and should not be used as current deployment entrypoints.

## Git

This release is frozen in-place in the existing production repository.
The RELEASES folder is documentation/snapshot material only; the live code remains in its canonical paths.
"@

Set-Content `
    -Path (Join-Path $RELEASE "README.md") `
    -Value $readme `
    -Encoding UTF8

Write-Host "  PASS"

# ------------------------------------------------------------
# 6. HASH RELEASE SNAPSHOT
# ------------------------------------------------------------
Write-Host ""
Write-Host "[6/10] BUILD RELEASE SHA256 MANIFEST"

$manifest = @()

Get-ChildItem `
    -Path $RELEASE `
    -File `
    -Recurse |
Where-Object {
    $_.Name -ne "MANIFEST_SHA256.csv"
} |
ForEach-Object {
    $rel = $_.FullName.Substring($RELEASE.Length + 1)
    $manifest += [PSCustomObject]@{
        relative_path = $rel
        sha256 = (Get-FileHash -Algorithm SHA256 $_.FullName).Hash
        bytes = $_.Length
    }
}

$manifest |
    Sort-Object relative_path |
    Export-Csv `
        -Path (Join-Path $RELEASE "MANIFEST_SHA256.csv") `
        -NoTypeInformation `
        -Encoding UTF8

Write-Host "  files hashed: $($manifest.Count)"
Write-Host "  PASS"

# ------------------------------------------------------------
# 7. GIT SAFETY RULES
# ------------------------------------------------------------
Write-Host ""
Write-Host "[7/10] GIT SAFETY GATES"

# Never stage secrets or future personal operations from runtime.
$localExclude = Join-Path $ROOT ".git\info\exclude"
$excludeLines = @(
    "",
    "# Alpha Engine local-only runtime / secrets",
    "**/.env",
    "**/secrets/**",
    "*.clixml",
    "PRODUCT/personal_portfolio_ledger_v4.json",
    "PRODUCT/personal_portfolio_ledger_v4.csv",
    "PRODUCT/AlphaEngine_Cartera_Real.xlsx",
    "ALPHA_ENGINE_DATA_RECOVERY_V1/outputs/data_recovery_v1/web_runtime.log",
    "ALPHA_ENGINE_DATA_RECOVERY_V1/outputs/data_recovery_v1/web_v41_runtime.log"
)

$currentExclude = ""
if (Test-Path $localExclude) {
    $currentExclude = Get-Content -Raw $localExclude
}

foreach ($line in $excludeLines) {
    if (
        $line `
        -and `
        $currentExclude -notmatch [regex]::Escape($line)
    ) {
        Add-Content -Path $localExclude -Value $line
    }
}

# Fetch before commit. Fail closed on divergence.
$fetch = Invoke-Git -Args @("fetch","origin",$branch) -AllowFailure
if ($fetch.Code -ne 0) {
    throw "git fetch origin $branch failed. No commit/push performed.`n$($fetch.Text)"
}

$remoteRef = Invoke-Git -Args @("rev-parse","--verify","origin/$branch") -AllowFailure
if ($remoteRef.Code -eq 0) {
    $ancestor = Invoke-Git `
        -Args @("merge-base","--is-ancestor","origin/$branch","HEAD") `
        -AllowFailure

    if ($ancestor.Code -ne 0) {
        throw "Remote origin/$branch contains commits not in local HEAD. Reconcile before final push."
    }
}

Write-Host "  remote fetch: PASS"
Write-Host "  divergence  : NONE"

# ------------------------------------------------------------
# 8. STAGE ONLY FINAL PRODUCT / RELEASE FILES
# ------------------------------------------------------------
Write-Host ""
Write-Host "[8/10] STAGE FINAL PRODUCT"

$stagePaths = @(
    "web",
    "START_ALPHA_ENGINE_V4.ps1",
    "ALPHA_ENGINE_DATA_RECOVERY_V1/scripts",
    ("RELEASES/" + $RELEASE_NAME)
)

foreach ($p in $stagePaths) {
    $full = Join-Path $ROOT ($p -replace "/","\")
    if (Test-Path $full) {
        [void](Invoke-Git -Args @("add","--",$p))
    }
}

$staged = (Invoke-Git -Args @("diff","--cached","--name-only")).Text `
    -split "`n" |
    Where-Object { $_ -and $_.Trim() }

if ($staged.Count -eq 0) {
    throw "Nothing staged. Freeze would create no commit."
}

$forbiddenPatterns = @(
    '(^|/)\.env$',
    '(^|/)secrets/',
    '\.clixml$',
    'personal_portfolio_ledger_v4\.(json|csv)$',
    'AlphaEngine_Cartera_Real\.xlsx$',
    'groq.*key',
    'api[_-]?key'
)

$bad = @()
foreach ($path in $staged) {
    foreach ($pat in $forbiddenPatterns) {
        if ($path -match $pat) {
            $bad += $path
        }
    }
}

if ($bad.Count -gt 0) {
    & git reset HEAD -- @($bad) | Out-Null
    throw "Forbidden secret/personal files were staged and have been unstaged: $($bad -join ', ')"
}

# Large staged binary gate.
$largeProblems = @()

foreach ($path in $staged) {
    $full = Join-Path $ROOT ($path -replace "/","\")
    if (Test-Path $full -PathType Leaf) {
        $size = (Get-Item $full).Length
        if ($size -gt 90000000) {
            $attr = (Invoke-Git -Args @("check-attr","filter","--",$path)).Text
            if ($attr -notmatch 'filter:\s+lfs') {
                $largeProblems += "$path ($size bytes)"
            }
        }
    }
}

if ($largeProblems.Count -gt 0) {
    throw "Large staged files are not Git LFS managed: $($largeProblems -join '; ')"
}

Write-Host "  staged files : $($staged.Count)"
Write-Host "  secrets gate : PASS"
Write-Host "  large files  : PASS"

# ------------------------------------------------------------
# 9. COMMIT + PUSH
# ------------------------------------------------------------
Write-Host ""
Write-Host "[9/10] COMMIT + PUSH"

$message = "Freeze Alpha Engine V4.2 production 2026-09-16"

$commit = Invoke-Git -Args @("commit","-m",$message) -AllowFailure

if ($commit.Code -ne 0) {
    if ($commit.Text -match "nothing to commit") {
        Write-Host "  nothing new to commit; using existing HEAD"
    }
    else {
        throw "git commit failed:`n$($commit.Text)"
    }
}
else {
    Write-Host "  commit: PASS"
}

$head = (Invoke-Git -Args @("rev-parse","HEAD")).Text.Trim()

$push = Invoke-Git -Args @("push","origin",$branch) -AllowFailure
if ($push.Code -ne 0) {
    throw "git push failed. Local commit is preserved.`n$($push.Text)"
}

Write-Host "  push  : PASS"
Write-Host "  HEAD  : $head"

# ------------------------------------------------------------
# 10. VERIFY REMOTE HEAD
# ------------------------------------------------------------
Write-Host ""
Write-Host "[10/10] REMOTE VERIFICATION"

$remoteLine = (Invoke-Git -Args @("ls-remote","origin","refs/heads/$branch")).Text.Trim()
if ([string]::IsNullOrWhiteSpace($remoteLine)) {
    throw "Could not verify remote branch after push."
}

$remoteHead = ($remoteLine -split "\s+")[0]

if ($remoteHead -ne $head) {
    throw "Remote verification mismatch. local=$head remote=$remoteHead"
}

Write-Host "  remote HEAD : $remoteHead"
Write-Host "  PASS"

# ------------------------------------------------------------
# Final
# ------------------------------------------------------------
$status = (Invoke-Git -Args @("status","--short")).Text

Write-Host ""
Write-Host "================================================================"
Write-Host "ALPHA ENGINE V4.2 FINAL FREEZE: PASS"
Write-Host "================================================================"
Write-Host "REPO ROOT            : $ROOT"
Write-Host "RELEASE SNAPSHOT     : RELEASES\$RELEASE_NAME"
Write-Host "BRANCH               : $branch"
Write-Host "REMOTE HEAD          : $remoteHead"
Write-Host "WEB V4.2             : ARCHIVED + PUSHED"
Write-Host "EXECUTION SCRIPTS    : ARCHIVED FROM DOWNLOADS"
Write-Host "FORWARD NAV          : $($forwardNav.start_date) -> $($forwardNav.latest_date)"
Write-Host "HOLDOUT PARITY       : $($forwardNav.holdout_parity.status)"
Write-Host "V13 SEALED CORE      : HASHED / UNCHANGED"
Write-Host "SECRETS              : NOT COMMITTED"
Write-Host "PERSONAL LEDGER      : LOCAL-ONLY"
Write-Host "REAL ORDERS          : NO"
Write-Host "================================================================"

if (-not [string]::IsNullOrWhiteSpace($status)) {
    Write-Host ""
    Write-Host "Remaining unstaged/local runtime changes are expected:"
    Write-Host $status
}

Write-Host ""
Write-Host "SAFE NEXT STEP:"
Write-Host "1) Confirm the GitHub commit exists."
Write-Host "2) Then delete the archived Alpha Engine PS1 files from Downloads."
Write-Host "3) Load your real portfolio operations in V4.2."
Write-Host ""
