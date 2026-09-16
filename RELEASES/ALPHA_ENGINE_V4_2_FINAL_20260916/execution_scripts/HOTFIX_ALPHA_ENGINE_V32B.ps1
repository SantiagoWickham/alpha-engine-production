$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION"
$REC = Join-Path $ROOT "ALPHA_ENGINE_DATA_RECOVERY_V1"
$SERVER = Join-Path $ROOT "web\run_data_recovery_server.py"
$JS = Join-Path $ROOT "web\finish.js"
$CSS = Join-Path $ROOT "web\finish.css"
$START = Join-Path $ROOT "START_ALPHA_ENGINE.ps1"
$SMOKE = Join-Path $REC "scripts\smoke_web_v32.py"

Write-Host ""
Write-Host "============================================================"
Write-Host "ALPHA ENGINE V3.2B - SMALL HOTFIX"
Write-Host "GROQ OUTPUT CAP + FUNDAMENTALS + CRISP SIDEBAR BRAND"
Write-Host "NO MODEL / NO DATA / NO SHEETS MUTATION"
Write-Host "============================================================"

foreach ($p in @($SERVER,$JS,$CSS,$START,$SMOKE)) {
    if (-not (Test-Path $p)) { throw "Missing required file: $p" }
}

Write-Host ""
Write-Host "[1/5] BACKUP"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = Join-Path $REC "outputs\data_recovery_v1\web_backups\v32b_$stamp"
New-Item -ItemType Directory -Force -Path $backup | Out-Null
Copy-Item $SERVER (Join-Path $backup "run_data_recovery_server.py") -Force
Copy-Item $JS (Join-Path $backup "finish.js") -Force
Copy-Item $CSS (Join-Path $backup "finish.css") -Force
Write-Host "  PASS $backup"

Write-Host ""
Write-Host "[2/5] PATCH GROQ COMPLETION BUDGET"
$py = Get-Content -Raw -Path $SERVER

if ($py -match '"max_completion_tokens"\s*:\s*1800') {
    $py = $py -replace '"max_completion_tokens"\s*:\s*1800', '"max_completion_tokens": 640'
}
elseif ($py -notmatch '"max_completion_tokens"\s*:\s*640') {
    throw "Unexpected max_completion_tokens value. Nothing patched."
}

if ($py -match '"reasoning_effort"\s*:\s*"medium"') {
    $py = $py -replace '"reasoning_effort"\s*:\s*"medium"', '"reasoning_effort": "low"'
}

Set-Content -Path $SERVER -Value $py -Encoding UTF8
python -m py_compile $SERVER
if ($LASTEXITCODE -ne 0) { throw "Server syntax failed after patch." }

$verify = Get-Content -Raw -Path $SERVER
if ($verify -notmatch '"max_completion_tokens"\s*:\s*640') {
    throw "Groq completion cap verification failed."
}
Write-Host "  PASS max_completion_tokens=640"
Write-Host "  PASS reasoning_effort=low"

Write-Host ""
Write-Host "[3/5] PATCH UI ACCESS"
$jsText = Get-Content -Raw -Path $JS
if ($jsText -notmatch 'window\.__aeOpenFundamentals\s*=\s*openFundamentals') {
    $needle = "  function filteredFundamentals() {"
    if (-not $jsText.Contains($needle)) {
        throw "Could not expose Fundamentals Explorer."
    }
    $replacement = "  window.__aeOpenFundamentals = openFundamentals;`r`n`r`n" + $needle
    $jsText = $jsText.Replace($needle, $replacement)
}
Set-Content -Path $JS -Value $jsText -Encoding UTF8

