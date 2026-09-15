(() => {

  let alphaHistory = [];


  const missing = value => {

    if (
      value === null ||
      value === undefined ||
      value === ""
    ) {
      return true;
    }

    if (
      typeof value === "number" &&
      !Number.isFinite(value)
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
        "none",
        "null",
        "<na>",
      ].includes(
        value.trim().toLowerCase()
      );

    }

    return false;
  };


  const esc = value =>

    String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");


  function prettyKey(key) {

    return String(key)
      .replaceAll("_", " ")
      .replace(
        /\b\w/g,
        c => c.toUpperCase()
      );
  }


  function smartValue(
    key,
    value
  ) {

    if (missing(value)) {
      return "—";
    }


    if (
      typeof value === "boolean"
    ) {
      return value
        ? "YES"
        : "NO";
    }


    if (
      typeof value === "number"
    ) {

      const k =
        String(key)
          .toLowerCase();


      if (
        k.includes("weight") ||
        k.includes("alpha") ||
        k.includes("return") ||
        k.includes("cagr") ||
        k.includes("margin") ||
        k.includes("pnl_pct")
      ) {

        return (
          (
            value * 100
          ).toFixed(2)
          + "%"
        );

      }


      return new Intl
        .NumberFormat(
          "en-US",
          {
            maximumFractionDigits: 4,
          }
        )
        .format(value);

    }


    if (
      typeof value === "object"
    ) {

      return JSON.stringify(
        value
      );

    }


    return String(value);
  }


  // ========================================================
  // LOGO
  // ========================================================

  function installLogo() {

    const mark =
      document.querySelector(
        ".brand-mark"
      );


    if (mark) {

      mark.innerHTML = `
        <img
          src="/assets/alpha-engine-logo.jpg"
          class="brand-logo"
          alt="Alpha Engine"
        >
      `;

    }


    const favicon =
      document.createElement(
        "link"
      );

    favicon.rel = "icon";

    favicon.href =
      "/assets/alpha-engine-logo.jpg";

    document.head.appendChild(
      favicon
    );

  }


  // ========================================================
  // REMOVE NAN VISUALLY
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


      if (
        /^(\+|-)?nan$/i.test(
          node.nodeValue.trim()
        ) ||
        node.nodeValue.trim()
          === "<NA>"
      ) {

        node.nodeValue = "—";

      }

    }

  }


  // ========================================================
  // TICKER MODAL
  // ========================================================

  function installTickerModal() {

    const backdrop =
      document.createElement(
        "div"
      );


    backdrop.id =
      "ticker-modal-backdrop";

    backdrop.className =
      "ticker-modal-backdrop";


    backdrop.innerHTML = `

      <div class="ticker-modal">

        <div class="ticker-modal-header">

          <div>
            <div class="eyebrow">
              TICKER INTELLIGENCE
            </div>

            <h2 id="ticker-title">
              —
            </h2>
          </div>

          <button
            class="ticker-close"
            id="ticker-close"
          >
            ×
          </button>

        </div>

        <div
          id="ticker-body"
          class="ticker-modal-body"
        ></div>

      </div>

    `;


    document.body.appendChild(
      backdrop
    );


    document
      .getElementById(
        "ticker-close"
      )
      .addEventListener(
        "click",
        closeTicker
      );


    backdrop.addEventListener(
      "click",
      event => {

        if (
          event.target ===
          backdrop
        ) {

          closeTicker();

        }

      }
    );


    document.addEventListener(
      "click",
      event => {

        const cell =
          event.target.closest(
            ".ticker"
          );


        if (!cell) {
          return;
        }


        const ticker =
          cell.textContent
            .trim()
            .toUpperCase();


        if (
          ticker &&
          ticker !== "—" &&
          ticker !== "N/D"
        ) {

          openTicker(
            ticker
          );

        }

      }
    );

  }


  function closeTicker() {

    document
      .getElementById(
        "ticker-modal-backdrop"
      )
      .classList
      .remove("open");

  }


  function objectBlock(
    title,
    obj
  ) {

    if (
      !obj ||
      typeof obj !== "object"
    ) {

      return `
        <div class="ticker-section">

          <h3>
            ${esc(title)}
          </h3>

          <div class="neutral">
            Sin datos disponibles.
          </div>

        </div>
      `;

    }


    const entries =
      Object.entries(obj)
        .filter(
          ([, value]) =>
            !missing(value)
        );


    if (
      entries.length === 0
    ) {

      return `
        <div class="ticker-section">

          <h3>
            ${esc(title)}
          </h3>

          <div class="neutral">
            Sin datos disponibles.
          </div>

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
                      prettyKey(key)
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


  function matchesBlock(
    title,
    rows
  ) {

    if (
      !Array.isArray(rows) ||
      rows.length === 0
    ) {
      return "";
    }


    return `
      <div class="ticker-section">

        <h3>
          ${esc(title)}
        </h3>

        ${rows
          .slice(0, 10)
          .map(
            row => `
              <div
                class="ticker-kv"
                style="margin-bottom:8px"
              >

                <span>
                  ${esc(
                    row.path || ""
                  )}
                </span>

                <strong>
                  ${esc(
                    JSON.stringify(
                      row.data
                    )
                  )}
                </strong>

              </div>
            `
          )
          .join("")}

      </div>
    `;

  }


  async function openTicker(
    ticker
  ) {

    const modal =
      document.getElementById(
        "ticker-modal-backdrop"
      );


    const body =
      document.getElementById(
        "ticker-body"
      );


    document
      .getElementById(
        "ticker-title"
      )
      .textContent =
        ticker;


    body.innerHTML =
      `
      <div class="empty-state">
        Cargando ${esc(ticker)}…
      </div>
      `;


    modal
      .classList
      .add("open");


    try {

      const response =
        await fetch(
          (
            "/api/ticker?ticker="
            + encodeURIComponent(
                ticker
              )
          ),
          {
            cache: "no-store",
          }
        );


      const data =
        await response.json();


      if (
        !response.ok ||
        data.status !== "PASS"
      ) {

        throw new Error(
          data.error ||
          `HTTP ${response.status}`
        );

      }


      const coverage =
        data.coverage || {};


      body.innerHTML = `

        <div class="ticker-coverage">

          ${Object.entries(
            coverage
          )
          .map(
            ([key, value]) => `

              <span
                class="coverage-chip ${
                  value ? "yes" : ""
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
          "BYMA",
          (
            Array.isArray(
              data.byma
            )
            ? data.byma[0]
            : data.byma
          )
        )}


        ${objectBlock(
          "Mi Cartera",
          data.personal
        )}


        ${objectBlock(
          "Fundamentales",
          data.fundamentals
        )}


        ${matchesBlock(
          "Fundamentales · coincidencias",
          data.fundamental_matches
        )}


        ${matchesBlock(
          "Mercado · coincidencias",
          data.market_matches
        )}

      `;

    } catch (error) {

      body.innerHTML = `
        <div class="error-box">
          ${esc(error.message)}
        </div>
      `;

    }

  }


  // ========================================================
  // ALPHA AI
  // ========================================================

  async function installAlpha() {

    const panel =
      document.querySelector(
        "#section-alpha .alpha-chat"
      );


    if (!panel) {
      return;
    }


    let health = {};


    try {

      health =
        await fetch(
          "/api/health",
          {
            cache: "no-store",
          }
        )
        .then(
          r => r.json()
        );

    } catch (_) {}


    const configured =
      health.alpha_configured
      === true;


    panel.className =
      "panel alpha-chat alpha-v2-chat";


    panel.innerHTML = `

      ${
        configured
          ? ""
          : `
            <div class="alpha-config-note">
              Alpha AI ya está instalada.
              Falta configurar OPENAI_API_KEY
              en esta PC.
            </div>
          `
      }


      <div
        id="alpha-messages"
        class="alpha-v2-messages"
      >

        <div class="alpha-message assistant">
Alpha AI conectada al Alpha Product State.

Puedo leer V13, BYMA, cartera, mercado y fundamentales disponibles.

Modelo configurado: ${esc(
          health.alpha_model || "—"
        )}
        </div>

      </div>


      <div class="prompt-examples">

        <span data-alpha="¿Cuáles son las recomendaciones principales actuales de V13?">
          Top V13
        </span>

        <span data-alpha="¿Qué recomendaciones actuales tienen vehículo BYMA disponible?">
          BYMA
        </span>

        <span data-alpha="Analizá mi cartera actual.">
          Mi cartera
        </span>

        <span data-alpha="¿Qué información fundamental está disponible actualmente?">
          Fundamentales
        </span>

      </div>


      <div class="alpha-v2-input">

        <textarea
          id="alpha-input"
          placeholder="Preguntale a Alpha…"
        ></textarea>

        <button id="alpha-send">
          Enviar
        </button>

      </div>

    `;


    document
      .querySelectorAll(
        "[data-alpha]"
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
                  "alpha-input"
                )
                .value =
                  element.dataset.alpha;

            }
          );

        }
      );


    document
      .getElementById(
        "alpha-send"
      )
      .addEventListener(
        "click",
        sendAlpha
      );


    document
      .getElementById(
        "alpha-input"
      )
      .addEventListener(
        "keydown",
        event => {

          if (
            event.key === "Enter" &&
            !event.shiftKey
          ) {

            event.preventDefault();

            sendAlpha();

          }

        }
      );


    const pill =
      document.querySelector(
        "#section-alpha .status-pill"
      );


    if (pill) {

      pill.textContent =
        configured
          ? "AI LIVE"
          : "API KEY";


      pill.className =
        configured
          ? "status-pill pass"
          : "status-pill pending";

    }

  }


  function message(
    role,
    text
  ) {

    const container =
      document.getElementById(
        "alpha-messages"
      );


    const element =
      document.createElement(
        "div"
      );


    element.className =
      `alpha-message ${role}`;


    element.textContent =
      text;


    container.appendChild(
      element
    );


    container.scrollTop =
      container.scrollHeight;


    return element;

  }


  async function sendAlpha() {

    const input =
      document.getElementById(
        "alpha-input"
      );


    const send =
      document.getElementById(
        "alpha-send"
      );


    const text =
      input.value.trim();


    if (!text) {
      return;
    }


    message(
      "user",
      text
    );


    input.value = "";

    send.disabled = true;

    send.textContent =
      "Pensando…";


    const pending =
      message(
        "assistant",
        "Analizando Alpha Engine…"
      );


    try {

      const response =
        await fetch(
          "/api/alpha",
          {
            method: "POST",

            headers: {
              "Content-Type":
                "application/json",
            },

            body: JSON.stringify({
              message: text,
              history: alphaHistory,
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
        !response.ok ||
        result.status !== "PASS"
      ) {

        throw new Error(
          result.error ||
          "ALPHA_AI_FAIL"
        );

      }


      pending.textContent =
        result.answer;


      alphaHistory.push({
        role: "user",
        content: text,
      });


      alphaHistory.push({
        role: "assistant",
        content: result.answer,
      });


      alphaHistory =
        alphaHistory.slice(
          -10
        );


    } catch (error) {

      pending.textContent =
        (
          "ALPHA ERROR: "
          + error.message
        );


    } finally {

      send.disabled = false;

      send.textContent =
        "Enviar";

    }

  }


  // ========================================================
  // START
  // ========================================================

  function start() {

    installLogo();

    installTickerModal();

    installAlpha();

    cleanNaNs();


    new MutationObserver(
      cleanNaNs
    ).observe(
      document.body,
      {
        childList: true,
        subtree: true,
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
