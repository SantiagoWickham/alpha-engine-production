let STATE = null;
let CURRENT_SECTION = "overview";


const sectionTitles = {
  overview: "Overview",
  recommendations: "Recomendaciones",
  byma: "BYMA Model",
  portfolio: "Mi Cartera",
  market: "Mercado & Riesgo",
  fundamentals: "Fundamentales",
  alpha: "Alpha AI",
  system: "Sistema",
};


const $ = (
  selector
) => document.querySelector(
  selector
);


const $$ = (
  selector
) => [
  ...document.querySelectorAll(
    selector
  ),
];


function numberValue(value) {

  const n = Number(value);

  return Number.isFinite(n)
    ? n
    : null;
}


function pct(
  value,
  digits = 2
) {

  const n = numberValue(
    value
  );

  if (n === null) {
    return "N/D";
  }

  return (
    (
      n * 100
    ).toFixed(digits)
    + "%"
  );
}


function money(
  value,
  digits = 2
) {

  const n = numberValue(
    value
  );

  if (n === null) {
    return "N/D";
  }

  return new Intl.NumberFormat(
    "en-US",
    {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }
  ).format(n);
}


function num(
  value,
  digits = 2
) {

  const n = numberValue(
    value
  );

  if (n === null) {
    return "N/D";
  }

  return new Intl.NumberFormat(
    "en-US",
    {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }
  ).format(n);
}


function boolText(value) {

  if (value === true) {
    return "YES";
  }

  if (value === false) {
    return "NO";
  }

  return "N/D";
}


function cleanValue(value) {

  if (
    value === null
    || value === undefined
    || value === ""
  ) {
    return "N/D";
  }

  if (
    typeof value
    === "object"
  ) {
    return JSON.stringify(
      value
    );
  }

  return String(value);
}


function badge(
  value,
  positive = false
) {

  const className =
    positive
      ? "tag green"
      : "tag";

  return (
    `<span class="${className}">`
    + cleanValue(value)
    + "</span>"
  );
}


function metricCard(
  label,
  value,
  subtitle = ""
) {

  return `
    <div class="metric-card">
      <div class="metric-label">
        ${label}
      </div>

      <div class="metric-value">
        ${value}
      </div>

      <div class="metric-sub">
        ${subtitle}
      </div>
    </div>
  `;
}


function emptyRow(
  colspan,
  text
) {

  return `
    <tr>
      <td
        colspan="${colspan}"
        class="empty-state"
      >
        ${text}
      </td>
    </tr>
  `;
}


function statusRow(
  label,
  value
) {

  return `
    <div class="status-list-row">
      <span>${label}</span>
      <strong>${cleanValue(value)}</strong>
    </div>
  `;
}


function showSection(
  section
) {

  CURRENT_SECTION = section;

  $$(".page-section")
    .forEach(
      element => {

        element
          .classList
          .toggle(
            "active",
            element.id
              ===
              `section-${section}`
          );

      }
    );


  $$(".nav-item")
    .forEach(
      element => {

        element
          .classList
          .toggle(
            "active",
            element.dataset.section
              ===
              section
          );

      }
    );


  $("#page-title")
    .textContent =
      sectionTitles[
        section
      ] || section;


  if (
    section === "overview"
    && STATE
  ) {

    requestAnimationFrame(
      () =>
        drawNavChart(
          STATE
        )
    );

  }

}


function flattenObject(
  obj,
  prefix = "",
  out = []
) {

  Object.entries(
    obj || {}
  ).forEach(
    ([key, value]) => {

      const full =
        prefix
          ? `${prefix}.${key}`
          : key;


      if (
        value !== null
        &&
        typeof value === "object"
        &&
        !Array.isArray(value)
      ) {

        flattenObject(
          value,
          full,
          out
        );

      } else {

        out.push([
          full,
          value,
        ]);

      }

    }
  );

  return out;
}