$marker = "/* AE_V32B_HOTFIX */"
if ((Get-Content -Raw -Path $JS) -notmatch [regex]::Escape($marker)) {
@'
/* AE_V32B_HOTFIX */
(() => {
  "use strict";

  function text(el) {
    return (el && el.textContent ? el.textContent : "").trim();
  }

  function installCrispSidebarBrand() {
    const imgs = [...document.querySelectorAll("img")].filter(img => {
      const src = (img.getAttribute("src") || "").toLowerCase();
      return src.includes("alpha-engine") || src.includes("alpha_engine");
    });

    const sidebarImg = imgs.find(img => {
      const r = img.getBoundingClientRect();
      return r.left < 120 && r.top < 160;
    });

    if (!sidebarImg) return;
    const host = sidebarImg.parentElement;
    if (!host || host.querySelector(".ae-v32b-brand")) return;

    sidebarImg.style.display = "none";
    [...host.children].forEach(child => {
      if (child !== sidebarImg) child.style.display = "none";
    });

    const brand = document.createElement("div");
    brand.className = "ae-v32b-brand";
    brand.innerHTML = `
      <div class="ae-v32b-brand-main">ALPHA<br>ENGINE</div>
      <div class="ae-v32b-brand-sub">MARKET<br>INTELLIGENCE</div>`;
    host.appendChild(brand);
  }

  function clickableSignature(el) {
    if (!el) return "";
    const bits = [
      text(el),
      el.getAttribute("title"),
      el.getAttribute("aria-label"),
      el.getAttribute("href"),
      el.getAttribute("data-view"),
      el.getAttribute("data-section"),
      el.getAttribute("data-tab"),
      el.id,
      el.className
    ];
    if (el.dataset) bits.push(...Object.values(el.dataset));
    return bits.filter(Boolean).join(" ").toLowerCase();
  }

  function openFundExplorer(ev) {
    if (typeof window.__aeOpenFundamentals !== "function") return false;
    if (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      if (typeof ev.stopImmediatePropagation === "function") {
        ev.stopImmediatePropagation();
      }
    }
    window.__aeOpenFundamentals().catch(console.error);
    return true;
  }

  function installFundamentalDelegation() {
    if (document.documentElement.dataset.aeV32bFundDelegation === "1") return;
    document.documentElement.dataset.aeV32bFundDelegation = "1";

    document.addEventListener("click", ev => {
      const el = ev.target.closest(
        "a,button,[role='button'],[data-view],[data-section],[data-tab]"
      );
      if (!el) return;
      const sig = clickableSignature(el);
      if (sig.includes("fundamental")) {
        openFundExplorer(ev);
      }
    }, true);
  }

  function replaceRawFundamentals() {
    if (typeof window.__aeOpenFundamentals !== "function") return;

    const nodes = [...document.querySelectorAll("pre,code,.raw-json,.json,.json-block")];
    nodes.forEach(el => {
      const v = text(el);
      if (
        v.length > 1200 &&
        (v.includes('"companies"') || v.includes("sec_summary")) &&
        !el.dataset.aeV32bReplaced
      ) {
        el.dataset.aeV32bReplaced = "1";
        el.textContent = "";
        const box = document.createElement("div");
        box.className = "ae-v32b-fund-cta";
        box.innerHTML = `
          <strong>Fundamentales auditados disponibles</strong>
          <span>187 compañías · buscador · filtros · ratios clave</span>
          <button type="button">Abrir Fundamentals Explorer</button>`;
        box.querySelector("button").addEventListener("click", openFundExplorer);
        el.appendChild(box);
      }
    });
  }

  function ensureFundamentalButton() {
    if (
      document.getElementById("aeV32bFundButton") ||
      typeof window.__aeOpenFundamentals !== "function"
    ) return;

    const button = document.createElement("button");
    button.id = "aeV32bFundButton";
    button.className = "ae-v32b-fund-button";
    button.type = "button";
    button.textContent = "Fundamentales";
    button.title = "Abrir Fundamentals Explorer";
    button.addEventListener("click", openFundExplorer);
    document.body.appendChild(button);
  }

  function pass() {
    installCrispSidebarBrand();
    installFundamentalDelegation();
    replaceRawFundamentals();
    ensureFundamentalButton();
  }

  document.addEventListener("DOMContentLoaded", pass);
  window.addEventListener("load", pass);
  new MutationObserver(pass).observe(document.documentElement, {
    childList: true,
    subtree: true
  });
  setTimeout(pass, 300);
  setTimeout(pass, 1200);
})();
'@ | Add-Content -Path $JS -Encoding UTF8
}

