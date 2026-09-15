(() => {

  let STATE_V3 = null;

  let ALPHA_HISTORY = [];


  const BENCHMARKS = [
    {
      ticker:
        "SPY",

      label:
        "S&P 500"
    },

    {
      ticker:
        "QQQ",

      label:
        "Nasdaq"
    },

    {
      ticker:
        "IWM",

      label:
        "Russell 2000"
    },

    {
      ticker:
        "EEM",

      label:
        "Emerging"
    },

    {
      ticker:
        "^MERV",

      label:
        "S&P Merval"
    },

    {
      ticker:
        "ARS=X",

      label:
        "USD / ARS"
    },
  ];


  // ========================================================
  // HELPERS
  // ========================================================

  const esc = value =>

    String(
      value ?? ""
    )
    .replaceAll(
      "&",
      "&amp;"
    )
    .replaceAll(
      "<",
      "&lt;"
    )
    .replaceAll(
      ">",
      "&gt;"
    )
    .replaceAll(
      '"',
      "&quot;"
    );


  function missing(
    value
  ) {

    if (
      value === null ||
      value === undefined ||
      value === ""
    ) {

      return true;

    }


    if (
      typeof value === "number"
      &&
      !Number.isFinite(
        value
      )
    ) {

      return true;

    }


    if (
      typeof value === "string"
    ) {

      return [
        "nan",
        "+nan",
        "-nan",
        "null",
        "none",
        "<na>",
      ].includes(
        value
        .trim()
        .toLowerCase()
      );

    }


    return false;

  }


  function numberValue(
    value
  ) {

    const n =
      Number(
        value
      );


    return Number.isFinite(
      n
    )
      ? n
      : null;

  }


  function money(
    value,
    currency="USD"
  ) {

    const n =
      numberValue(
        value
      );


    if (
      n === null
    ) {

      return "—";

    }


    try {

      return new Intl
        .NumberFormat(
          "en-US",
          {
            style:
              "currency",

            currency:
              currency || "USD",

            maximumFractionDigits:
              2,
          }
        )
        .format(n);

    } catch (_) {

      return (
        n.toFixed(2)
        + " "
        + (
            currency || ""
          )
      );

    }

  }


  function pct(
    value
  ) {

    const n =
      numberValue(
        value
      );


    if (
      n === null
    ) {

      return "—";

    }


    return (
      (
        n * 100
      ).toFixed(2)
      + "%"
    );

  }


  function number(
    value,
    digits=2
  ) {

    const n =
      numberValue(
        value
      );


    if (
      n === null
    ) {

      return "—";

    }


    return new Intl
      .NumberFormat(
        "en-US",
        {
          maximumFractionDigits:
            digits,
        }
      )
      .format(n);

  }


  function marketChangeClass(
    value
  ) {

    const n =
      numberValue(
        value
      );


    if (
      n === null ||
      n === 0
    ) {

      return "flat";

    }


    return (
      n > 0
        ? "up"
        : "down"
    );

  }


  function humanKey(
    key
  ) {

    return String(
      key
    )
    .replaceAll(
      "_",
      " "
    )
    .replace(
      /\b\w/g,
      c =>
        c.toUpperCase()
    );

  }


  function smartValue(
    key,
    value
  ) {

    if (
      missing(
        value
      )
    ) {

      return "—";

    }


    if (
      typeof value ===
      "boolean"
    ) {

      return (
        value
          ? "YES"
          : "NO"
      );

    }


    if (
      typeof value ===
      "number"
    ) {

      const k =
        String(key)
        .toLowerCase();


      if (
        k.includes(
          "weight"
        )
        ||
        k.includes(
          "alpha"
        )
        ||
        k.includes(
          "return"
        )
        ||
        k.includes(
          "cagr"
        )
        ||
        k.includes(
          "margin"
        )
        ||
        k.includes(
          "pnl_pct"
        )
      ) {

        return pct(
          value
        );

      }


      return number(
        value,
        4
      );

    }


    if (
      typeof value ===
      "object"
    ) {

      return JSON.stringify(
        value
      );

    }


    return String(
      value
    );

  }


  // ========================================================
  // BRAND
  // ========================================================

  function installBrand() {

    const mark =
      document.querySelector(
        ".brand-mark"
      );


    if (
      mark
    ) {

      mark.innerHTML = `
        <img
          src="/assets/alpha-engine-logo.jpg"
          class="brand-logo"
          alt="Alpha Engine"
        >
      `;

    }


    const subtitle =
      document.querySelector(
        ".brand-subtitle"
      );


    if (
      subtitle
    ) {

      subtitle.textContent =
        "Market Intelligence";

    }


    const favicon =
      document.createElement(
        "link"
      );


    favicon.rel =
      "icon";


    favicon.href =
      "/assets/alpha-engine-logo.jpg";


    document.head
      .appendChild(
        favicon
      );

  }


  // ========================================================
  // STATE
  // ========================================================

  async function loadV3State() {

    try {

      STATE_V3 =
        await fetch(
          "/api/state",
          {
            cache:
              "no-store"
          }
        )
        .then(
          response =>
            response.json()
        );


      if (
        STATE_V3.system
      ) {

        installBrandBanner(
          STATE_V3
        );


        await installMarketTape(
          STATE_V3
        );

      }

    } catch (
      error
    ) {

      console.error(
        "V3 state:",
        error
      );

    }

  }


  // ========================================================
  // HERO
  // ========================================================

  function installBrandBanner(
    state
  ) {

    const section =
      document.getElementById(
        "section-overview"
      );


    if (
      !section ||
      document.getElementById(
        "alpha-brand-banner"
      )
    ) {

      return;

    }


    const banner =
      document.createElement(
        "div"
      );


    banner.id =
      "alpha-brand-banner";


    banner.className =
      "alpha-brand-banner";


    banner.innerHTML = `

      <div class="alpha-brand-copy">

        <div class="alpha-live-ribbon">

          <span class="alpha-live-dot"></span>

          ALPHA ENGINE SYSTEM ONLINE

        </div>


        <div class="alpha-brand-kicker">

          QUANTITATIVE MARKET INTELLIGENCE

        </div>


        <h2>

          Signal.
          Translate.
          Decide.

        </h2>


        <p>

          V13 Ideal como núcleo cuantitativo,
          BYMA como capa de traducción local,
          mercado regular como contexto operativo
          y tu cartera como ledger independiente.

        </p>


        <div class="alpha-brand-system">

          <div>

            <span>
              AUTHORITY
            </span>

            <strong>
              ${esc(
                state.system
                ?.authority
                || "—"
              )}
            </strong>

          </div>


          <div>

            <span>
              AS OF MODEL
            </span>

            <strong>
              ${esc(
                state.system
                ?.asof
                || "—"
              )}
            </strong>

          </div>


          <div>

            <span>
              HOLDOUT
            </span>

            <strong>
              ${esc(
                state.system
                ?.holdout_verdict
                || "—"
              )}
            </strong>

          </div>

        </div>

      </div>


      <img
        class="alpha-brand-image"
        src="/assets/alpha-engine-logo.jpg"
        alt=""
      >

    `;


    section.insertBefore(
      banner,
      section.firstChild
    );

  }


  // ========================================================
  // MARKET
  // ========================================================

  async function getMarkets(
    tickers
  ) {

    const url =
      (
        "/api/market-batch?tickers="
        +
        encodeURIComponent(
          tickers.join(
            ","
          )
        )
      );


    const result =
      await fetch(
        url,
        {
          cache:
            "no-store"
        }
      )
      .then(
        response =>
          response.json()
      );


    return (
      result.data
      || {}
    );

  }


  function marketCard(
    ticker,
    label,
    data
  ) {

    if (
      !data
      ||
      data.status
      !== "PASS"
    ) {

      return `

        <div class="alpha-market-card">

          <div class="alpha-market-symbol">

            ${esc(label)}

          </div>

          <div class="alpha-market-price">

            —

          </div>

          <div class="alpha-market-change flat">

            DATA UNAVAILABLE

          </div>

        </div>

      `;

    }


    const changeClass =
      marketChangeClass(
        data.change_pct
      );


    const currency =
      data.currency
      || "USD";


    return `

      <div
        class="alpha-market-card ticker"
        data-ticker="${esc(ticker)}"
      >

        <div class="alpha-market-symbol">

          ${esc(label)}
          ·
          ${esc(ticker)}

        </div>


        <div class="alpha-market-price">

          ${money(
            data.regular_market_price,
            currency
          )}

        </div>


        <div class="alpha-market-change ${changeClass}">

          ${
            numberValue(
              data.change_pct
            ) !== null
              ?
              (
                (
                  data.change_pct
                  >= 0
                    ? "+"
                    : ""
                )
                +
                pct(
                  data.change_pct
                )
              )
              :
              "—"
          }

        </div>


        <div class="alpha-market-source">

          Regular session
          ·
          ${esc(
            data.exchange
            || ""
          )}

        </div>

      </div>

    `;

  }


  async function installMarketTape(
    state
  ) {

    const overview =
      document.getElementById(
        "section-overview"
      );


    if (
      !overview
    ) {

      return;

    }


    const old =
      document.getElementById(
        "alpha-market-strip"
      );


    if (
      old
    ) {

      old.remove();

    }


    const wrapper =
      document.createElement(
        "div"
      );


    wrapper.id =
      "alpha-market-strip";


    wrapper.className =
      "alpha-market-strip panel";


    wrapper.innerHTML = `

      <div class="alpha-market-header">

        <div>

          <div class="eyebrow">

            LIVE REGULAR MARKET

          </div>

          <h3>

            Market Pulse

          </h3>

        </div>


        <small>

          Yahoo Finance
          ·
          regular session only
          ·
          no pre/post

        </small>

      </div>


      <div
        id="alpha-market-grid"
        class="alpha-market-grid"
      >

        ${BENCHMARKS
          .map(
            item => `
              <div class="alpha-market-card">

                <div class="alpha-market-symbol">

                  ${esc(
                    item.label
                  )}

                </div>

                <div class="alpha-market-price">

                  …

                </div>

              </div>
            `
          )
          .join("")}

      </div>

    `;


    const banner =
      document.getElementById(
        "alpha-brand-banner"
      );


    banner.insertAdjacentElement(
      "afterend",
      wrapper
    );


    try {

      const markets =
        await getMarkets(
          BENCHMARKS.map(
            item =>
              item.ticker
          )
        );


      document
        .getElementById(
          "alpha-market-grid"
        )
        .innerHTML =
          BENCHMARKS
          .map(
            item =>
              marketCard(
                item.ticker,
                item.label,
                markets[
                  item.ticker
                ]
              )
          )
          .join("");

    } catch (
      error
    ) {

      console.error(
        error
      );

    }


    installMarketMonitorPage(
      state
    );

  }


  async function installMarketMonitorPage(
    state
  ) {

    const section =
      document.getElementById(
        "section-market"
      );


    if (
      !section
    ) {

      return;

    }


    const existing =
      document.getElementById(
        "alpha-market-monitor"
      );


    if (
      existing
    ) {

      existing.remove();

    }


    const recommendations =
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
        8
      );


    const tickers =
      recommendations
      .map(
        row =>
          row.ticker
      )
      .filter(
        Boolean
      );


    const monitor =
      document.createElement(
        "div"
      );


    monitor.id =
      "alpha-market-monitor";


    monitor.className =
      "alpha-monitor";


    monitor.innerHTML = `

      <div class="alpha-monitor-title">

        <div>

          <div class="eyebrow">

            V13 MARKET MONITOR

          </div>

          <h3>

            Leading model exposures

          </h3>

        </div>


        <small>

          Latest regular-market snapshot

        </small>

      </div>


      <div
        id="alpha-model-market-grid"
        class="alpha-market-grid"
      >

        ${tickers
          .map(
            ticker => `
              <div class="alpha-market-card">

                <div class="alpha-market-symbol">

                  ${esc(
                    ticker
                  )}

                </div>

                <div class="alpha-market-price">

                  …

                </div>

              </div>
            `
          )
          .join("")}

      </div>

    `;


    const heading =
      section.querySelector(
        ".section-heading"
      );


    if (
      heading
    ) {

      heading.insertAdjacentElement(
        "afterend",
        monitor
      );

    }


    if (
      tickers.length
      === 0
    ) {

      return;

    }


    try {

      const markets =
        await getMarkets(
          tickers
        );


      document
        .getElementById(
          "alpha-model-market-grid"
        )
        .innerHTML =
          tickers
          .map(
            ticker =>
              marketCard(
                ticker,
                ticker,
                markets[
                  ticker
                ]
              )
          )
          .join("");

    } catch (
      error
    ) {

      console.error(
        error
      );

    }

  }


  // ========================================================
  // TICKER INTELLIGENCE
  // ========================================================

  function installTickerModal() {

    if (
      document.getElementById(
        "ticker-modal-v3"
      )
    ) {

      return;

    }


    const backdrop =
      document.createElement(
        "div"
      );


    backdrop.id =
      "ticker-modal-v3";


    backdrop.className =
      "ticker-modal-backdrop";


    backdrop.innerHTML = `

      <div class="ticker-modal">

        <div class="ticker-modal-header">

          <div>

            <div class="eyebrow">

              ALPHA // TICKER INTELLIGENCE

            </div>

            <h2 id="ticker-v3-title">

              —

            </h2>

          </div>


          <button
            id="ticker-v3-close"
            class="ticker-close"
          >

            ×

          </button>

        </div>


        <div
          id="ticker-v3-body"
          class="ticker-modal-body"
        >

        </div>

      </div>

    `;


    document.body
      .appendChild(
        backdrop
      );


    document
      .getElementById(
        "ticker-v3-close"
      )
      .addEventListener(
        "click",
        () =>
          backdrop
          .classList
          .remove(
            "open"
          )
      );


    backdrop.addEventListener(
      "click",
      event => {

        if (
          event.target
          === backdrop
        ) {

          backdrop
          .classList
          .remove(
            "open"
          );

        }

      }
    );


    document.addEventListener(
      "click",
      event => {

        const target =
          event.target.closest(
            ".ticker"
          );


        if (
          !target
        ) {

          return;

        }


        const ticker =
          (
            target.dataset
            ?.ticker
            ||
            target.textContent
          )
          .trim()
          .toUpperCase();


        if (
          ticker
          &&
          ticker !== "—"
          &&
          ticker !== "N/D"
        ) {

          openTicker(
            ticker
          );

        }

      }
    );

  }


  function objectBlock(
    title,
    object
  ) {

    if (
      !object
      ||
      typeof object
      !== "object"
    ) {

      return `

        <div class="ticker-section">

          <h3>

            ${esc(title)}

          </h3>

          <span class="neutral">

            Data not available in this layer.

          </span>

        </div>

      `;

    }


    const entries =
      Object.entries(
        object
      )
      .filter(
        ([key, value]) =>
          !missing(
            value
          )
          &&
          key !==
          "sparkline"
      );


    if (
      entries.length
      === 0
    ) {

      return `

        <div class="ticker-section">

          <h3>

            ${esc(title)}

          </h3>

          <span class="neutral">

            Data not available in this layer.

          </span>

        </div>

      `;

    }


    return `

      <div class="ticker-section">

        <h3>

          ${esc(title)}

        </h3>


        <div class="ticker-kv-grid">

          ${entries
            .map(
              ([key, value]) => `

                <div class="ticker-kv">

                  <span>

                    ${esc(
                      humanKey(
                        key
                      )
                    )}

                  </span>

                  <strong>

                    ${esc(
                      smartValue(
                        key,
                        value
                      )
                    )}

                  </strong>

                </div>

              `
            )
            .join("")}

        </div>

      </div>

    `;

  }


  function marketBanner(
    market
  ) {

    if (
      !market
      ||
      market.status
      !== "PASS"
    ) {

      return `

        <div class="ticker-section">

          <h3>
            Live Market
          </h3>

          <span class="neutral">
            Market snapshot unavailable.
          </span>

        </div>

      `;

    }


    return `

      <div class="ticker-live-banner">

        <div class="ticker-live-primary">

          <span>

            REGULAR MARKET PRICE

          </span>

          <strong>

            ${money(
              market.regular_market_price,
              market.currency
            )}

          </strong>

          <div
            class="alpha-market-change ${
              marketChangeClass(
                market.change_pct
              )
            }"
          >

            ${
              numberValue(
                market.change_pct
              ) !== null
                ?
                (
                  (
                    market.change_pct >= 0
                    ? "+"
                    : ""
                  )
                  +
                  pct(
                    market.change_pct
                  )
                )
                :
                "—"
            }

          </div>

        </div>


        <div class="ticker-live-stat">

          <span>
            PREVIOUS CLOSE
          </span>

          <strong>

            ${money(
              market.previous_close,
              market.currency
            )}

          </strong>

        </div>


        <div class="ticker-live-stat">

          <span>
            52W HIGH
          </span>

          <strong>

            ${money(
              market.fifty_two_week_high,
              market.currency
            )}

          </strong>

        </div>


        <div class="ticker-live-stat">

          <span>
            52W LOW
          </span>

          <strong>

            ${money(
              market.fifty_two_week_low,
              market.currency
            )}

          </strong>

        </div>


        <div class="ticker-live-stat">

          <span>
            EXCHANGE
          </span>

          <strong>

            ${esc(
              market.exchange
              || "—"
            )}

          </strong>

        </div>

      </div>

    `;

  }


  async function openTicker(
    ticker
  ) {

    const modal =
      document.getElementById(
        "ticker-modal-v3"
      );


    const body =
      document.getElementById(
        "ticker-v3-body"
      );


    document
      .getElementById(
        "ticker-v3-title"
      )
      .textContent =
        ticker;


    body.innerHTML = `

      <div class="empty-state">

        Loading ${esc(ticker)}…

      </div>

    `;


    modal
      .classList
      .add(
        "open"
      );


    try {

      const response =
        await fetch(
          (
            "/api/ticker?ticker="
            +
            encodeURIComponent(
              ticker
            )
          ),
          {
            cache:
              "no-store"
          }
        );


      const data =
        await response.json();


      if (
        !response.ok
        ||
        data.status
        !== "PASS"
      ) {

        throw new Error(
          data.error
          ||
          `HTTP ${response.status}`
        );

      }


      body.innerHTML = `

        ${marketBanner(
          data.market
        )}


        <div class="ticker-coverage">

          ${Object.entries(
            data.coverage
            || {}
          )
          .map(
            ([key, value]) => `

              <span
                class="coverage-chip ${
                  value
                  ? "yes"
                  : ""
                }"
              >

                ${esc(
                  key.toUpperCase()
                )}
                ·
                ${
                  value
                    ? "YES"
                    : "NO"
                }

              </span>

            `
          )
          .join("")}

        </div>


        ${objectBlock(
          "V13 Ideal",
          data.v13
        )}


        ${objectBlock(
          "BYMA Translation",
          Array.isArray(
            data.byma
          )
          ?
          data.byma[0]
          :
          data.byma
        )}


        ${objectBlock(
          "Personal Position",
          data.personal
        )}


        ${objectBlock(
          "Fundamentals",
          data.fundamentals
        )}

      `;

    } catch (
      error
    ) {

      body.innerHTML = `

        <div class="error-box">

          ${esc(
            error.message
          )}

        </div>

      `;

    }

  }


  // ========================================================
  // ALPHA DECISION DESK
  // ========================================================

  async function installAlphaDesk() {

    const panel =
      document.querySelector(
        "#section-alpha .alpha-chat"
      );


    if (
      !panel
    ) {

      return;

    }


    let health = {};


    try {

      health =
        await fetch(
          "/api/health",
          {
            cache:
              "no-store"
          }
        )
        .then(
          response =>
            response.json()
        );

    } catch (_) {}


    const configured =
      health.alpha_configured
      === true;


    panel.innerHTML = `

      <div class="alpha-desk-header">

        <div class="alpha-desk-identity">

          <img
            class="alpha-desk-logo"
            src="/assets/alpha-engine-logo.jpg"
            alt=""
          >


          <div>

            <small>

              DECISION DESK

            </small>

            <h3>

              ALPHA // INTELLIGENCE

            </h3>

          </div>

        </div>


        <div
          class="status-pill ${
            configured
            ? "pass"
            : "pending"
          }"
        >

          ${
            configured
            ? "DESK LIVE"
            : "API KEY"
          }

        </div>

      </div>


      ${
        configured
        ?
        ""
        :
        `

          <div class="alpha-desk-note">

            Decision Desk installed.
            OPENAI_API_KEY is not configured
            on this machine yet.

          </div>

        `
      }


      <div
        id="alpha-desk-messages"
        class="alpha-desk-messages"
      >

        <div class="alpha-desk-message alpha">

Alpha Engine context loaded.

V13, BYMA, live regular market, risk, fundamentals and personal ledger are available according to current data coverage.

Model: ${esc(
          health.alpha_model
          || "—"
        )}

        </div>

      </div>


      <div class="prompt-examples">

        <span data-desk-query="Dame el briefing actual de V13 y las cinco exposiciones más fuertes.">

          V13 Brief

        </span>


        <span data-desk-query="¿Qué exposiciones de V13 tienen hoy traducción BYMA disponible?">

          BYMA Map

        </span>


        <span data-desk-query="Dame una lectura del mercado actual y cómo dialoga con las señales de V13.">

          Market Read

        </span>


        <span data-desk-query="Analizá mi cartera actual contra V13 y BYMA sin modificar el modelo.">

          Portfolio Review

        </span>

      </div>


      <div class="alpha-desk-input">

        <textarea
          id="alpha-desk-input"
          placeholder="Consultá al Decision Desk…"
        ></textarea>

        <button
          id="alpha-desk-send"
        >

          RUN

        </button>

      </div>

    `;


    const tools =
      document.querySelector(
        "#section-alpha .alpha-tools"
      );


    if (
      tools
    ) {

      tools.innerHTML = `

        <div class="panel-header">

          <div>

            <div class="eyebrow">

              ALPHA DOCTRINE

            </div>

            <h3>

              System Boundaries

            </h3>

          </div>

        </div>


        <div class="alpha-doctrine">

          <div class="alpha-doctrine-item">

            <strong>

              V13 IDEAL

            </strong>

            <span>

              Theoretical model authority.
              Never contaminated by personal holdings.

            </span>

          </div>


          <div class="alpha-doctrine-item">

            <strong>

              BYMA MODEL

            </strong>

            <span>

              Local implementation layer.
              Separate from V13 performance authority.

            </span>

          </div>


          <div class="alpha-doctrine-item">

            <strong>

              LIVE MARKET

            </strong>

            <span>

              Regular session data only.
              Pre/post-market excluded.

            </span>

          </div>


          <div class="alpha-doctrine-item">

            <strong>

              PERSONAL LEDGER

            </strong>

            <span>

              Human-confirmed portfolio accounting.

            </span>

          </div>


          <div class="alpha-doctrine-item">

            <strong>

              EXECUTION

            </strong>

            <span>

              No automatic broker orders.

            </span>

          </div>

        </div>

      `;

    }


    document
      .querySelectorAll(
        "[data-desk-query]"
      )
      .forEach(
        element => {

          element.style.cursor =
            "pointer";


          element.addEventListener(
            "click",
            () => {

              document
                .getElementById(
                  "alpha-desk-input"
                )
                .value =
                  element.dataset
                  .deskQuery;

            }
          );

        }
      );


    document
      .getElementById(
        "alpha-desk-send"
      )
      .addEventListener(
        "click",
        sendDeskQuery
      );


    document
      .getElementById(
        "alpha-desk-input"
      )
      .addEventListener(
        "keydown",
        event => {

          if (
            event.key
            === "Enter"
            &&
            !event.shiftKey
          ) {

            event.preventDefault();

            sendDeskQuery();

          }

        }
      );

  }


  function deskMessage(
    role,
    text
  ) {

    const messages =
      document.getElementById(
        "alpha-desk-messages"
      );


    const item =
      document.createElement(
        "div"
      );


    item.className =
      (
        "alpha-desk-message "
        +
        role
      );


    item.textContent =
      text;


    messages.appendChild(
      item
    );


    messages.scrollTop =
      messages.scrollHeight;


    return item;

  }


  async function sendDeskQuery() {

    const input =
      document.getElementById(
        "alpha-desk-input"
      );


    const button =
      document.getElementById(
        "alpha-desk-send"
      );


    const query =
      input.value
      .trim();


    if (
      !query
    ) {

      return;

    }


    deskMessage(
      "user",
      query
    );


    input.value =
      "";


    button.disabled =
      true;


    button.textContent =
      "RUNNING";


    const pending =
      deskMessage(
        "alpha",
        "Running Alpha Engine analysis…"
      );


    try {

      const response =
        await fetch(
          "/api/alpha",
          {
            method:
              "POST",

            headers: {
              "Content-Type":
                "application/json",
            },

            body:
              JSON.stringify({
                message:
                  query,

                history:
                  ALPHA_HISTORY,
              }),
          }
        );


      const result =
        await response.json();


      if (
        result.status
        === "NOT_CONFIGURED"
      ) {

        pending.textContent =
          result.answer;

        return;

      }


      if (
        !response.ok
        ||
        result.status
        !== "PASS"
      ) {

        throw new Error(
          result.error
          ||
          "ALPHA_DESK_FAIL"
        );

      }


      pending.textContent =
        result.answer;


      ALPHA_HISTORY.push({
        role:
          "user",

        content:
          query,
      });


      ALPHA_HISTORY.push({
        role:
          "assistant",

        content:
          result.answer,
      });


      ALPHA_HISTORY =
        ALPHA_HISTORY.slice(
          -10
        );


    } catch (
      error
    ) {

      pending.textContent =
        (
          "DESK ERROR: "
          +
          error.message
        );


    } finally {

      button.disabled =
        false;


      button.textContent =
        "RUN";

    }

  }


  // ========================================================
  // CLEAN OLD GENERIC UI
  // ========================================================

  function cleanNaNs() {

    const walker =
      document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_TEXT
      );


    while (
      walker.nextNode()
    ) {

      const node =
        walker.currentNode;


      const text =
        node.nodeValue
        .trim();


      if (
        [
          "nan",
          "NaN",
          "+nan",
          "-nan",
          "<NA>",
        ].includes(
          text
        )
      ) {

        node.nodeValue =
          "—";

      }

    }

  }


  // ========================================================
  // START
  // ========================================================

  async function start() {

    installBrand();

    installTickerModal();

    await installAlphaDesk();

    await loadV3State();

    cleanNaNs();


    new MutationObserver(
      cleanNaNs
    ).observe(
      document.body,
      {
        childList:
          true,

        subtree:
          true,
      }
    );

  }


  if (
    document.readyState
    === "loading"
  ) {

    document.addEventListener(
      "DOMContentLoaded",
      start
    );

  } else {

    start();

  }

})();
