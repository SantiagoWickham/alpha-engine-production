$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$ExpectedFreezeId = '3c3ebdd84730abee33d74575387b019e453588021ff1bb3249d11824ecf234b8'
$RemoteUrl       = 'https://github.com/SantiagoWickham/alpha-engine.git'
$TagName         = 'v13-preholdout-3c3ebdd8'
$CommitMessage   = 'freeze: Alpha Engine V13 pre-holdout 3c3ebdd8'

function Fail([string]$Message) {
    Write-Host "`nERROR: $Message" -ForegroundColor Red
    exit 1
}

function Require-Path([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { Fail "Missing required path: $Path" }
}

Write-Host '============================================================' -ForegroundColor Cyan
Write-Host 'ALPHA ENGINE V13 - GITHUB PRE-HOLDOUT BOOTSTRAP' -ForegroundColor Cyan
Write-Host '============================================================' -ForegroundColor Cyan
Write-Host "Workspace: $(Get-Location)"
Write-Host "Remote:    $RemoteUrl"
Write-Host "Tag:       $TagName"

# Must be run from the V13 workspace root.
Require-Path 'src\alpha_engine_v13'
Require-Path 'config'
Require-Path 'scripts'
Require-Path 'tests'
Require-Path 'outputs\v13_phase3aa_summary.json'
Require-Path 'outputs\v13_phase3aa_gate.csv'
Require-Path 'outputs\v13_phase3aa_freeze_manifest.json'

# Validate Phase 3AA summary.
$summary = Get-Content -Raw -LiteralPath 'outputs\v13_phase3aa_summary.json' | ConvertFrom-Json
if ([string]$summary.status -ne 'PASS') { Fail "Phase3AA status is not PASS: $($summary.status)" }
if ([bool]$summary.holdout_used) { Fail 'Phase3AA says holdout_used=true. Refusing to create pre-holdout tag.' }
if ([bool]$summary.policy_changed) { Fail 'Phase3AA says policy_changed=true.' }
if ([bool]$summary.predictor_retrained) { Fail 'Phase3AA says predictor_retrained=true.' }
if ([string]$summary.freeze_id -ne $ExpectedFreezeId) {
    Fail "Unexpected freeze_id in summary: $($summary.freeze_id)"
}

# Validate freeze manifest and every listed SHA-256 against current workspace.
$manifest = Get-Content -Raw -LiteralPath 'outputs\v13_phase3aa_freeze_manifest.json' | ConvertFrom-Json
if ([string]$manifest.freeze_id -ne $ExpectedFreezeId) {
    Fail "Unexpected freeze_id in manifest: $($manifest.freeze_id)"
}
if ([string]$manifest.holdout_start -ne '2025-01-01') {
    Fail "Unexpected holdout_start: $($manifest.holdout_start)"
}

Write-Host "`nVerifying frozen manifest hashes..." -ForegroundColor Yellow
foreach ($entry in $manifest.files) {
    $rel = ([string]$entry.path).Replace('/', [IO.Path]::DirectorySeparatorChar)
    Require-Path $rel
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $rel).Hash.ToLowerInvariant()
    $expected = ([string]$entry.sha256).ToLowerInvariant()
    if ($actual -ne $expected) {
        Fail "SHA-256 mismatch: $rel`nExpected: $expected`nActual:   $actual"
    }
    Write-Host "  OK $rel" -ForegroundColor Green
}
Write-Host 'Freeze manifest verification: PASS' -ForegroundColor Green

# Curated freeze artifacts for Git history.
New-Item -ItemType Directory -Force -Path 'artifacts\freeze' | Out-Null
Copy-Item -Force 'outputs\v13_phase3aa_summary.json'         'artifacts\freeze\v13_phase3aa_summary.json'
Copy-Item -Force 'outputs\v13_phase3aa_gate.csv'             'artifacts\freeze\v13_phase3aa_gate.csv'
Copy-Item -Force 'outputs\v13_phase3aa_freeze_manifest.json' 'artifacts\freeze\v13_phase3aa_freeze_manifest.json'

# Initialize repository if needed.
if (-not (Test-Path '.git')) {
    git init -b main
    if ($LASTEXITCODE -ne 0) { Fail 'git init failed.' }
} else {
    Write-Host '`nExisting .git directory detected; preserving it.' -ForegroundColor Yellow
    git branch -M main
}

