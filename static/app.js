'use strict';
const $ = id => document.getElementById(id);
const state = {status:null, searchSerial:0, labelSerial:0, caseSerial:0, query:null, snapshot:null, sourceButton:null};
const text = (tag,value,className) => { const el=document.createElement(tag); el.textContent=value == null ? '—' : String(value); if(className) el.className=className; return el; };
const short = value => typeof value==='string' && value.length>23 ? value.slice(0,10)+'…'+value.slice(-8) : value || '—';
const display = value => typeof value==='object' ? JSON.stringify(value) : String(value ?? '—');
function notice(message,error=false){$('notice').hidden=false;$('notice').textContent=message;$('notice').classList.toggle('error',error);}
async function request(path,body){const options={headers:{'Accept':'application/json'}};if(body!==undefined){options.method='POST';options.headers['Content-Type']='application/json';options.body=JSON.stringify(body);}const response=await fetch(path,options);let data;try{data=await response.json();}catch{throw new Error('The server returned an unreadable response. Please try again.');}if(!response.ok)throw new Error(typeof data.error==='string'?data.error:typeof data.message==='string'?data.message:'Request failed ('+response.status+').');return data;}
async function busy(button, action) {
  if (button.disabled || button.getAttribute('aria-busy') === 'true') return;
  const label = button.textContent;
  button.setAttribute('aria-busy', 'true');
  button.setAttribute('aria-disabled', 'true');
  button.textContent = 'Working…';
  try { await action(); }
  catch (error) { notice(error.message, true); }
  finally {
    button.removeAttribute('aria-busy');
    button.removeAttribute('aria-disabled');
    button.textContent = label;
  }
}
function badge(dataset){const known=['synthetic','live','reference'].includes(dataset)?dataset:'unclassified';return text('span',known.toUpperCase(),'pill '+known);}
function amount(event){try{if(!/^\d+$/.test(String(event.raw_amount)))return 'Invalid amount';const raw=String(event.raw_amount);if(!Number.isInteger(event.decimals)||event.decimals<0||event.decimals>36)return raw+' raw units';const padded=raw.padStart(event.decimals+1,'0');const whole=event.decimals?padded.slice(0,-event.decimals):padded;const fraction=event.decimals?padded.slice(-event.decimals).replace(/0+$/,''):'';return whole+(fraction?'.'+fraction:'')+' '+(event.asset==='ETH'?'ETH':short(event.asset));}catch{return 'Unresolved';}}
function cell(value, className) {
  const el = text('td', value, className);
  el.setAttribute('role', 'cell');
  return el;
}

function sourceButton(event) {
  const button = text('button', 'Inspect record', 'record-button');
  button.title = event.tx_hash || '';
  button.type = 'button';
  button.setAttribute('aria-label', 'Inspect ' + (event.kind || 'transfer').replaceAll('_', ' ') +
    ' in block ' + event.block_number + ', transaction ' + event.tx_hash);
  button.setAttribute('aria-controls', 'record-detail');
  button.addEventListener('click', () => {
    state.sourceButton = button;
    $('source-summary').textContent = 'Source record · block ' + event.block_number;
    $('record-json').textContent = JSON.stringify(event, null, 2);
    $('record-detail').hidden = false;
    $('record-detail').open = true;
    $('source-summary').focus();
  });
  return button;
}

function transferRow(event) {
  const row = document.createElement('tr');
  row.setAttribute('role', 'row');
  const kind = {native_transfer:'ETH transfer', erc20_transfer:'ERC-20 transfer'}[event.kind] || event.kind || 'Transfer';
  const activity = cell(kind, 'activity');
  activity.append(text('small', event.timestamp || 'Time unavailable'), badge(event.dataset));
  const value = cell(amount(event), 'amount');
  if (event.decimals == null) value.append(text('small', 'Decimals unverified'));
  const route = cell('', 'route');
  for (const [label, address] of [['From', event.from_address], ['To', event.to_address]]) {
    const line = document.createElement('div');
    const code = text('code', short(address));
    code.title = address || '';
    line.append(text('span', label), code);
    route.append(line);
  }
  const evidence = cell('', 'evidence');
  evidence.append(sourceButton(event), text('small', 'Block ' + (event.block_number ?? '—')));
  row.append(activity, value, route, evidence);
  return row;
}

function clearLedger() {
  state.query = null;
  state.snapshot = null;
  $('source-mix').hidden = true;
  $('export-help').hidden = true;
  state.sourceButton = null;
  $('event-rows').replaceChildren();
  $('ledger-table').hidden = true;
  $('record-detail').hidden = true;
  $('record-detail').open = false;
  $('record-json').textContent = '';
  $('identifier-box').hidden = true;
  $('identifiers').replaceChildren();
  $('no-events').hidden = true;
  $('export-search').hidden = true;
  $('coverage').classList.remove('error');
}

