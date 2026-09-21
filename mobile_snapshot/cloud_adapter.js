(() => {
  "use strict";

  const nativeFetch = window.fetch.bind(window);
  const base = new URL("./", window.location.href);

  let cache = null;
  let loadedAt = 0;

  const jget = async (name) => {
    const u = new URL(name, base);
    u.searchParams.set("_", Date.now());
    const r = await nativeFetch(u.toString(), { cache: "no-store" });
    if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
    return await r.json();
  };

  const load = async (force=false) => {
    if (cache && !force && Date.now() - loadedAt < 30000) return cache;
    const [market, model, fundamentals] = await Promise.all([
      jget("market.json").catch(e => ({status:"FAIL", error:String(e), rows:[]})),
      jget("model.json").catch(e => ({status:"FAIL", error:String(e), targets:[]})),
      jget("fundamentals.json").catch(() => ({status:"PASS", rows:[], count:0}))
    ]);
    cache = { market, model, fundamentals };
    loadedAt = Date.now();
    return cache;
  };

  const n = v => (v === null || v === undefined || v === "" || !Number.isFinite(Number(v))) ? null : Number(v);
  const b = v => v === true || String(v).toLowerCase() === "true" || String(v) === "1";

  const targetRows = (m) => (m.targets || []).map(r => ({
    signal_date: r.signal_date || m.latest_completed_session || "",
    ticker: String(r.ticker || "").toUpperCase(),
    target_weight: n(r.target_weight ?? r.model_target_weight),
    expected_active_total: n(r.expected_active_total ?? r.expected_active),
    entry_ok: b(r.entry_ok),
    model_intent: r.model_intent || (n(r.target_weight ?? r.model_target_weight) > 0 ? "TARGET" : "WATCH"),
    effective_horizon_sessions: n(r.effective_horizon_sessions)
  }));

  const marketRows = (x) => (x.rows || []).map(r => ({
    ticker: String(r.ticker || "").toUpperCase(),
    market_symbol: String(r.market_symbol || r.provider_symbol || "").toUpperCase(),
    benchmark: String(r.benchmark || "").toUpperCase(),
    price: n(r.price),
    var_1d: n(r.var_1d),
    ret_1m: n(r.ret_1m),
    ret_3m: n(r.ret_3m),
    ret_6m: n(r.ret_6m),
    ret_12m: n(r.ret_12m),
    sma20: n(r.sma20),
    sma50: n(r.sma50),
    sma200: n(r.sma200),
    rsi14: n(r.rsi14),
    vol_20d: n(r.vol_20d),
    vol_60d: n(r.vol_60d),
    vol_1y: n(r.vol_1y),
    max_drawdown_1y: n(r.max_drawdown_1y),
    beta_6m: n(r.beta_6m),
    corr_6m: n(r.corr_6m),
    dist_52w_high: n(r.dist_52w_high),
    source: r.source || "ALPHA_ENGINE_DATA_RECOVERY_V1",
    updated_at: r.updated_at || r.source_updated || x.generated_at_ba || x.generated_at_utc || "",
    coverage: n(r.coverage)
  }));

  const forwardObj = (m) => {
    const t = targetRows(m);
    const f = m.forward || {};
    const s = m.summary || {};
    return {
      status: m.status || "PASS",
      summary: {
        status: s.status || m.status || "PASS",
        last_observed: s.last_observed || f.start || "",
        latest_completed_session: s.latest_completed_session || m.latest_completed_session || f.latest || "",
        new_sessions: s.new_sessions ?? m.new_sessions ?? "",
        shadow_only: s.shadow_only ?? m.shadow_only ?? true,
        real_orders_sent: s.real_orders_sent ?? m.real_orders_sent ?? false,
        tuning_performed: s.tuning_performed ?? m.tuning_performed ?? false
      },
      latest_signal_date: m.latest_completed_session || f.latest || "",
      history_rows: m.history_rows ?? f.sessions ?? 0,
      latest_rows: t.length,
      seal_ids: m.seal_id ? [m.seal_id] : [],
      real_orders_sent: b(m.real_orders_sent),
      shadow_only: m.shadow_only !== false,
      top_exposures: t.slice().sort((a,z)=>(z.target_weight??-1)-(a.target_weight??-1)).slice(0,20),
      runner: {
        status: "CLOUD_SCHEDULED",
        relative: "GitHub Actions · 19:30 Argentina",
        candidates: []
      },
      performance_artifact: null,
      note: "Cloud read-only mirror. Official model refresh is scheduled in GitHub Actions."
    };
  };

  const overviewObj = ({market, model, fundamentals}) => {
    const tr = targetRows(model);
    const mr = marketRows(market);
    const f = forwardObj(model);
    return {
      status: "PASS",
      web_version: "V4.2-CLOUD",
      llm_status: "PAUSED",
      system: {
        authority: "V13_IDEAL",
        seal_id: model.seal_id || "",
        holdout_verdict: model.holdout_verdict || "",
        asof: model.latest_completed_session || "",
        status: model.status || "PASS"
      },
      clocks: {
        oos_sealed_through: "2026-09-04",
        live_shadow_through: model.latest_completed_session || "",
        market_asof: market.generated_at_ba || market.generated_at_utc || market.asof || ""
      },
      coverage: {
        market: market.asset_rows ?? mr.length,
        fundamentals: fundamentals.count ?? (fundamentals.rows || []).length,
        provider_failures: market.provider_failures ?? null
      },
      v13: {
        top: tr.slice().sort((a,z)=>(z.target_weight??-1)-(a.target_weight??-1)).slice(0,10),
        positive_targets: tr.filter(x => (x.target_weight ?? 0) > 0).length,
        entry_eligible: tr.filter(x => x.entry_ok === true).length
      },
      portfolio: {
        mode: "PRIVATE_NOT_PUBLISHED",
        positions: 0,
        operations: 0,
        buying_power_status: "PRIVATE"
      },
      forward: {
        status: f.status,
        runner: f.runner,
        real_orders_sent: false
      }
    };
  };

  const performanceObj = (m) => ({
    status: "PASS",
    series: Array.isArray(m.performance_series) ? m.performance_series : [],
    markers: { oos_start: "2025-01-02", live_shadow_start: "2026-09-04" },
    personal: { status: "PRIVATE_NOT_PUBLISHED", mode: "PUBLIC_READ_ONLY" },
    note: "Public cloud mirror. Personal portfolio is intentionally excluded."
  });

  const auditObj = ({market,model,fundamentals}) => ({
    status: "PASS",
    web_version: "V4.2-CLOUD",
    llm: {status:"PAUSED", network_calls:false},
    market: {
      authority:"ALPHA_ENGINE_DATA_RECOVERY_V1",
      rows: market.asset_rows ?? (market.rows||[]).length,
      regular_session_only:true,
      prepost:false,
      var_1d_contract:"regular_market_price / immediately_preceding_raw_daily_close - 1",
      cloud_snapshot_at: market.generated_at_ba || market.generated_at_utc || ""
    },
    fundamentals: {
      rows: fundamentals.count ?? (fundamentals.rows||[]).length,
      authority:"ALPHA_ENGINE_DATA_RECOVERY_V1"
    },
    v13: {
      authority:"V13_IDEAL",
      seal_id:model.seal_id || "",
      mutated_by_web:false
    },
    portfolio: {
      status:"PRIVATE_NOT_PUBLISHED",
      reason:"Public GitHub Pages never receives the personal ledger."
    },
    forward: forwardObj(model),
    orders:{real_orders_sent:false,broker_connection:false},
    sheets:{runtime_required:false},
    cloud:{read_only:true, provider:"GitHub Actions + GitHub Pages"}
  });

  const jsonResponse = obj => new Response(JSON.stringify(obj), {
    status: 200,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store"
    }
  });

  window.fetch = async function(input, init={}) {
    let url;
    try {
      url = new URL(typeof input === "string" ? input : input.url, window.location.href);
    } catch (_) {
      return nativeFetch(input, init);
    }

    const p = url.pathname;
    if (!p.includes("/api/")) return nativeFetch(input, init);

    const method = String(init.method || (typeof input !== "string" && input.method) || "GET").toUpperCase();

    // Public cloud copy is strictly read-only.
    if (method !== "GET") {
      return jsonResponse({
        status:"READ_ONLY",
        reason:"CLOUD_READ_ONLY_AUTO_REFRESH",
        message:"This public mirror is updated by GitHub Actions. No writes or real orders are allowed."
      });
    }

    const data = await load(false);

    if (p.endsWith("/api/health")) return jsonResponse({status:"PASS",web_version:"V4.2-CLOUD",llm:"PAUSED",v13_mutated:false});
    if (p.endsWith("/api/overview")) return jsonResponse(overviewObj(data));
    if (p.endsWith("/api/market")) return jsonResponse({
      status:"PASS",
      rows:marketRows(data.market),
      count:data.market.asset_rows ?? (data.market.rows||[]).length,
      asof:data.market.generated_at_ba || data.market.generated_at_utc || data.market.asof || "",
      contract:"regular_market_price / immediately_preceding_raw_daily_close - 1",
      prepost:false
    });
    if (p.endsWith("/api/fundamentals")) return jsonResponse(data.fundamentals || {status:"PASS",rows:[],count:0});
    if (p.endsWith("/api/v13")) return jsonResponse({
      status:"PASS",
      system:{
        authority:"V13_IDEAL",
        seal_id:data.model.seal_id || "",
        holdout_verdict:data.model.holdout_verdict || "",
        asof:data.model.latest_completed_session || "",
        status:data.model.status || "PASS"
      },
      summary:data.model.summary || {},
      performance:data.model.holdout_performance || {},
      recommendations:targetRows(data.model)
    });
    if (p.endsWith("/api/performance")) return jsonResponse(performanceObj(data.model));
    if (p.endsWith("/api/forward")) return jsonResponse(forwardObj(data.model));
    if (p.endsWith("/api/portfolio")) return jsonResponse({
      status:"PASS",
      mode:"PRIVATE_NOT_PUBLISHED",
      position_rows:0,
      operations_count:0,
      buying_power_status:"PRIVATE",
      totals_by_currency:{},
      positions:[],
      operations:[],
      workbook:"PRIVATE_NOT_PUBLISHED",
      ledger_json:"PRIVATE_NOT_PUBLISHED"
    });
    if (p.endsWith("/api/operations")) return jsonResponse({status:"PASS",operations:[],workbook:"PRIVATE_NOT_PUBLISHED"});
    if (p.endsWith("/api/audit")) return jsonResponse(auditObj(data));
    if (p.endsWith("/api/alpha")) return jsonResponse({status:"PAUSED",reason:"LLM_PAUSED_BY_DESIGN"});

    return jsonResponse({status:"FAIL", error:`CLOUD_API_ROUTE_NOT_MAPPED: ${p}`});
  };

  // Refresh the snapshots in-place every minute without replacing the V4 shell.
  setInterval(() => load(true).catch(()=>{}), 60000);

  document.addEventListener("DOMContentLoaded", () => {
    document.documentElement.dataset.cloudMirror = "true";
    const dangerous = [
      "#operationForm",
      "#syncExcel"
    ];
    dangerous.forEach(sel => {
      const el = document.querySelector(sel);
      if (el) {
        el.querySelectorAll("input,select,button,textarea").forEach(x => x.disabled = true);
        if ("disabled" in el) el.disabled = true;
      }
    });
  });
})();
