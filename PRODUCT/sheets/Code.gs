/**
 * ALPHA ENGINE - Google Sheets bridge
 *
 * Does NOT overwrite LISTA or price formulas.
 * Writes model data only to a dedicated sheet: ALPHA_MODEL
 *
 * Configure once:
 *   setAlphaDataUrl("https://YOUR-DOMAIN/data/dashboard.json")
 */

const ALPHA_SHEET = 'ALPHA_MODEL';

function setAlphaDataUrl(url) {
  PropertiesService.getScriptProperties().setProperty('ALPHA_DATA_URL', String(url).trim());
}

function refreshAlphaModel() {
  const url = PropertiesService.getScriptProperties().getProperty('ALPHA_DATA_URL');
  if (!url) throw new Error('ALPHA_DATA_URL not set. Run setAlphaDataUrl("...") once.');

  const res = UrlFetchApp.fetch(url, {muteHttpExceptions: true});
  if (res.getResponseCode() !== 200) {
    throw new Error('Alpha data fetch failed: HTTP ' + res.getResponseCode());
  }
  const d = JSON.parse(res.getContentText());

  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName(ALPHA_SHEET);
  if (!sh) sh = ss.insertSheet(ALPHA_SHEET);

  sh.clearContents();

  const trackRows = [
    ['TRACK','CAGR','MAX_DRAWDOWN','NAV','ASOF'],
    ['V13_IDEAL', val_(d,'tracks.v13_ideal.cagr'), val_(d,'tracks.v13_ideal.max_drawdown'), val_(d,'tracks.v13_ideal.nav'), d.asof || ''],
    ['BYMA_TRANSFER', val_(d,'tracks.byma_transfer.cagr'), val_(d,'tracks.byma_transfer.max_drawdown'), val_(d,'tracks.byma_transfer.nav'), d.asof || ''],
    ['PERSONAL', val_(d,'tracks.personal.cagr'), val_(d,'tracks.personal.max_drawdown'), val_(d,'tracks.personal.nav'), d.asof || '']
  ];
  sh.getRange(1,1,trackRows.length,trackRows[0].length).setValues(trackRows);

  const target = d.byma_current_target || [];
  const header = ['TICKER','TARGET_WEIGHT','VEHICLE','BYMA_TICKER','QUANTITY','ACTUAL_WEIGHT','SIGNAL_DATE'];
  const rows = target.map(x => [
    x.ticker || '',
    Number(x.target_weight || 0),
    x.vehicle || '',
    x.byma_ticker || '',
    x.quantity === undefined ? '' : x.quantity,
    x.actual_weight === undefined ? '' : Number(x.actual_weight),
    x.signal_date || ''
  ]);
  const start = 7;
  sh.getRange(start,1,1,header.length).setValues([header]);
  if (rows.length) sh.getRange(start+1,1,rows.length,header.length).setValues(rows);

  sh.setFrozenRows(1);
  sh.autoResizeColumns(1, header.length);
}

function installAlphaHourlyTrigger() {
  deleteAlphaTriggers_();
  ScriptApp.newTrigger('refreshAlphaModel').timeBased().everyHours(1).create();
}

function deleteAlphaTriggers_() {
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'refreshAlphaModel')
    .forEach(t => ScriptApp.deleteTrigger(t));
}

function val_(obj,path) {
  return path.split('.').reduce((a,k) => a && a[k] !== undefined ? a[k] : '', obj);
}