function renderEvents(data, query) {
  state.query = query;
  state.snapshot = data;
  const events = data.events || [];
  const count = events.length;
  $('result-count').textContent = data.truncated ? 'First ' + count + ' matches' : count + (count === 1 ? ' record' : ' records');
  const context = query === state.status?.demo_address ? 'Results for the fictional sample address. '
    : query ? 'Results for “' + query + '”. ' : 'Latest indexed transfers. ';
  const sources = new Map();
  for (const event of events) {
    const source = {live:'live', synthetic:'fictional', reference:'reference'}[event.dataset] || 'unclassified';
    sources.set(source, (sources.get(source) || 0) + 1);
  }
  $('source-mix').textContent = Array.from(sources, ([source, total]) => total + ' ' + source).join(' · ');
  $('source-mix').hidden = !count;
  $('coverage').textContent = context + (data.coverage || 'Only locally indexed windows are searchable.');
  $('event-rows').replaceChildren(...events.map(transferRow));
  $('ledger-table').hidden = !count;
  if (!count) {
    $('no-events').hidden = false;
    $('no-events').textContent = query
      ? ((data.labels || []).length ? 'A label matches this search, but no transfers match in the local index.' : 'No matching transfers in the local index.') +
        ' Clear the search to see all indexed records, or try another address.'
      : 'The local index contains no transfers. Import a supported block window to add evidence.';
  }
  const identifiers = data.identifiers || [];
  $('identifier-box').hidden = !identifiers.length;
  for (const item of identifiers) $('identifiers').append(text('li', item.type + ': ' + item.value));
  $('export-search').hidden = false;
  updateExportAvailability();
}

async function search(query) {
  const serial = ++state.searchSerial;
  clearLedger();
  $('result-count').textContent = 'Searching…';
  $('coverage').textContent = 'Reading the local transfer index…';
  $('ledger-table').setAttribute('aria-busy', 'true');
  try {
    const data = await request('/api/search?q=' + encodeURIComponent(query));
    if (serial !== state.searchSerial) return;
    renderEvents(data, query);
  } catch (error) {
    if (serial !== state.searchSerial) return;
    $('result-count').textContent = 'Search unavailable';
    $('coverage').classList.add('error');
    $('coverage').textContent = error.message + ' Retry the search to load indexed evidence.';
  } finally {
    if (serial === state.searchSerial) $('ledger-table').removeAttribute('aria-busy');
  }
}

async function labels(query = '') {
  const serial = ++state.labelSerial;
  const list = $('label-list');
  const status = $('label-status');
  list.replaceChildren();
  list.setAttribute('aria-busy', 'true');
  status.classList.remove('error');
  status.textContent = 'Searching the label directory…';
  try {
    const data = await request('/api/search?q=' + encodeURIComponent(query));
    if (serial !== state.labelSerial) return;
    const matches = data.labels || [];
    status.textContent = matches.length ? matches.length + (matches.length === 1 ? ' label shown' : ' labels shown')
      : 'No matching labels in this directory. Try another name or address.';
    for (const label of matches) {
      const card = document.createElement('article');
      card.className = 'panel label-card';
      card.append(badge(label.dataset), text('h2', label.name), text('code', label.address),
        text('p', label.category || 'Unclassified'), text('p', 'Source: ' + (label.source || 'Not supplied')));
      const button = text('button', 'Inspect transfers', 'text-button');
      button.type = 'button';
      button.setAttribute('aria-label', 'Inspect transfers for ' + label.name);
      button.addEventListener('click', () => {
        $('query').value = label.address;
        $('crawl-address').value = label.address;
        location.hash = 'explore';
        search(label.address);
      });
      card.append(button);
      list.append(card);
    }
  } catch (error) {
    if (serial !== state.labelSerial) return;
    status.classList.add('error');
    status.textContent = 'Directory unavailable. ' + error.message + ' Retry the label search.';
  } finally {
    if (serial === state.labelSerial) list.removeAttribute('aria-busy');
  }
}

