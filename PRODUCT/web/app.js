
const pct = x => (x === null || x === undefined || Number.isNaN(Number(x))) ? "—" : `${(Number(x)*100).toFixed(2)}%`;
const esc = s => String(s ?? "").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[m]));

async function main(){
  const r = await fetch("data/dashboard.json",{cache:"no-store"});
  if(!r.ok) throw new Error(`dashboard.json ${r.status}`);
  const d = await r.json();
  document.getElementById("asof").textContent = `As of ${d.asof ?? "—"}`;

  const tracks = [
    ["V13 Ideal", d.tracks?.v13_ideal, "International / reference"],
    ["BYMA Transfer", d.tracks?.byma_transfer, "Local / model"],
    ["Personal", d.tracks?.personal, "Actual / discretionary"],
  ];
  document.getElementById("cards").innerHTML = tracks.map(([name,x,note]) => `
    <article class="card">
      <p class="eyebrow">${esc(note)}</p>
      <h2>${esc(name)}</h2>
      <div class="metric">${pct(x?.cagr)}</div>
      <div class="small">CAGR · MaxDD ${pct(x?.max_drawdown)} · NAV ${x?.nav ?? "—"}</div>
    </article>`).join("");

  const rows = d.byma_current_target ?? [];
  document.getElementById("target-body").innerHTML = rows.map(x => `
    <tr>
      <td>${esc(x.ticker)}</td>
      <td>${pct(x.target_weight)}</td>
      <td>${esc(x.vehicle ?? "")}</td>
      <td>${esc(x.quantity ?? "")}</td>
    </tr>`).join("");
}
main().catch(e=>{
  document.body.insertAdjacentHTML("beforeend",`<pre style="padding:24px">${esc(e.message)}</pre>`);
});