function renderDataList(
  selector,
  object,
  limit = 200
) {

  const rows =
    flattenObject(
      object
    )
      .slice(
        0,
        limit
      );


  const container =
    $(selector);


  if (
    rows.length === 0
  ) {

    container.innerHTML =
      `<div class="empty-state">Sin datos disponibles.</div>`;

    return;
  }


  container.innerHTML =
    rows
      .map(
        ([key, value]) => `
          <div class="data-row">
            <div class="data-key">
              ${key}
            </div>

            <div class="data-value">
              ${cleanValue(value)}
            </div>
          </div>
        `
      )
      .join("");

}


function renderHeader(
  state
) {

  const system =
    state.system || {};


  $("#asof")
    .textContent =
      system.asof || "N/D";


  const status =
    $("#system-status");


  const pass =
    system.status === "PASS";


  status.textContent =
    system.status || "UNKNOWN";


  status.className =
    pass
      ? "status-pill pass"
      : "status-pill fail";


  $("#hero-holdout")
    .textContent =
      system.holdout_verdict
      || "N/D";


  $("#hero-local")
    .textContent =
      system.local_implementation
      || "N/D";


  $("#hero-description")
    .textContent =
      `Autoridad ${system.authority || "N/D"} · `
      +
      `Seal ${(system.seal_id || "").slice(0, 12)}…`;

}


function renderOverview(
  state
) {

  const overview =
    state.overview || {};

  const v13 =
    state.v13?.performance || {};

  const byma =
    state.byma?.performance || {};

  const personal =
    state.personal?.summary || {};


  $("#overview-cards")
    .innerHTML = [

      metricCard(
        "V13 CAGR",
        pct(
          v13.full_period_cagr
        ),
        "Período completo"
      ),

      metricCard(
        "BYMA CAGR",
        pct(
          byma.full_period_cagr
        ),
        "Accepted BYMA Transfer"
      ),

      metricCard(
        "TARGETS POSITIVOS",
        num(
          overview.positive_target_count,
          0
        ),
        `${overview.entry_eligible_count || 0} entry eligible`
      ),

      metricCard(
        "MI CARTERA",
        personal.market_nav_usd
          !== null
          &&
          personal.market_nav_usd
          !== undefined
            ? money(
                personal.market_nav_usd
              )
            : cleanValue(
                personal.status
              ),
        `${overview.personal_positions_count || 0} posiciones`
      ),

    ].join("");


  $("#overview-status-list")
    .innerHTML = [

      statusRow(
        "Universo",
        overview.universe_count
      ),

      statusRow(
        "Entry eligible",
        overview.entry_eligible_count
      ),

      statusRow(
        "Targets positivos",
        overview.positive_target_count
      ),

      statusRow(
        "BYMA disponibles",
        overview.byma_available_count
      ),

      statusRow(
        "Operaciones personales",
        overview.personal_operations_count
      ),

      statusRow(
        "Posiciones personales",
        overview.personal_positions_count
      ),

    ].join("");


  const recs =
    (
      state.v13
        ?.recommendations
      || []
    )
      .filter(
        row =>
          numberValue(
            row.target_weight
          ) > 0
      )
      .slice(
        0,
        10
      );


  const body =
    $("#top-recommendations");


  if (
    recs.length === 0
  ) {

    body.innerHTML =
      emptyRow(
        5,
        "No hay recomendaciones positivas."
      );

  } else {

    body.innerHTML =
      recs
        .map(
          row => `
            <tr>
              <td class="ticker">
                ${cleanValue(row.ticker)}
              </td>

              <td>
                ${badge(row.model_intent)}
              </td>

              <td>
                ${pct(row.target_weight)}
              </td>

              <td>
                ${pct(row.expected_active_total)}
              </td>

              <td>
                ${
                  row.entry_ok
                    ? badge("YES", true)
                    : badge("NO")
                }
              </td>
            </tr>
          `
        )
        .join("");

  }

}