function metric(label,value,note){const el=document.createElement('div');el.append(text('span',label),text('strong',value),text('small',note));return el;}
async function loadCase(){const serial=++state.caseSerial;const data=await request('/api/case');if(serial!==state.caseSerial)return;const r=data.result||{};const currency=r.currency||'illustrative units';$('case-state').textContent=r.status||'Unresolved';$('case-summary').replaceChildren(metric('Reconstructed gains',r.totals?.realized_gains??'Blocked',currency+' · fictional FIFO example'),metric('Reconstructed income',r.totals?.income??'Blocked',currency+' · separate category'),metric('Gains difference',r.differences?.realized_gains??'Blocked','Reconstructed minus declared · not tax due'));$('case-facts').replaceChildren();const facts={'Case':r.case_id,'Rule pack':r.pack?`${r.pack.id} / ${r.pack.version}`:'—','Period':r.period?`${r.period.start} to ${r.period.end}`:'—','Income difference':r.differences?.income,'Evidence hash':r.evidence_hash};for(const [key,value]of Object.entries(facts))$('case-facts').append(text('dt',key),text('dd',display(value)));$('case-issues').replaceChildren();for(const issue of [...(Array.isArray(r.issues)?r.issues:[]),...(Array.isArray(r.limitations)?r.limitations:[])])$('case-issues').append(text('p',display(issue),'fine'));$('case-json').textContent=JSON.stringify(data,null,2);if(data.review){$('review-result').textContent=`Last review: ${data.review.decision} · ${data.review.at}\n${data.review.note}`;}else{$('review-result').textContent='No research review recorded yet.';}}
async function refreshStatus() {
  const status = await request('/api/status');
  state.status = status;
  $('version').textContent = 'VISION / ' + (status.version || 'V1.1');
  $('connection').textContent = status.rpc_configured ? 'Local index · RPC configured' : 'Local index · RPC not configured';
  for (const key of ['events', 'labels', 'crawls']) {
    $('count-' + key).textContent = Number.isInteger(status.counts?.[key]) ? String(status.counts[key]) : 'Unknown';
  }
  $('rpc-help').textContent = status.rpc_configured
    ? 'Imports use the server’s RPC provider. The provider receives the address you enter.'
    : 'Import unavailable. Configure VISION_RPC_URL on the server, restart it and reload this page. Local search is available.';
  $('crawl-button').disabled = !status.rpc_configured;
}

function changeView(event) {
  const wanted = location.hash.slice(1);
  const view = ['explore', 'labels', 'case', 'scope'].includes(wanted) ? wanted : 'explore';
  const section = $('view-' + view);
  document.querySelectorAll('.view').forEach(el => { el.hidden = el !== section; });
  document.querySelectorAll('[data-view]').forEach(el => {
    const active = el.dataset.view === view;
    el.classList.toggle('active', active);
    if (active) el.setAttribute('aria-current', 'page');
    else el.removeAttribute('aria-current');
  });
  const title = section.querySelector('h1');
  document.title = title.textContent + ' · Vision';
  if (event) {
    $('notice').hidden = true;
    title.focus();
  }
  if (view === 'labels') labels($('label-query').value.trim());
  if (view === 'case') loadCase().catch(error => {
    $('case-state').textContent = 'Unavailable';
    notice('Could not load the fictional case. ' + error.message, true);
  });
}