# Configure remote safely.
$origin = git remote get-url origin 2>$null
if ($LASTEXITCODE -eq 0 -and $origin) {
    if ($origin.Trim() -ne $RemoteUrl) {
        Write-Host "Updating origin from $origin to $RemoteUrl" -ForegroundColor Yellow
        git remote set-url origin $RemoteUrl
    }
} else {
    git remote add origin $RemoteUrl
}

# Remote must be empty. Never overwrite an existing repository history.
Write-Host '`nChecking that GitHub remote has no refs...' -ForegroundColor Yellow
$remoteRefs = git ls-remote --heads --tags origin 2>$null
if ($LASTEXITCODE -ne 0) {
    Fail 'Could not access GitHub remote. Check internet/authentication/repository URL.'
}
if ($remoteRefs -and ($remoteRefs | Where-Object { $_.Trim() -ne '' })) {
    Write-Host $remoteRefs
    Fail 'Remote repository is not empty. Refusing to overwrite existing GitHub history.'
}
Write-Host 'Remote repository is empty: PASS' -ForegroundColor Green

# Stage only code/contracts/docs. Never git add . here.
git reset | Out-Null
$stagePaths = @('.gitignore','.gitattributes','README.md','docs','artifacts\freeze','src','config','scripts','tests')
foreach ($p in $stagePaths) {
    if (Test-Path -LiteralPath $p) { git add -- $p }
}
Get-ChildItem -File -Filter 'RUN_V13*.ps1' -ErrorAction SilentlyContinue | ForEach-Object { git add -- $_.FullName }
foreach ($extra in @('pyproject.toml','requirements.txt','requirements-dev.txt','pytest.ini','setup.cfg','tox.ini')) {
    if (Test-Path -LiteralPath $extra) { git add -- $extra }
}

$staged = @(git diff --cached --name-only)
if ($staged.Count -eq 0) { Fail 'Nothing staged for first commit.' }

# Security/data guard.
$forbiddenPatterns = @(
    '^data/', '^outputs/', '^cache/', '^caches/', '^logs/',
    '(^|/)\.env($|\.)', '(^|/)secrets/', '\.parquet$', '\.pkl$', '\.pickle$',
    '\.joblib$', '\.sqlite3?$', '\.db$', '\.pem$', '\.key$', '\.p12$', '\.pfx$'
)
$violations = New-Object System.Collections.Generic.List[string]
foreach ($f in $staged) {
    $norm = $f.Replace('\','/')
    foreach ($pat in $forbiddenPatterns) {
        if ($norm -match $pat) { $violations.Add($norm); break }
    }
}
if ($violations.Count -gt 0) {
    Write-Host ($violations | Sort-Object -Unique)
    Fail 'Forbidden data/secret files are staged. Nothing was committed.'
}

Write-Host "`nFiles staged for immutable pre-holdout checkpoint:" -ForegroundColor Cyan
$staged | ForEach-Object { Write-Host "  $_" }

# Commit. Git may ask user to configure name/email if not already configured.
git commit -m $CommitMessage
if ($LASTEXITCODE -ne 0) { Fail 'git commit failed. If Git asks for user.name/user.email, configure them and rerun this script.' }

$commit = (git rev-parse HEAD).Trim()
Write-Host "`nCommit created: $commit" -ForegroundColor Green

# Push main first, then create immutable annotated tag on that exact commit.
git push -u origin main
if ($LASTEXITCODE -ne 0) { Fail 'git push main failed. Authenticate with GitHub/Git Credential Manager and rerun.' }

git tag -a $TagName $commit -m "Alpha Engine V13 frozen before 2025+ holdout | freeze_id=$ExpectedFreezeId"
if ($LASTEXITCODE -ne 0) { Fail 'git tag failed.' }

git push origin $TagName
if ($LASTEXITCODE -ne 0) { Fail 'git push tag failed.' }

Write-Host '`n============================================================' -ForegroundColor Green
Write-Host 'PRE-HOLDOUT GITHUB CHECKPOINT CREATED SUCCESSFULLY' -ForegroundColor Green
Write-Host "Commit:    $commit"
Write-Host "Tag:       $TagName"
Write-Host "Freeze ID: $ExpectedFreezeId"
Write-Host '2025+ HOLDOUT HAS NOT BEEN OPENED BY THIS SCRIPT.'
Write-Host '============================================================' -ForegroundColor Green