function renderRecommendations(
  state
) {

  const all =
    state.v13
      ?.recommendations || [];


  const search =
    (
      $("#recommendation-search")
        ?.value || ""
    )
      .trim()
      .toUpperCase();


  const filter =
    $("#recommendation-filter")
      ?.value || "all";


  const rows =
    all.filter(
      row => {

        const ticker =
          String(
            row.ticker || ""
          ).toUpperCase();


        if (
          search
          &&
          !ticker.includes(
            search
          )
        ) {
          return false;
        }


        if (
          filter === "positive"
          &&
          !(
            numberValue(
              row.target_weight
            ) > 0
          )
        ) {
          return false;
        }


        if (
          filter === "entry"
          &&
          row.entry_ok !== true
        ) {
          return false;
        }


        return true;

      }
    );


  const body =
    $("#recommendations-table");


  if (
    rows.length === 0
  ) {

    body.innerHTML =
      emptyRow(
        6,
        "Sin resultados."
      );

    return;
  }


  body.innerHTML =
    rows
      .map(
        row => `
          <tr>

            <td class="ticker">
              ${cleanValue(row.ticker)}
            </td>

            <td>
              ${badge(row.model_intent)}
            </td>

            <td>
              ${pct(row.target_weight)}
            </td>

            <td>
              ${pct(row.expected_active_total)}
            </td>

            <td>
              ${
                row.entry_ok
                  ? badge("YES", true)
                  : badge("NO")
              }
            </td>

            <td>
              ${cleanValue(row.signal_date)}
            </td>

          </tr>
        `
      )
      .join("");

}


function renderByma(
  state
) {

  const byma =
    state.byma || {};

  const perf =
    byma.performance || {};

  const retention =
    byma.retention || {};


  $("#byma-cards")
    .innerHTML = [

      metricCard(
        "CAGR COMPLETO",
        pct(
          perf.full_period_cagr
        ),
        "Accepted BYMA Transfer"
      ),

      metricCard(
        "RETENCIÓN PRE",
        pct(
          retention.pre2025_cagr_ratio
        ),
        "vs V13 Ideal"
      ),

      metricCard(
        "RETENCIÓN HOLDOUT",
        pct(
          retention.holdout_cagr_ratio
        ),
        "vs V13 Ideal"
      ),

    ].join("");


  const rows =
    byma.recommendations || [];


  const body =
    $("#byma-table");


  if (
    rows.length === 0
  ) {

    body.innerHTML =
      emptyRow(
        8,
        "Sin mapeos BYMA."
      );

    return;
  }


  body.innerHTML =
    rows
      .map(
        row => `
          <tr>

            <td class="ticker">
              ${cleanValue(row.ticker)}
            </td>

            <td>
              ${pct(row.v13_target_weight)}
            </td>

            <td>
              ${cleanValue(row.vehicle)}
            </td>

            <td class="ticker">
              ${cleanValue(row.byma_ticker)}
            </td>

            <td>
              ${cleanValue(row.ratio)}
            </td>

            <td>
              ${
                row.vehicle_available
                  ? badge("YES", true)
                  : badge("NO")
              }
            </td>

            <td>
              ${pct(row.actual_weight)}
            </td>

            <td>
              ${pct(row.weight_error)}
            </td>

          </tr>
        `
      )
      .join("");

}


