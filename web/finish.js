(() => {
  "use strict";

  const LOGO = "/assets/alpha-engine-wordmark.png?v=32";
  const PAGE_SIZE = 25;
  let stateCache = null;
  let fundPage = 0;
  let fundQuery = "";
  let fundSector = "ALL";

  const esc = (x) => String(x ?? "");

  async function getState(force=false) {
    if (stateCache && !force) return stateCache;
    const r = await fetch("/api/state" + (force ? "?refresh=1" : ""), {
      cache: "no-store"
    });
    if (!r.ok) throw new Error("state " + r.status);
    stateCache = await r.json();
    return stateCache;
  }

  function leafText(selector="body *") {
    return [...document.querySelectorAll(selector)]
      .filter(el => el.children.length === 0);
  }

  function fixLogo() {
    const imgs = [...document.querySelectorAll("img")].filter(img => {
      const src = (img.getAttribute("src") || "").toLowerCase();
      return src.includes("alpha-engine") || src.includes("alpha_engine");
    });

    imgs.forEach(img => {
      img.src = LOGO;
      img.style.objectFit = "contain";
      img.style.objectPosition = "center";
      img.style.borderRadius = "0";
      img.style.transform = "none";

      const p = img.parentElement;
      if (p && /ALPHA ENGINE/i.test(p.textContent || "")) {
        p.classList.add("ae-brand-fixed");
      }
    });
  }

  function fmtNum(v, d=2) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    return n.toLocaleString("es-AR", {
      minimumFractionDigits: d,
      maximumFractionDigits: d
    });
  }

  function fmtPct(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    const z = Math.abs(n) <= 2 ? n * 100 : n;
    return z.toLocaleString("es-AR", {
      maximumFractionDigits: 1
    }) + "%";
  }

  function fmtCap(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    if (Math.abs(n) >= 1e12) return (n/1e12).toFixed(2) + "T";
    if (Math.abs(n) >= 1e9) return (n/1e9).toFixed(2) + "B";
    if (Math.abs(n) >= 1e6) return (n/1e6).toFixed(1) + "M";
    return fmtNum(n,0);
  }

  function ensureModal() {
    if (document.getElementById("aeV32Modal")) return;

    const backdrop = document.createElement("div");
    backdrop.id = "aeV32Backdrop";
    backdrop.className = "ae-v32-modal-backdrop";

    const modal = document.createElement("div");
    modal.id = "aeV32Modal";
    modal.className = "ae-v32-modal";
    modal.innerHTML = `
      <div class="ae-v32-modal-head">
        <div>
          <h2>Fundamentals Explorer</h2>
          <div class="meta" id="aeFundMeta">Data Recovery V1</div>
        </div>
        <button class="ae-v32-close" id="aeV32Close">Cerrar</button>
      </div>
      <div class="ae-v32-toolbar">
        <input id="aeFundSearch" placeholder="Buscar ticker, empresa o sector…" />
        <select id="aeFundSector"><option value="ALL">Todos los sectores</option></select>
        <div id="aeFundCount" style="align-self:center;color:#8fa5b1;font-size:11px"></div>
      </div>
      <div class="ae-v32-table-wrap">
        <table class="ae-v32-table">
          <thead><tr>
            <th>Ticker</th><th>Empresa</th><th>Sector</th><th>Precio</th>
            <th>Market Cap</th><th>P/E</th><th>Fwd P/E</th><th>ROE</th>
            <th>Debt/Eq</th><th>Margen</th><th>Rev Growth</th>
            <th>FCF Yield</th><th>Fuente</th>
          </tr></thead>
          <tbody id="aeFundBody"></tbody>
        </table>
      </div>
      <div class="ae-v32-pager">
        <span id="aeFundPageInfo"></span>
        <div>
          <button id="aeFundPrev">Anterior</button>
          <button id="aeFundNext">Siguiente</button>
        </div>
      </div>`;

    document.body.appendChild(backdrop);
    document.body.appendChild(modal);

    const close = () => {
      backdrop.classList.remove("open");
      modal.classList.remove("open");
    };
    document.getElementById("aeV32Close").onclick = close;
    backdrop.onclick = close;

    document.getElementById("aeFundSearch").addEventListener("input", e => {
      fundQuery = e.target.value.trim().toLowerCase();
      fundPage = 0;
      renderFundamentals();
    });

    document.getElementById("aeFundSector").addEventListener("change", e => {
      fundSector = e.target.value;
      fundPage = 0;
      renderFundamentals();
    });

    document.getElementById("aeFundPrev").onclick = () => {
      fundPage = Math.max(0, fundPage - 1);
      renderFundamentals();
    };
    document.getElementById("aeFundNext").onclick = () => {
      fundPage += 1;
      renderFundamentals();
    };
  }

  async function openFundamentals() {
    ensureModal();
    await getState(true);

    const sectorSel = document.getElementById("aeFundSector");
    const companies = stateCache?.fundamentals?.companies || [];
    const sectors = [...new Set(
      companies.map(x => x.sector).filter(Boolean)
    )].sort((a,b) => String(a).localeCompare(String(b)));

    const current = sectorSel.value || "ALL";
    sectorSel.innerHTML = '<option value="ALL">Todos los sectores</option>';
    sectors.forEach(s => {
      const o = document.createElement("option");
      o.value = s;
      o.textContent = s;
      sectorSel.appendChild(o);
    });
    if ([...sectorSel.options].some(o => o.value === current)) {
      sectorSel.value = current;
    }

    document.getElementById("aeV32Backdrop").classList.add("open");
    document.getElementById("aeV32Modal").classList.add("open");
    renderFundamentals();
  }

  window.__aeOpenFundamentals = openFundamentals;

  function filteredFundamentals() {
    const companies = stateCache?.fundamentals?.companies || [];
    return companies.filter(r => {
      const sectorOK = fundSector === "ALL" || esc(r.sector) === fundSector;
      const hay = [r.ticker, r.name, r.sector]
        .map(x => esc(x).toLowerCase())
        .join(" ");
      const queryOK = !fundQuery || hay.includes(fundQuery);
      return sectorOK && queryOK;
    });
  }

  function td(tr, value, cls="") {
    const cell = document.createElement("td");
    if (cls) cell.className = cls;
    cell.textContent = value;
    tr.appendChild(cell);
  }

  function renderFundamentals() {
    if (!stateCache) return;
    const all = filteredFundamentals();
    const pages = Math.max(1, Math.ceil(all.length / PAGE_SIZE));
    fundPage = Math.min(fundPage, pages - 1);

    const start = fundPage * PAGE_SIZE;
    const rows = all.slice(start, start + PAGE_SIZE);
    const body = document.getElementById("aeFundBody");
    body.textContent = "";

    rows.forEach(r => {
      const tr = document.createElement("tr");
      td(tr, esc(r.ticker), "ae-v32-ticker");
      td(tr, esc(r.name));
      td(tr, esc(r.sector));
      td(tr, r.price_usd == null ? "—" : "$" + fmtNum(r.price_usd,2));
      td(tr, fmtCap(r.market_cap));
      td(tr, fmtNum(r.pe,2));
      td(tr, fmtNum(r.forward_pe,2));
      td(tr, fmtPct(r.roe));
      td(tr, fmtNum(r.debt_to_equity,2));
      td(tr, fmtPct(r.net_margin));
      td(tr, fmtPct(r.revenue_growth));
      td(tr, fmtPct(r.fcf_yield));
      td(tr, esc(r.source || "—"), "ae-v32-source");
      body.appendChild(tr);
    });

    document.getElementById("aeFundCount").textContent =
      `${all.length} compañías`;
    document.getElementById("aeFundPageInfo").textContent =
      `Página ${fundPage + 1} de ${pages} · filas ${all.length ? start + 1 : 0}–${Math.min(start + PAGE_SIZE, all.length)}`;

    const asof = stateCache?.fundamentals?.asof || "—";
    document.getElementById("aeFundMeta").textContent =
      `Data Recovery V1 · ${stateCache?.fundamentals?.rows ?? all.length} filas · as of ${asof}`;

    document.getElementById("aeFundPrev").disabled = fundPage <= 0;
    document.getElementById("aeFundNext").disabled = fundPage >= pages - 1;
  }

  function bindFundamentalsNav() {
    [...document.querySelectorAll("a,button")].forEach(el => {
      const label = (el.textContent || "").trim().toLowerCase();
      if (label === "fundamentales" && !el.dataset.aeV32Bound) {
        el.dataset.aeV32Bound = "1";
        el.addEventListener("click", ev => {
          ev.preventDefault();
          ev.stopPropagation();
          openFundamentals().catch(console.error);
        }, true);
      }
    });
  }

  async function semanticStatusPass() {
    try {
      const s = await getState(true);
      const count = Number(
        s?.personal?.positions_count ??
        s?.personal?.position_rows ??
        s?.personal?.positions?.length ??
        0
      );

      leafText().forEach(el => {
        const v = (el.textContent || "").trim();

        if (/^0 posiciones$/i.test(v) && count > 0) {
          el.textContent = `${count} posiciones · snapshot auditado`;
        }

        if (/^0 operaciones$/i.test(v)) {
          el.textContent = "Ledger de operaciones no conectado";
        }

        if (/^operaciones personales\s*0$/i.test(v)) {
          el.textContent = "Operaciones personales · fuente no conectada";
        }
      });

      // Insert explicit status into visible Mi Cartera content once.
      const headings = [...document.querySelectorAll("h1,h2,h3,h4")]
        .filter(x => /mi cartera/i.test(x.textContent || ""));
      headings.forEach(h => {
        const container = h.closest("section,main,.panel,.view,.content") || h.parentElement;
        if (!container || container.querySelector(".ae-v32-status-card")) return;

        const card = document.createElement("div");
        card.className = "ae-v32-status-card";
        card.innerHTML = `
          <div class="title">Operaciones personales · fuente no conectada</div>
          <div class="copy">
            Las 3 posiciones visibles provienen del snapshot auditado V13.
            El ledger local de operaciones está vacío y no se interpreta como
            “cero operaciones”. La importación de operaciones ejecutadas queda
            pendiente de conectar a una fuente autoritativa.
          </div>`;
        h.insertAdjacentElement("afterend", card);
      });

      // Add separate clocks where an overview/status panel is visible.
      const mainHeading = [...document.querySelectorAll("h1,h2")]
        .find(x => /overview|alpha engine v13/i.test(x.textContent || ""));
      if (mainHeading && !document.getElementById("aeClockBar")) {
        const d = s?._web?.model_dates || {};
        const bar = document.createElement("div");
        bar.id = "aeClockBar";
        bar.className = "ae-v32-clockbar";
        bar.innerHTML = `
          <span class="ae-v32-clock"><strong>OOS sellado</strong> ${esc(d.historical_oos_last_score_date || "—")}</span>
          <span class="ae-v32-clock"><strong>Live shadow</strong> ${esc(d.live_shadow_latest_completed_session || "—")}</span>
          <span class="ae-v32-clock"><strong>Mercado</strong> ${esc(d.market_data_asof || "—")}</span>`;
        mainHeading.insertAdjacentElement("afterend", bar);
      }
    } catch (_) {}
  }

  let queued = false;
  function pass() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(async () => {
      queued = false;
      fixLogo();
      bindFundamentalsNav();
      await semanticStatusPass();
    });
  }

  document.addEventListener("DOMContentLoaded", pass);
  window.addEventListener("load", pass);
  new MutationObserver(pass).observe(document.documentElement, {
    childList: true,
    subtree: true
  });
  setTimeout(pass, 400);
  setTimeout(pass, 1500);
})();

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