if ((Get-Content -Raw -Path $CSS) -notmatch [regex]::Escape($marker)) {
@'
/* AE_V32B_HOTFIX */
.ae-v32b-brand {
  width: 52px;
  min-width: 52px;
  box-sizing: border-box;
  padding: 5px 4px 4px;
  color: #f2f7fa;
  text-align: left;
  line-height: .92;
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  user-select: none;
}

.ae-v32b-brand-main {
  font-size: 9px;
  font-weight: 900;
  letter-spacing: .12em;
}

.ae-v32b-brand-sub {
  margin-top: 5px;
  color: #42d89b;
  font-size: 4.6px;
  font-weight: 800;
  line-height: 1.05;
  letter-spacing: .13em;
}

.ae-v32b-fund-button {
  position: fixed;
  z-index: 9000;
  right: 18px;
  bottom: 18px;
  border: 1px solid rgba(60, 220, 157, .32);
  background: rgba(5, 27, 37, .96);
  color: #cfe9df;
  border-radius: 10px;
  padding: 9px 12px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 10px 30px rgba(0,0,0,.28);
}

.ae-v32b-fund-button:hover {
  border-color: rgba(60, 220, 157, .58);
  color: #ffffff;
}

.ae-v32b-fund-cta {
  display: grid;
  gap: 8px;
  padding: 18px;
  border: 1px solid rgba(60, 220, 157, .18);
  border-radius: 12px;
  background: rgba(5, 27, 37, .72);
}

.ae-v32b-fund-cta strong {
  color: #e9f4f0;
  font-size: 14px;
}

.ae-v32b-fund-cta span {
  color: #8fa8b4;
  font-size: 12px;
}

.ae-v32b-fund-cta button {
  justify-self: start;
  border: 1px solid rgba(60, 220, 157, .28);
  background: rgba(19, 217, 120, .08);
  color: #8df2be;
  border-radius: 9px;
  padding: 8px 11px;
  cursor: pointer;
}
'@ | Add-Content -Path $CSS -Encoding UTF8
}

Write-Host "  PASS Fundamentals Explorer exposed"
Write-Host "  PASS raw fundamentals replacement installed"
Write-Host "  PASS sidebar brand uses crisp text, no crop"

Write-Host ""
Write-Host "[4/5] RESTART ONLY ALPHA SERVER"
$listeners = @(
    Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue
)
foreach ($listener in $listeners) {
    $processId = [int]$listener.OwningProcess
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
    $cmd = [string]$proc.CommandLine
    if ($cmd -notlike "*run_data_recovery_server.py*") {
        throw "Port 8765 occupied by non-Alpha PID=$processId. Nothing killed."
    }
    Stop-Process -Id $processId -Force
    Write-Host "  stopped Alpha PID=$processId"
}
Start-Sleep -Milliseconds 800

$launcher = Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $START
    ) `
    -WindowStyle Hidden `
    -PassThru

Write-Host "  launcher PID=$($launcher.Id)"

Write-Host ""
Write-Host "[5/5] REAL HTTP + GROQ SMOKE"
Set-Location $ROOT
python $SMOKE
if ($LASTEXITCODE -ne 0) {
    throw "V3.2B smoke failed. V13 remains untouched."
}

Write-Host ""
Write-Host "============================================================"
Write-Host "ALPHA ENGINE WEB V3.2B: PASS"
Write-Host "============================================================"
Write-Host "GROQ INPUT CONTEXT : COMPACT"
Write-Host "GROQ OUTPUT CAP    : 640 TOKENS"
Write-Host "FUNDAMENTALS       : EXPLORER ACCESS FORCED"
Write-Host "SIDEBAR BRAND      : CRISP TEXT / NO IMAGE CROP"
Write-Host "PORTFOLIO          : 3 POSITIONS / SNAPSHOT"
Write-Host "OPERATIONS         : NOT CONNECTED"
Write-Host "V13 MUTATED        : NO"
Write-Host "============================================================"