function renderPortfolio(
  state
) {

  const personal =
    state.personal || {};

  const summary =
    personal.summary || {};

  const positions =
    personal.positions || [];

  const cash =
    personal.cash || {};

  const operations =
    personal.operations || [];


  $("#portfolio-cards")
    .innerHTML = [

      metricCard(
        "ESTADO",
        cleanValue(
          summary.status
        ),
        "Portfolio Engine"
      ),

      metricCard(
        "CAJA",
        money(
          summary.cash_usd
        ),
        "USD calculado"
      ),

      metricCard(
        "CAPITAL INVERTIDO",
        money(
          summary.total_cost_basis_usd
        ),
        "Costo base"
      ),

      metricCard(
        "P&L REALIZADO",
        money(
          summary.realized_pnl_usd
        ),
        "Acumulado"
      ),

    ].join("");


  const positionsBody =
    $("#portfolio-positions");


  if (
    positions.length === 0
  ) {

    positionsBody.innerHTML =
      emptyRow(
        6,
        "Todavía no hay posiciones reales."
      );

  } else {

    positionsBody.innerHTML =
      positions
        .map(
          row => `
            <tr>

              <td class="ticker">
                ${cleanValue(row.ticker)}
              </td>

              <td>
                ${num(row.quantity, 6)}
              </td>

              <td>
                ${money(row.average_cost_usd)}
              </td>

              <td>
                ${money(row.market_value_usd)}
              </td>

              <td class="${
                numberValue(
                  row.unrealized_pnl_usd
                ) > 0
                  ? "positive"
                  :
                numberValue(
                  row.unrealized_pnl_usd
                ) < 0
                  ? "negative"
                  : ""
              }">
                ${money(row.unrealized_pnl_usd)}
              </td>

              <td>
                ${pct(row.portfolio_weight)}
              </td>

            </tr>
          `
        )
        .join("");

  }


  $("#cash-list")
    .innerHTML = [

      statusRow(
        "Caja inicial",
        money(
          cash.initial_cash_usd
        )
      ),

      statusRow(
        "Caja actual",
        money(
          cash.current_cash_usd
        )
      ),

      statusRow(
        "Depósitos",
        money(
          cash.deposits_usd
        )
      ),

      statusRow(
        "Retiros",
        money(
          cash.withdrawals_usd
        )
      ),

      statusRow(
        "Dividendos",
        money(
          cash.dividends_usd
        )
      ),

      statusRow(
        "Fees",
        money(
          cash.fees_usd
        )
      ),

      statusRow(
        "Taxes",
        money(
          cash.taxes_usd
        )
      ),

    ].join("");


  const operationsBody =
    $("#operations-table");


  const latest =
    [...operations]
      .reverse()
      .slice(
        0,
        25
      );


  if (
    latest.length === 0
  ) {

    operationsBody.innerHTML =
      emptyRow(
        8,
        "Todavía no hay operaciones registradas."
      );

  } else {

    operationsBody.innerHTML =
      latest
        .map(
          row => `
            <tr>

              <td>
                ${cleanValue(
                  row.Fecha
                  ?? row.date
                )}
              </td>

              <td class="ticker">
                ${cleanValue(
                  row.Ticker
                  ?? row.ticker
                )}
              </td>

              <td>
                ${badge(
                  row["Operación"]
                  ?? row.operation
                )}
              </td>

              <td>
                ${cleanValue(
                  row.Cantidad
                  ?? row.quantity
                )}
              </td>

              <td>
                ${cleanValue(
                  row.Precio
                  ?? row.price
                )}
              </td>

              <td>
                ${cleanValue(
                  row.Moneda
                  ?? row.currency
                )}
              </td>

              <td>
                ${cleanValue(
                  row.Costos
                  ?? row.costs
                )}
              </td>

              <td>
                ${cleanValue(
                  row.Fuente
                  ?? row.source
                )}
              </td>

            </tr>
          `
        )
        .join("");

  }

}


function renderMarket(
  state
) {

  renderDataList(
    "#market-list",
    state.market || {}
  );


  renderDataList(
    "#risk-list",
    state.risk || {}
  );

}


function renderFundamentals(
  state
) {

  const f =
    state.fundamentals || {};

  const sec =
    f.sec_summary || {};


  $("#fundamental-cards")
    .innerHTML = [

      metricCard(
        "STATUS",
        cleanValue(
          f.status
        ),
        "Fundamental layer"
      ),

      metricCard(
        "MAPPED",
        cleanValue(
          sec.mapped_tickers
          ?? sec.mapped
        ),
        "SEC tickers"
      ),

      metricCard(
        "SUCCESS",
        sec.success_rate
          !== undefined
          ? pct(
              sec.success_rate
            )
          : "N/D",
        "SEC ingestion"
      ),

    ].join("");


  renderDataList(
    "#fundamentals-list",
    f
  );

}


