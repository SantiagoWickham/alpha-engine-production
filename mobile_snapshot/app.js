(() => {
  "use strict";

  const $ = (s, root=document) => root.querySelector(s);
  const $$ = (s, root=document) => [...root.querySelectorAll(s)];
  const cache = { summary:null, market:[], pulse:[], marketJob:null, fund:[], v13:null, forwardJob:null, recommendations:null, perf:null, portfolio:null, ph:null };
  let fundPage = 0;
  const FUND_PAGE_SIZE = 55;

  function esc(v){return String(v ?? "—").replace(/[&<>"']/g, m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));}
  function num(v,d=2){const x=Number(v);return Number.isFinite(x)?x.toLocaleString("es-AR",{maximumFractionDigits:d,minimumFractionDigits:d}):"—";}
  function pct(v,d=2){const x=Number(v);return Number.isFinite(x)?`${(x*100).toFixed(d)}%`:"—";}
  function money(v,cur="USD"){const x=Number(v); if(!Number.isFinite(x)) return "—"; try{return new Intl.NumberFormat("es-AR",{style:"currency",currency:cur,maximumFractionDigits:2}).format(x);}catch{return `${cur} ${num(x)}`;}}
  function cls(v){const x=Number(v);return Number.isFinite(x)?(x>0?"positive":x<0?"negative":""):"";}
  function toast(msg, error=false){const el=$("#toast");el.textContent=msg;el.hidden=false;el.classList.toggle("error",error);clearTimeout(toast.t);toast.t=setTimeout(()=>el.hidden=true,4500);}
  async function api(path, opts={}){const r=await fetch(path,{cache:"no-store",...opts,headers:{"Content-Type":"application/json",...(opts.headers||{})}});let j;try{j=await r.json();}catch{throw new Error(`HTTP ${r.status}`);}if(!r.ok||j.status==="FAIL")throw new Error(j.error||j.message||`HTTP ${r.status}`);return j;}
  async function post(path,body={}){return api(path,{method:"POST",body:JSON.stringify(body)});}

  const titles={overview:["Alpha Engine","Signal. Translate. Decide."],forward:["Forward Control","V13 live shadow sellado"],recommendations:["Recomendaciones","Política económica V13 + rebalance personal"],market:["Mercado & Riesgo","Auto 5m · regular session only · Data Recovery V1"],fundamentals:["Fundamentales","Cobertura auditada y ratios clave"],portfolio:["Mi cartera real","Ledger manual autoritativo + P&L live"],performance:["Performance","OOS sellado + Forward NAV causal"]};
  function showView(name){$$('.view').forEach(v=>v.classList.toggle('active',v.id===`view-${name}`));$$('.nav-item').forEach(b=>b.classList.toggle('active',b.dataset.view===name));const t=titles[name]||titles.overview;$("#pageTitle").textContent=t[0];$("#pageSubtitle").textContent=t[1];history.replaceState(null,"",`#${name}`); if(name==="performance") requestAnimationFrame(renderPerfChart); if(name==="portfolio") requestAnimationFrame(renderPortfolioChart);}

  function kpi(label,value,sub="",valueClass=""){return `<div class="kpi"><div class="label">${esc(label)}</div><div class="value ${valueClass}">${value}</div><div class="sub">${esc(sub)}</div></div>`;}

  async function loadSummary(){cache.summary=await api('/api/v4/summary');$("#systemPill").textContent=`SYSTEM ${cache.summary.status}`;$("#llmPill").textContent="LLM PAUSED · MANUAL LEDGER";const s=cache.summary;$("#clockGrid").innerHTML=[['OOS sellado',s.v13.oos_last_date],['Live shadow',s.v13.latest_completed_session||'—'],['Mercado',String(s.market.asof||'—').slice(0,19).replace('T',' ')],['Cartera',`${s.portfolio.operations||0} operaciones`]].map(([a,b])=>`<div class="clock"><span>${esc(a)}</span><b>${esc(b)}</b></div>`).join('');$("#overviewKpis").innerHTML=[kpi('Holdout',esc(s.v13.holdout_verdict||'—'),'V13 Ideal'),kpi('Targets positivos',esc(s.v13.positive_targets??'—'),`${s.v13.entry_eligible??'—'} entry eligible`),kpi('Mercado',`${s.market.rows}/200`,'regular session'),kpi('Cartera V4',`${s.portfolio.positions} posiciones`,`${s.portfolio.operations} operaciones`) ].join('');}

  async function loadV13(){const [v,j]=await Promise.all([api('/api/v4/v13'),api('/api/v4/forward/job')]);cache.v13=v;cache.forwardJob=j;$("#forwardKpis").innerHTML=[kpi('Última sesión shadow',esc(v.latest_completed_session||'—'),`OOS cerró ${v.oos_last_date}`),kpi('Entry eligible',esc(v.entry_eligible??'—'),`${v.positive_targets??'—'} targets positivos`),kpi('Universo',esc(v.universe??'—'),`Coverage ${pct(v.market_coverage_latest,0)}`),kpi('Forward engine',esc(j.status||'IDLE'),j.stale?`pendiente → ${j.latest_completed_market_session||'—'}`:`al día · ${j.latest_completed_market_session||'—'}`)].join('');renderTargets(v.targets||[], '#forwardTargets', 18);renderTargets(v.top5||[], '#topExposureMini', 5);const dates=v.history_signal_dates||[];$("#forwardHistory").innerHTML=dates.length?`<div class="mini-table">${dates.slice().reverse().map((d,i)=>`<div class="mini-row"><b>${esc(d)}</b><span>persistido</span><span>${i===0?'<span class="tag">LATEST</span>':''}</span><span></span></div>`).join('')}</div>`:`<div class="empty">No hay historial legible.</div>`;$("#forwardIntegrity").innerHTML=[['Seal',String(v.seal_id||'—').slice(0,18)+'…'],['Tuning',v.tuning_performed?'DETECTED':'NO'],['Órdenes reales',v.real_orders_sent?'YES':'NO'],['Contrato rows',String(v.contract_history_rows??'—')],['Runner',v.refresh_runner_available?'AVAILABLE':'MISSING'],['Job',j.status||'IDLE'],['Modelo',j.current_model_session||'—'],['Mercado completo',j.latest_completed_market_session||'—']].map(([a,b])=>`<div><b>${esc(a)}</b><span>${esc(b)}</span></div>`).join('');}
  function renderTargets(rows, selector, limit){const target=$(selector);if(!rows.length){target.innerHTML='<div class="empty">Sin targets.</div>';return;}target.innerHTML=`<div class="mini-table">${rows.slice(0,limit).map(r=>`<div class="mini-row"><b>${esc(r.ticker)}</b><span>${esc(r.model_intent||'TARGET')}</span><span>${pct(r.target_weight)}</span><span>${r.entry_ok===true||String(r.entry_ok).toLowerCase()==='true'?'<span class="tag">ENTRY</span>':''}</span></div>`).join('')}</div>`;}

  async function loadMarket(){const [j,p,mj]=await Promise.all([api('/api/v4/market'),api('/api/v4/pulse'),api('/api/v4/market/job')]);cache.market=j.rows||[];cache.pulse=p.rows||[];cache.marketJob=mj;$("#marketMeta").textContent=`${cache.market.length} activos · regular session only`;const ma=$("#marketAutoMeta");if(ma){ma.textContent=`AUTO 5M · ${mj.market_state||'—'}${mj.last_pass_at?' · '+String(mj.last_pass_at).slice(11,19)+'Z':''}`;ma.classList.toggle('pill-warn',mj.status==='FAIL'||mj.status==='WARN');}renderMarket();renderPulse();}
  function renderPulse(){const rows=cache.pulse||[];$("#marketPulse").classList.remove('skeleton');$("#marketPulse").innerHTML=rows.map(r=>`<div class="pulse"><div class="name">${esc(r.name)} · ${esc(r.ticker)}</div><div class="price">${r.status==='PASS'?num(r.price,2):'—'}</div><div class="chg ${cls(r.var_1d)}">${r.status==='PASS'?pct(r.var_1d):esc(r.status||'FAIL')}</div></div>`).join('');}
  function renderMarket(){const q=($("#marketSearch").value||'').trim().toUpperCase();const rows=cache.market.filter(r=>!q||String(r.ticker||'').toUpperCase().includes(q)||String(r.market_symbol||'').toUpperCase().includes(q));$("#marketBody").innerHTML=rows.map(r=>`<tr><td>${esc(r.ticker)}</td><td>${num(r.price)}</td><td class="${cls(r.var_1d)}">${pct(r.var_1d)}</td><td class="${cls(r.ret_1m)}">${pct(r.ret_1m)}</td><td class="${cls(r.ret_3m)}">${pct(r.ret_3m)}</td><td class="${cls(r.ret_6m)}">${pct(r.ret_6m)}</td><td class="${cls(r.ret_12m)}">${pct(r.ret_12m)}</td><td>${num(r.rsi14,1)}</td><td>${pct(r.vol_20d)}</td><td>${num(r.beta_6m,2)}</td><td class="${cls(r.max_drawdown_1y)}">${pct(r.max_drawdown_1y)}</td><td>${esc(r.source||'—')}</td></tr>`).join('');}

  async function loadRecommendations(){
    cache.recommendations=await api('/api/v4/recommendations');
    const r=cache.recommendations, rows=r.rows||[];
    const active=rows.filter(x=>Number(x.model_target_weight)>0).length;
    const buys=rows.filter(x=>x.action==='COMPRAR').length;
    const sells=rows.filter(x=>x.action==='VENDER').length;
    $("#recommendationKpis").innerHTML=[
      kpi('Señal',esc(r.signal_date||'—'),'última sesión V13'),
      kpi('Targets positivos',String(active),r.portfolio_status||'—'),
      kpi('Comprar',String(buys),'se activa con cartera real'),
      kpi('Vender',String(sells),'sin órdenes automáticas')
    ].join('');
    $("#recommendationNote").innerHTML=`<b>${esc(r.portfolio_status||'—')}</b><span>${esc(r.message||'')}</span>${r.portfolio_equity!=null?`<span>Base económica: ${money(r.portfolio_equity,r.currency||'ARS')}</span>`:''}`;
    $("#recommendationBody").innerHTML=rows.map(x=>`<tr>
      <td><b>${esc(x.ticker)}</b></td>
      <td><span class="tag ${x.action==='COMPRAR'?'positive':x.action==='VENDER'?'negative':''}">${esc(x.action||x.model_change||'—')}</span></td>
      <td>${x.current_quantity==null?'—':num(x.current_quantity,0)}</td>
      <td>${x.target_quantity==null?'—':num(x.target_quantity,0)}</td>
      <td class="${cls(x.delta_quantity)}">${x.delta_quantity==null?'—':num(x.delta_quantity,0)}</td>
      <td>${pct(x.current_weight)}</td>
      <td>${pct(x.economic_target_weight)}</td>
      <td>${pct(x.model_target_weight)}</td>
      <td class="${cls(x.target_delta_weight)}">${pct(x.target_delta_weight)}</td>
      <td>${x.entry_ok?'<span class="tag">ENTRY</span>':'—'}</td>
      <td class="${cls(x.expected_active_total)}">${pct(x.expected_active_total)}</td>
      <td>${x.local_price==null?'—':money(x.local_price,r.currency||'USD')}</td>
      <td>${esc(x.execution_symbol||'—')}</td>
    </tr>`).join('');
  }

  async function loadFund(){const j=await api('/api/v4/fundamentals');cache.fund=j.rows||[];const sectors=[...new Set(cache.fund.map(r=>r.sector).filter(Boolean))].sort();$("#fundSector").innerHTML='<option value="">Todos los sectores</option>'+sectors.map(s=>`<option>${esc(s)}</option>`).join('');$("#fundMeta").textContent=`${cache.fund.length} compañías`;fundPage=0;renderFund();}
  function filteredFund(){const q=($("#fundSearch").value||'').trim().toLowerCase(), sec=$("#fundSector").value;return cache.fund.filter(r=>(!sec||r.sector===sec)&&(!q||[r.ticker,r.name,r.sector,r.industry].some(x=>String(x||'').toLowerCase().includes(q))));}
  function renderFund(){const all=filteredFund(),pages=Math.max(1,Math.ceil(all.length/FUND_PAGE_SIZE));fundPage=Math.min(fundPage,pages-1);const rows=all.slice(fundPage*FUND_PAGE_SIZE,(fundPage+1)*FUND_PAGE_SIZE);$("#fundBody").innerHTML=rows.map(r=>`<tr><td>${esc(r.ticker)}</td><td>${esc(r.name)}</td><td>${esc(r.sector)}</td><td>${num(r.price)}</td><td>${Number.isFinite(Number(r.market_cap))?num(Number(r.market_cap)/1e9,2)+'B':'—'}</td><td>${num(r.pe,1)}</td><td>${num(r.forward_pe,1)}</td><td>${pct(r.roe)}</td><td>${num(r.debt_to_equity,1)}</td><td>${pct(r.profit_margin)}</td><td>${pct(r.revenue_growth)}</td><td>${pct(r.fcf_yield)}</td><td>${esc(r.source)}</td></tr>`).join('');$("#fundPage").textContent=`${all.length} resultados · página ${fundPage+1}/${pages}`;$("#fundPrev").disabled=fundPage<=0;$("#fundNext").disabled=fundPage>=pages-1;}

  async function loadPortfolio(){cache.portfolio=await api('/api/v4/portfolio');renderPortfolio();try{cache.ph=await api('/api/v4/portfolio/history');renderPortfolioChart();}catch(e){toast(`Gráfico cartera: ${e.message}`,true);}}
  function renderPortfolio(){const p=cache.portfolio;const totals=p.totals_by_currency||{};const preferred=totals.ARS?'ARS':totals.USD?'USD':'ARS';$("#portfolioCurrency").value=preferred;const cards=[];for(const [cur,t] of Object.entries(totals)){cards.push(kpi(`Valor ${cur}`,money(t.market_value,cur),`Costo ${money(t.cost_basis,cur)}`),kpi(`P&L ${cur}`,money(t.total_pnl,cur),`Realizado ${money(t.realized_pnl,cur)}`,cls(t.total_pnl)));}while(cards.length<4)cards.push(kpi(cards.length===0?'Ledger':'Excel mirror',cards.length===0?`${p.operations_count} ops`:'ACTIVO',cards.length===0?'Manual / persistido':'AlphaEngine_Cartera_Real.xlsx'));$("#portfolioKpis").innerHTML=cards.slice(0,4).join('');$("#positionBody").innerHTML=(p.positions||[]).map(r=>`<tr><td>${esc(r.market)}</td><td>${esc(r.ticker)}</td><td>${esc(r.currency)}</td><td>${num(r.quantity,4)}</td><td>${money(r.avg_cost,r.currency)}</td><td>${money(r.live_price,r.currency)}</td><td>${money(r.market_value,r.currency)}</td><td class="${cls(r.unrealized_pnl)}">${money(r.unrealized_pnl,r.currency)}</td></tr>`).join('')||'<tr><td colspan="8" class="empty">Todavía no hay posiciones en el ledger V4. Cargá la operación original o un saldo inicial como COMPRA con su fecha y costo.</td></tr>';$("#operationBody").innerHTML=(p.operations||[]).map(o=>`<tr><td>${esc(String(o.date||'').replace('T',' ').slice(0,19))}</td><td>${esc(o.type)}</td><td>${esc(o.market)}</td><td>${esc(o.ticker)}</td><td>${num(o.quantity,4)}</td><td>${num(o.unit_price,2)}</td><td>${num(o.fees,2)}</td><td>${esc(o.currency)}</td><td>${esc(o.note)}</td><td><button class="text-btn delete-op" data-id="${esc(o.id)}">Eliminar</button></td></tr>`).join('')||'<tr><td colspan="10" class="empty">Sin operaciones manuales.</td></tr>';$("#portfolioFiles").textContent=`JSON + CSV + Excel persistidos en PRODUCT`;const l=p.legacy_snapshot||{};$("#legacyPortfolio").innerHTML=`<div class="fineprint">${esc(l.note||'')}</div><div class="table-wrap"><table><thead><tr><th>Ticker</th><th>Cantidad</th><th>Costo medio USD Eq.</th><th>Valor mercado USD Eq.</th><th>P&L snapshot</th></tr></thead><tbody>${(l.positions||[]).map(x=>`<tr><td>${esc(x.ticker)}</td><td>${num(x.quantity,4)}</td><td>${num(x.avg_cost_usd)}</td><td>${num(x.market_value_usd)}</td><td>${num(x.unrealized_pnl_usd)}</td></tr>`).join('')}</tbody></table></div>`;}

  async function loadPerf(){cache.perf=await api('/api/v4/performance');const f=cache.perf.forward_summary||{};const pill=$("#forwardNavPill");if(pill){pill.textContent=f.status==='PASS'?`FORWARD NAV ${f.latest_date||'—'} · ${pct(f.metrics?.total_return_since_2026_09_04_close)}`:`FORWARD NAV ${f.status||'—'}`;pill.classList.toggle('pill-warn',f.status!=='PASS');}renderPerfChart();renderOverviewChart();}

  function setupCanvas(canvas){const dpr=window.devicePixelRatio||1,rect=canvas.getBoundingClientRect();const w=Math.max(300,Math.round(rect.width*dpr)),h=Math.max(220,Math.round(parseFloat(getComputedStyle(canvas).height)*dpr));if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);return {ctx,w:rect.width,h:h/dpr};}
  function drawLineChart(canvas, series, opts={}){if(!canvas)return;const {ctx,w,h}=setupCanvas(canvas);ctx.clearRect(0,0,w,h);const pad={l:52,r:18,t:24,b:34};const rows=(series||[]).filter(r=>r.date&&Number.isFinite(Number(r.value))).sort((a,b)=>a.date.localeCompare(b.date));if(rows.length<2){ctx.fillStyle='#6f8790';ctx.font='12px sans-serif';ctx.fillText('Sin datos suficientes',pad.l,pad.t+24);return;}const from=opts.from||rows[0].date,to=opts.to||rows.at(-1).date;let vis=rows.filter(r=>r.date>=from&&r.date<=to);if(vis.length<2)vis=rows;const ys=vis.map(r=>Number(r.value)),yMin=Math.min(...ys),yMax=Math.max(...ys),yPad=Math.max(2,(yMax-yMin)*.09),lo=yMin-yPad,hi=yMax+yPad;const x=i=>pad.l+(i/(vis.length-1))*(w-pad.l-pad.r),y=v=>pad.t+(1-(v-lo)/(hi-lo))*(h-pad.t-pad.b);ctx.strokeStyle='rgba(90,139,145,.15)';ctx.lineWidth=1;ctx.fillStyle='#6e858e';ctx.font='9px sans-serif';for(let k=0;k<5;k++){const yy=pad.t+k*(h-pad.t-pad.b)/4,val=hi-k*(hi-lo)/4;ctx.beginPath();ctx.moveTo(pad.l,yy);ctx.lineTo(w-pad.r,yy);ctx.stroke();ctx.fillText(val.toFixed(0),6,yy+3);}const markers=opts.markers||[];for(const m of markers){const idx=vis.findIndex(r=>r.date>=m.date);if(idx>=0){const xx=x(idx);ctx.save();ctx.setLineDash([5,4]);ctx.strokeStyle='rgba(225,178,92,.48)';ctx.beginPath();ctx.moveTo(xx,pad.t);ctx.lineTo(xx,h-pad.b);ctx.stroke();ctx.restore();ctx.fillStyle='#d4b46f';ctx.font='8px sans-serif';ctx.fillText(m.label,Math.min(xx+5,w-110),pad.t+10);}}
    const grad=ctx.createLinearGradient(0,pad.t,0,h-pad.b);grad.addColorStop(0,'rgba(38,221,143,.23)');grad.addColorStop(1,'rgba(38,221,143,0)');ctx.beginPath();vis.forEach((r,i)=>{const xx=x(i),yy=y(Number(r.value));i?ctx.lineTo(xx,yy):ctx.moveTo(xx,yy);});ctx.lineTo(x(vis.length-1),h-pad.b);ctx.lineTo(x(0),h-pad.b);ctx.closePath();ctx.fillStyle=grad;ctx.fill();ctx.beginPath();vis.forEach((r,i)=>{const xx=x(i),yy=y(Number(r.value));i?ctx.lineTo(xx,yy):ctx.moveTo(xx,yy);});ctx.strokeStyle='#4fe3a2';ctx.lineWidth=1.8;ctx.stroke();ctx.fillStyle='#657c85';ctx.font='8px sans-serif';ctx.fillText(vis[0].date,pad.l,h-10);const end=vis.at(-1).date;ctx.fillText(end,w-pad.r-ctx.measureText(end).width,h-10);
    canvas._chart={rows:vis,x,y,pad,w,h,opts};
  }
  function bindInteractive(canvas){if(canvas.dataset.bound)return;canvas.dataset.bound='1';let drag=null;canvas.addEventListener('mousemove',e=>{const c=canvas._chart;if(!c)return;const rect=canvas.getBoundingClientRect(),mx=e.clientX-rect.left;const plotW=c.w-c.pad.l-c.pad.r;let i=Math.round((mx-c.pad.l)/plotW*(c.rows.length-1));i=Math.max(0,Math.min(c.rows.length-1,i));const r=c.rows[i];if(!r)return;canvas.title=`${r.date} · ${Number(r.value).toFixed(2)}`;if(drag){const dx=e.clientX-drag.x;if(Math.abs(dx)>20){drag.moved=true;}}});canvas.addEventListener('mousedown',e=>drag={x:e.clientX,moved:false});window.addEventListener('mouseup',()=>drag=null);canvas.addEventListener('wheel',e=>{if(!canvas._rangeSetter)return;e.preventDefault();canvas._rangeSetter(e.deltaY<0?'in':'out');},{passive:false});}
  function perfSeries(){const p=cache.perf||{};if((p.combined_20bps||[]).length)return p.combined_20bps;if((p.nav_history||[]).length){const rows=p.nav_history,numericKeys=Object.keys(rows[0]||{}).filter(k=>!['date','segment'].includes(k)&&rows.some(r=>Number.isFinite(Number(r[k]))));const preferred=numericKeys.find(k=>/v13/i.test(k))||numericKeys[0];if(preferred){const raw=rows.filter(r=>r.date&&Number.isFinite(Number(r[preferred])));if(raw.length){const base=Number(raw[0][preferred]);return raw.map(r=>({date:String(r.date).slice(0,10),value:100*Number(r[preferred])/base}));}}}return p.oos_20bps||[];}
  let perfRange={from:null,to:null};
  function renderPerfChart(){if(!cache.perf)return;const rows=perfSeries();if(!rows.length)return;const from=perfRange.from||rows[0].date,to=perfRange.to||rows.at(-1).date;drawLineChart($("#performanceChart"),rows,{from,to,markers:cache.perf.markers||[]});bindInteractive($("#performanceChart"));$("#performanceChart")._rangeSetter=(dir)=>{const dates=rows.map(r=>new Date(r.date+'T00:00:00Z'));let a=new Date(from+'T00:00:00Z'),b=new Date(to+'T00:00:00Z'),span=b-a,delta=span*.18;if(dir==='in'){a=new Date(+a+delta);b=new Date(+b-delta);}else{a=new Date(+a-delta);b=new Date(+b+delta);}a=new Date(Math.max(+a,+dates[0]));b=new Date(Math.min(+b,+dates.at(-1)));perfRange={from:a.toISOString().slice(0,10),to:b.toISOString().slice(0,10)};$("#perfFrom").value=perfRange.from;$("#perfTo").value=perfRange.to;renderPerfChart();};}
  function renderOverviewChart(){if(!cache.perf)return;drawLineChart($("#overviewChart"),perfSeries(),{markers:(cache.perf.markers||[]).slice(-1)});}
  function setPerfPreset(range){const rows=perfSeries();if(!rows.length)return;const last=rows.at(-1).date,ld=new Date(last+'T00:00:00Z');let first=rows[0].date;if(range==='LIVE')first='2026-09-04';if(range==='OOS')first='2025-01-02';if(range==='1Y'){const d=new Date(ld);d.setUTCFullYear(d.getUTCFullYear()-1);first=d.toISOString().slice(0,10);}if(range==='YTD')first=`${ld.getUTCFullYear()}-01-01`;perfRange={from:first,to:last};$("#perfFrom").value=first;$("#perfTo").value=last;renderPerfChart();}

  function renderPortfolioChart(){const c=$("#portfolioChart");if(!cache.ph){drawLineChart(c,[]);return;}const cur=$("#portfolioCurrency").value||'ARS';const rows=((cache.ph.series||{})[cur]||[]).map(r=>({date:r.date,value:Number(r.pnl)}));drawLineChart(c,rows,{markers:[]});$("#portfolioChartMeta").textContent=rows.length?`${cur} · P&L económico acumulado · desde ${rows[0].date}`:`${cur} · sin historial`;}

  async function globalReload(){try{$("#globalRefresh").disabled=true;await Promise.all([loadSummary(),loadV13(),loadRecommendations(),loadMarket(),loadFund(),loadPortfolio(),loadPerf()]);toast('Alpha Engine V4 actualizado');}catch(e){toast(e.message,true);}finally{$("#globalRefresh").disabled=false;}}

  function defaultDate(){const d=new Date();d.setMinutes(d.getMinutes()-d.getTimezoneOffset());$("#opDate").value=d.toISOString().slice(0,16);}
  function syncOpDefaults(){const m=$("#opMarket").value,t=$("#opTicker").value.trim().toUpperCase();$("#opCurrency").value=m==='BYMA'?'ARS':'USD';if(t&&!$("#opSymbol").value.trim())$("#opSymbol").value=m==='BYMA'?(t.endsWith('.BA')?t:t+'.BA'):t;}


  async function waitForwardJob(){
    const b=$("#refreshForward");
    for(let i=0;i<400;i++){
      const j=await api('/api/v4/forward/job');
      cache.forwardJob=j;
      b.textContent=j.status==='RUNNING'?`Forward en curso… ${j.current_model_session||'—'} → ${j.latest_completed_market_session||'—'}`:'Actualizar Forward';
      if(j.status==='PASS'){
        toast(`Forward actualizado · ${j.after_session||j.current_model_session||'PASS'}`);
        await loadV13(); await loadRecommendations(); await loadPerf(); await loadSummary(); b.disabled=false; return;
      }
      if(j.status==='FAIL'){
        toast(`Forward FAIL: ${j.error||'ver log'}`,true);
        await loadV13(); b.disabled=false; b.textContent='Reintentar Forward'; return;
      }
      if(j.status!=='RUNNING'){await loadV13(); b.disabled=false; b.textContent='Actualizar Forward'; return;}
      await new Promise(r=>setTimeout(r,3000));
    }
    b.disabled=false; b.textContent='Actualizar Forward'; toast('Forward sigue ejecutándose; podés navegar y volver a esta pestaña.',false);
  }

  function bind(){
    $("#nav").addEventListener('click',e=>{const b=e.target.closest('[data-view]');if(b)showView(b.dataset.view);});
    document.addEventListener('click',e=>{const b=e.target.closest('[data-jump]');if(b)showView(b.dataset.jump);});
    $("#globalRefresh").addEventListener('click',globalReload);
    $("#marketSearch").addEventListener('input',renderMarket);
    $("#fundSearch").addEventListener('input',()=>{fundPage=0;renderFund();});$("#fundSector").addEventListener('change',()=>{fundPage=0;renderFund();});$("#fundPrev").onclick=()=>{fundPage--;renderFund();};$("#fundNext").onclick=()=>{fundPage++;renderFund();};
    $("#refreshRecommendations").onclick=async()=>{const b=$("#refreshRecommendations");b.disabled=true;try{await loadRecommendations();toast('Recomendaciones actualizadas');}catch(e){toast(e.message,true);}finally{b.disabled=false;}};
    $("#refreshForward").onclick=async()=>{const b=$("#refreshForward");b.disabled=true;b.textContent='Iniciando…';try{const j=await post('/api/v4/forward/refresh',{force:false});if(j.status==='NOT_AVAILABLE'){toast(j.message,true);b.disabled=false;b.textContent='Actualizar Forward';}else if(j.status==='UP_TO_DATE'){toast(`Forward al día · ${j.job?.current_model_session||'—'}`);await loadV13();b.disabled=false;b.textContent='Actualizar Forward';}else{toast(`Forward ${j.status} · proceso en background`);await waitForwardJob();}}catch(e){toast(`Forward: ${e.message}`,true);b.disabled=false;b.textContent='Actualizar Forward';}};
    $("#refreshMarket").onclick=async()=>{const b=$("#refreshMarket");b.disabled=true;b.textContent='Refrescando…';try{const j=await post('/api/v4/market/refresh');toast(`Mercado ${j.status} · ${j.critical_rows||0}/${j.rows||0} precios válidos`);await loadMarket();await loadSummary();}catch(e){toast(e.message,true);}finally{b.disabled=false;b.textContent='Refrescar mercado';}};
    $("#opMarket").addEventListener('change',()=>{$("#opSymbol").value='';syncOpDefaults();});$("#opTicker").addEventListener('blur',syncOpDefaults);
    $("#quoteBtn").onclick=async()=>{try{syncOpDefaults();const m=$("#opMarket").value,t=$("#opTicker").value.trim().toUpperCase(),s=$("#opSymbol").value.trim().toUpperCase();const q=await api(`/api/v4/quote?market=${encodeURIComponent(m)}&ticker=${encodeURIComponent(t)}&symbol=${encodeURIComponent(s)}`);if(q.regular_market_price!=null)$("#opPrice").value=q.regular_market_price;toast(`${q.symbol}: ${q.regular_market_price} · regular session`);}catch(e){toast(e.message,true);}};
    $("#opForm").addEventListener('submit',async e=>{e.preventDefault();const payload={date:$("#opDate").value,type:$("#opType").value,market:$("#opMarket").value,currency:$("#opCurrency").value,ticker:$("#opTicker").value,market_symbol:$("#opSymbol").value,quantity:$("#opQty").value,unit_price:$("#opPrice").value,fees:$("#opFees").value,cash_amount:$("#opCash").value,note:$("#opNote").value};try{await post('/api/v4/portfolio/operation',payload);toast('Operación guardada en JSON + CSV + Excel');$("#opForm").reset();defaultDate();$("#opMarket").value='BYMA';$("#opCurrency").value='ARS';$("#opFees").value='0';$("#opCash").value='0';await loadPortfolio();await loadSummary();}catch(err){toast(err.message,true);}});
    $("#operationBody").addEventListener('click',async e=>{const b=e.target.closest('.delete-op');if(!b)return;if(!confirm('¿Eliminar esta operación del ledger V4?'))return;try{await post('/api/v4/portfolio/delete',{id:b.dataset.id});toast('Operación eliminada');await loadPortfolio();await loadSummary();}catch(err){toast(err.message,true);}});
    $("#portfolioCurrency").addEventListener('change',renderPortfolioChart);
    $$('.perf-range').forEach(b=>b.onclick=()=>setPerfPreset(b.dataset.range));$("#perfApply").onclick=()=>{perfRange={from:$("#perfFrom").value||null,to:$("#perfTo").value||null};renderPerfChart();};
    window.addEventListener('resize',()=>{renderOverviewChart();renderPerfChart();renderPortfolioChart();});
  }

  async function boot(){bind();defaultDate();showView(location.hash.replace('#','')||'overview');try{await globalReload();setPerfPreset('FULL');if(cache.forwardJob?.status==='RUNNING'){waitForwardJob();}}catch(e){toast(`Inicio: ${e.message}`,true);}setInterval(async()=>{if(document.hidden)return;const active=document.querySelector('.nav-item.active')?.dataset.view;try{if(active==='portfolio')await loadPortfolio();else if(active==='market'||active==='overview')await loadMarket();if(active==='forward')await loadV13();if(active==='recommendations')await loadRecommendations();if(active==='performance')await loadPerf();}catch(_){/* automatic refresh never breaks UI */}},60000);}
  document.addEventListener('DOMContentLoaded',boot);
})();