document.querySelector('.skip').addEventListener('click', event => {
  event.preventDefault();
  document.querySelector('.view:not([hidden]) h1').focus();
});
$('return-record').addEventListener('click', () => {
  $('record-detail').open = false;
  state.sourceButton?.focus();
});
$('jump-import').addEventListener('click', () => $('crawl-address').focus());
$('search-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.currentTarget.querySelector('button'), () => search($('query').value.trim()));
});
$('label-form').addEventListener('submit', event => {
  event.preventDefault();
  busy(event.currentTarget.querySelector('button'), () => labels($('label-query').value.trim()));
});
$('load-demo').addEventListener('click', event => busy(event.currentTarget, async () => {
  const serial = state.searchSerial;
  const input = $('query').value;
  if (!state.status) await refreshStatus();
  if (serial !== state.searchSerial || input !== $('query').value) return;
  const address = state.status.demo_address;
  if (!address) throw new Error('The server has not supplied a sample address.');
  $('query').value = address;
  await search(address);
}));
$('crawl-form').addEventListener('submit', event => {
  event.preventDefault();
  const button = $('crawl-button');
  const output = $('crawl-result');
  busy(button, async () => {
    const address = $('crawl-address').value.trim();
    const payload = {address, blocks:Number($('blocks').value)};
    const end = $('crawl-end').value.trim();
    output.hidden = false;
    output.classList.remove('error');
    output.textContent = 'Reading finalized blocks…';
    try {
      if (!/^0x[0-9a-fA-F]{40}$/.test(address)) throw new Error('Enter a complete 0x address with 40 hexadecimal characters.');
      if (end !== '') {
        if (!/^\d+$/.test(end) || !Number.isSafeInteger(Number(end))) throw new Error('End block must be a non-negative integer.');
        payload.end = Number(end);
      }
      const searchAtStart = state.searchSerial;
      const result = await request('/api/crawl', payload);
      output.textContent = 'Indexed ' + (result.events ?? 0) + ' events from blocks ' + result.from_block +
        '–' + result.to_block + '. ' + (result.coverage || 'Coverage applies to this window.');
      if (state.searchSerial === searchAtStart) {
        $('query').value = address;
        await search(address);
      }
    } catch (error) {
      output.classList.add('error');
      output.textContent = 'Import failed. ' + error.message;
      return;
    }
    await refreshStatus();
  });
});
$('review-form').addEventListener('submit',e=>{e.preventDefault();busy(e.submitter||e.currentTarget.querySelector('button[type=submit],button:not([type])'),async()=>{const note=$('review-note').value.trim();if(!note)throw new Error('Add a review reason before saving.');const data=await request('/api/review',{decision:$('decision').value,note});$('review-result').textContent=`Saved: ${data.decision} · ${data.at}`;notice('Research review recorded. No enforcement action was taken.');await loadCase();});});
async function downloadResponse(path) {
  const response = await fetch(path, {headers:{'Accept':'application/json'}});
  if (!response.ok) {
    let message = 'Evidence export failed (' + response.status + ').';
    try { const error = await response.json(); if (typeof error.error === 'string') message = error.error; }
    catch { /* Keep the HTTP status if the server did not send JSON. */ }
    throw new Error(message);
  }
  return response;
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function download(path, filename) {
  const response = await downloadResponse(path);
  saveBlob(await response.blob(), filename);
}

function updateExportAvailability() {
  if (state.query === null) return;
  const edited = $('query').value.trim() !== state.query;
  $('export-search').disabled = !state.snapshot || edited;
  const help = $('export-help');
  help.hidden = false;
  if (!state.snapshot) help.textContent = 'The index changed. Run the search again to review the latest evidence before exporting.';
  else if (edited) help.textContent = 'Search with the edited query before exporting.';
  else help.hidden = true;
}
$('query').addEventListener('input', updateExportAvailability);
$('export').addEventListener('click',e=>busy(e.currentTarget,async()=>{await download('/api/evidence','vision-synthetic-case-evidence.json');notice('Synthetic case evidence downloaded. This is not a tax assessment.');}));
$('export-search').addEventListener('click', event => busy(event.currentTarget, async () => {
  const serial = state.searchSerial;
  const query = state.query;
  if (!state.snapshot || query !== $('query').value.trim()) return;
  try {
    const response = await downloadResponse('/api/search-export?q=' + encodeURIComponent(query));
    const body = await response.text();
    const evidence = JSON.parse(body);
    if (serial !== state.searchSerial || query !== $('query').value.trim()) return;
    // Both snapshots come from the same canonical JSON encoder in the local API.
    if (evidence.query !== query || JSON.stringify(evidence.snapshot) !== JSON.stringify(state.snapshot)) {
      state.snapshot = null;
      updateExportAvailability();
      return;
    }
    saveBlob(new Blob([body], {type:'application/json'}), 'vision-indexed-evidence.json');
    $('export-help').hidden = false;
    $('export-help').textContent = 'Indexed evidence downloaded with its available coverage.';
  } catch (error) {
    if (serial !== state.searchSerial) return;
    $('export-help').hidden = false;
    $('export-help').textContent = 'Export unavailable. ' + error.message;
  }
}));
window.addEventListener('hashchange', changeView);
changeView();
search('');
refreshStatus().catch(() => {
  $('connection').textContent = 'Index status unavailable';
  $('rpc-help').textContent = 'Could not check the RPC configuration. Reload to check import availability.';
  for (const key of ['events', 'labels', 'crawls']) $('count-' + key).textContent = 'Unknown';
});

$('simulate-form').addEventListener('submit',e=>{e.preventDefault();busy(e.submitter||e.currentTarget.querySelector('button[type=submit],button:not([type])'),async()=>{const realized_gains=$('simulate-gains').value.trim(),income=$('simulate-income').value.trim();if(!/^-?\d+(\.\d+)?$/.test(realized_gains)||!/^\d+(\.\d+)?$/.test(income))throw new Error('Enter decimal amounts. Income cannot be negative.');const data=await request('/api/simulate',{realized_gains,income});const result=data.result||{};const target=$('simulate-result');target.replaceChildren();target.hidden=false;target.append(badge('synthetic'),text('h3','Preview only · not saved'));if(result.status==='blocked'){target.append(text('p','Calculation blocked. '+(result.issues||[]).map(display).join(' ')));}else{target.append(text('p','Gains difference: '+(result.differences?.realized_gains??'Unresolved')+' '+(result.currency||'')+' · Income difference: '+(result.differences?.income??'Unresolved')+' '+(result.currency||'')));}target.append(text('p','Baseline evidence export and review are unchanged. No tax liability is calculated.','fine'));});});