function renderSystem(
  state
) {

  const systemData = {

    ...(
      state.system || {}
    ),

    web_source:
      state._web?.source,

    product_schema:
      state.schema,

    generated_at_utc:
      state.generated_at_utc,

    methodology:
      state.performance
        ?.methodology,

  };


  renderDataList(
    "#system-list",
    systemData
  );

}


function drawNavChart(
  state
) {

  const canvas =
    $("#nav-chart");


  if (!canvas) {
    return;
  }


  const history =
    state.performance
      ?.nav_history || [];


  const rect =
    canvas
      .getBoundingClientRect();


  if (
    rect.width <= 0
    ||
    rect.height <= 0
  ) {
    return;
  }


  const dpr =
    window.devicePixelRatio
    || 1;


  canvas.width =
    Math.floor(
      rect.width * dpr
    );


  canvas.height =
    Math.floor(
      rect.height * dpr
    );


  const ctx =
    canvas.getContext(
      "2d"
    );


  ctx.scale(
    dpr,
    dpr
  );


  const width =
    rect.width;

  const height =
    rect.height;


  ctx.clearRect(
    0,
    0,
    width,
    height
  );


  if (
    history.length < 2
  ) {

    ctx.fillStyle =
      "#7f8da1";

    ctx.font =
      "12px Segoe UI";

    ctx.fillText(
      "Sin historial NAV.",
      25,
      35
    );

    return;
  }


  const series = [

    {
      key:
        "v13_ideal_index_100",
      color:
        "#64a8ff",
    },

    {
      key:
        "byma_model_index_100",
      color:
        "#49d69f",
    },

    {
      key:
        "personal_portfolio_nav",
      color:
        "#f2b45f",
    },

  ];


  let values = [];


  series.forEach(
    s => {

      history.forEach(
        row => {

          const value =
            numberValue(
              row[s.key]
            );


          if (
            value !== null
          ) {

            values.push(
              value
            );

          }

        }
      );

    }
  );


  if (
    values.length === 0
  ) {
    return;
  }


  let min =
    Math.min(
      ...values
    );


  let max =
    Math.max(
      ...values
    );


  if (
    min === max
  ) {

    min -= 1;
    max += 1;

  }


  const pad = {
    left: 52,
    right: 18,
    top: 18,
    bottom: 33,
  };


  const chartW =
    width
    - pad.left
    - pad.right;


  const chartH =
    height
    - pad.top
    - pad.bottom;


  const xAt =
    i =>
      pad.left
      +
      (
        i
        /
        Math.max(
          history.length - 1,
          1
        )
      )
      *
      chartW;


  const yAt =
    value =>
      pad.top
      +
      (
        1
        -
        (
          value - min
        )
        /
        (
          max - min
        )
      )
      *
      chartH;


  ctx.strokeStyle =
    "#1c2939";

  ctx.lineWidth = 1;


  ctx.fillStyle =
    "#68788d";

  ctx.font =
    "9px Segoe UI";


  const gridLines = 5;


  for (
    let i = 0;
    i <= gridLines;
    i++
  ) {

    const ratio =
      i / gridLines;


    const y =
      pad.top
      +
      ratio * chartH;


    ctx.beginPath();

    ctx.moveTo(
      pad.left,
      y
    );

    ctx.lineTo(
      width - pad.right,
      y
    );

    ctx.stroke();


    const value =
      max
      -
      ratio
      *
      (
        max - min
      );


    ctx.fillText(
      value.toFixed(0),
      6,
      y + 3
    );

  }


  series.forEach(
    s => {

      let started =
        false;


      ctx.beginPath();

      ctx.strokeStyle =
        s.color;

      ctx.lineWidth =
        1.7;


      history.forEach(
        (row, i) => {

          const value =
            numberValue(
              row[s.key]
            );


          if (
            value === null
          ) {

            started = false;
            return;

          }


          const x =
            xAt(i);

          const y =
            yAt(value);


          if (!started) {

            ctx.moveTo(
              x,
              y
            );

            started = true;

          } else {

            ctx.lineTo(
              x,
              y
            );

          }

        }
      );


      ctx.stroke();

    }
  );


  const ticks = 6;


  for (
    let i = 0;
    i < ticks;
    i++
  ) {

    const index =
      Math.round(
        (
          i
          /
          (
            ticks - 1
          )
        )
        *
        (
          history.length - 1
        )
      );


    const row =
      history[index];


    if (!row) {
      continue;
    }


    const x =
      xAt(index);


    ctx.fillStyle =
      "#68788d";


    ctx.fillText(
      String(
        row.date || ""
      ).slice(
        0,
        10
      ),
      Math.max(
        0,
        x - 28
      ),
      height - 8
    );

  }

}


function renderAll(
  state
) {

  STATE = state;

  renderHeader(
    state
  );

  renderOverview(
    state
  );

  renderRecommendations(
    state
  );

  renderByma(
    state
  );

  renderPortfolio(
    state
  );

  renderMarket(
    state
  );

  renderFundamentals(
    state
  );

  renderSystem(
    state
  );


  $("#loading")
    .classList
    .add(
      "hidden"
    );


  if (
    CURRENT_SECTION
    ===
    "overview"
  ) {

    requestAnimationFrame(
      () =>
        drawNavChart(
          state
        )
    );

  }

}


async function loadState(
  force = false
) {

  $("#error-box")
    .classList
    .add(
      "hidden"
    );


  try {

    const response =
      await fetch(
        `/api/state${force ? "?refresh=1" : ""}`,
        {
          cache: "no-store",
        }
      );


    if (!response.ok) {

      throw new Error(
        `HTTP ${response.status}`
      );

    }


    const state =
      await response.json();


    if (
      state.status === "FAIL"
    ) {

      throw new Error(
        state.error
        || "Product State failed"
      );

    }


    renderAll(
      state
    );


  } catch (error) {

    $("#loading")
      .classList
      .add(
        "hidden"
      );


    const box =
      $("#error-box");


    box.textContent =
      `ALPHA WEB ERROR: ${error.message}`;


    box.classList.remove(
      "hidden"
    );


    const status =
      $("#system-status");


    status.textContent =
      "FAIL";


    status.className =
      "status-pill fail";

  }

}


$$(".nav-item")
  .forEach(
    button => {

      button.addEventListener(
        "click",
        () => {

          showSection(
            button.dataset.section
          );

        }
      );

    }
  );


$$("[data-goto]")
  .forEach(
    button => {

      button.addEventListener(
        "click",
        () => {

          showSection(
            button.dataset.goto
          );

        }
      );

    }
  );


$("#refresh-btn")
  .addEventListener(
    "click",
    async () => {

      const button =
        $("#refresh-btn");


      button.disabled =
        true;


      button.textContent =
        "Actualizando…";


      await loadState(
        true
      );


      button.disabled =
        false;


      button.textContent =
        "Actualizar";

    }
  );


$("#recommendation-search")
  .addEventListener(
    "input",
    () => {

      if (STATE) {
        renderRecommendations(
          STATE
        );
      }

    }
  );


$("#recommendation-filter")
  .addEventListener(
    "change",
    () => {

      if (STATE) {
        renderRecommendations(
          STATE
        );
      }

    }
  );


window.addEventListener(
  "resize",
  () => {

    if (
      STATE
      &&
      CURRENT_SECTION
        ===
        "overview"
    ) {

      drawNavChart(
        STATE
      );

    }

  }
);


loadState(
  true
);
