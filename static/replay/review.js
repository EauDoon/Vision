'use strict';

const byId = id => document.getElementById(id);
const decisions = {
  matched: 'Matched', verified_zero: 'Verified zero', disagreement: 'Disagreement',
  incomplete: 'Incomplete', unavailable: 'Unavailable'
};
const kinds = {fixture: 'Constructed fixture', public_capture: 'Public capture', diagnostic: 'Diagnostic example'};
const fieldLabels = {
  log_index: 'Log index', tx_hash: 'Transaction', contract: 'Emitting contract',
  from_address: 'Sender', to_address: 'Recipient', raw_amount: 'Raw amount'
};
const tokens = {
  '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2': 'WETH',
  '0xae78736cd615f374d3085123a210448e74fc6393': 'rETH'
};
let packet;
let archiveBase;
let downloadUrl;

function element(tag, content, className) {
  const node = document.createElement(tag);
  if (content !== undefined) node.textContent = typeof content === 'object' ? JSON.stringify(content) : content;
  if (className) node.className = className;
  return node;
}

function fields(entries) {
  const dl = element('dl', undefined, 'fields');
  for (const [key, value] of entries) {
    const dd = element('dd');
    dd.append(element('code', value ?? 'Unavailable'));
    dl.append(element('dt', key), dd);
  }
  return dl;
}

function disclosure(title, node) {
  const details = element('details', undefined, 'disclosure');
  details.append(element('summary', title), node);
  return details;
}

function sourceOption(label, value) {
  return new Option(label, value);
}

function availableSources() {
  return packet.sources.filter(source => source.kind !== 'diagnostic' || byId('show-diagnostics').checked);
}

function setSourceOptions() {
  const input = byId('source-filter');
  const current = input.value;
  input.replaceChildren(sourceOption('All sources', ''),
    ...availableSources().map(source => sourceOption(source.label, source.id)));
  input.value = availableSources().some(source => source.id === current) ? current : '';
}

// The URL describes only the view. Never use its values to fetch data.
const viewKeys = ['block', 'source', 'state'];
function restoreView() {
  const query = new URLSearchParams(location.search);
  byId('show-diagnostics').checked = query.get('diagnostics') === '1';
  setSourceOptions();
  for (const key of viewKeys) {
    const select = byId(key + '-filter');
    const value = query.get(key);
    select.value = [...select.options].some(option => option.value === value) ? value : '';
  }
}

function saveView() {
  const url = new URL(location.href);
  for (const key of viewKeys) {
    const value = byId(key + '-filter').value;
    if (value) url.searchParams.set(key, value);
    else url.searchParams.delete(key);
  }
  if (byId('show-diagnostics').checked) url.searchParams.set('diagnostics', '1');
  else url.searchParams.delete('diagnostics');
  history.replaceState(history.state, '', url);
  renderResults();
}

function eventRow(row) {
  const card = element('div', undefined, 'event');
  if (!row || typeof row !== 'object' || !Number.isInteger(row.log_index) ||
      !['tx_hash', 'contract', 'from_address', 'to_address', 'raw_amount'].every(key => typeof row[key] === 'string')) {
    card.append(element('strong', 'Incomplete transfer tuple'), element('pre', JSON.stringify(row, null, 2)));
    return card;
  }
  const vault = packet.scope.address;
  const direction = row.to_address === vault && row.from_address === vault ? 'self-transfer'
    : row.to_address === vault ? 'in' : 'out';
  card.append(element('strong', 'Log ' + row.log_index + ' · ' + (tokens[row.contract] || 'Token') + ' ' + direction),
    fields(['raw_amount', 'tx_hash', 'contract', 'from_address', 'to_address'].map(key => [fieldLabels[key], row[key]])));
  return card;
}

function side(title, data) {
  const section = element('section', undefined, 'side');
  section.append(element('h4', title), fields([['Block hash', data?.block_hash], ['Count', data?.count]]));
  if (!Array.isArray(data?.rows)) {
    section.append(element('p', 'Row evidence unavailable.'));
    if (data?.rows != null) section.append(element('pre', JSON.stringify(data.rows, null, 2)));
  }
  else if (!data.rows.length) section.append(element('p', 'No rows recorded.'));
  else section.append(...data.rows.map(eventRow));
  return section;
}

function differenceView(block) {
  const diff = block.diff;
  const section = element('section', undefined, 'diff');
  section.append(element('h4', 'Event differences'));
  if (diff.block_hash_changed) section.append(element('p', 'The archive and observation identify different block hashes.'));
  for (const change of diff.changed) {
    const labels = change.fields.map(key => fieldLabels[key] || key).join(', ');
    section.append(element('strong', 'Log ' + change.log_index + ' · Changed fields: ' + labels));
    const values = [];
    for (const key of change.fields) {
      values.push(['Archive ' + (fieldLabels[key] || key).toLowerCase(), change.expected[key]],
        ['Observed ' + (fieldLabels[key] || key).toLowerCase(), change.observed[key]]);
    }
    section.append(fields(values));
  }
  for (const row of diff.missing) section.append(element('p', 'Missing from observation · Log ' + row.log_index), eventRow(row));
  for (const row of diff.extra) section.append(element('p', 'Extra in observation · Log ' + row.log_index), eventRow(row));
  return section;
}

function witnessView(observation) {
  const witness = observation?.witness;
  const section = element('section');
  section.append(element('h4', 'Replay witness'));
  if (!witness) {
    section.append(element('p', 'Witness unavailable.'));
    return section;
  }
  section.append(fields([
    ['Sender filter count', witness.filter_counts?.sender], ['Recipient filter count', witness.filter_counts?.recipient],
    ['Finalized height', witness.finalized_height], ['Final block header', witness.end_block_hash],
    ['Receipt witnesses', Array.isArray(witness.receipts) ? witness.receipts.length : null]
  ]), disclosure('Witness JSON', element('pre', JSON.stringify(witness, null, 2))));
  return section;
}

function observation(source, block) {
  const item = element('details', undefined, 'observation');
  item.dataset.block = block.block_number;
  item.dataset.source = source.id;
  item.dataset.state = block.decision;
  const summary = element('summary');
  const title = element('span', source.label, 'src-label');
  if (source.kind === 'public_capture') title.append(element('small', kinds[source.kind], 'source-kind'));
  const obs = block.observed;
  const count = Number.isSafeInteger(obs?.count) ? obs.count : 'unavailable';
  const partial = block.decision === 'incomplete' && typeof count === 'number' ? ' (partial)' : '';
  summary.append(title, element('span', 'Archive ' + (block.expected.count ?? 'unavailable') +
    ' · Observed ' + count + partial, 'summary-counts'),
    element('span', decisions[block.decision], 'badge ' + block.decision));
  const body = element('div', undefined, 'details-body');
  if (block.decision === 'verified_zero') {
    body.append(element('p', 'All ' + block.coverage.receipts_examined + ' archived receipts and ' +
      block.coverage.logs_examined + ' logs were examined. Both Vault filters completed, the final header matched, ' +
      'and neither side contained a qualifying transfer.', 'note'));
  } else if (block.decision === 'matched') {
    body.append(element('p', 'The block hash and every transfer field agree.', 'note'));
  }
  if (block.issues.length) {
    const issues = element('ul', undefined, 'issue-list');
    issues.append(...block.issues.map(issue => element('li', issue)));
    body.append(issues);
  }
  if (obs?.error_kind || block.decision === 'incomplete') {
    const attempted = obs?.attempted === true ? 'Yes' : obs?.attempted === false ? 'No' : null;
    body.append(fields([['Attempted', attempted], ['Stage', obs?.stage], ['Error kind', obs?.error_kind],
      ['Started at', obs?.started_at]]));
  }
  if (block.decision === 'disagreement') body.append(differenceView(block));
  const sides = element('div', undefined, 'side-grid');
  sides.append(side('Archive expectation', block.expected), side('Source observation', obs));
  body.append(sides, witnessView(obs));
  const sourceLink = element('a', 'Archived block ' + block.block_number.toLocaleString('en-US'));
  sourceLink.href = archiveBase + '/' + block.archive.path.split('/').map(encodeURIComponent).join('/');
  body.append(sourceLink, fields([['Archive file SHA-256', block.archive.sha256]]));
  item.append(summary, body);
  return item;
}

function renderResults() {
  const blockFilter = byId('block-filter').value;
  const sourceFilter = byId('source-filter').value;
  const stateFilter = byId('state-filter').value;
  const groups = new Map();
  let count = 0;
  for (const source of availableSources()) {
    if (sourceFilter && source.id !== sourceFilter) continue;
    for (const block of source.blocks) {
      if ((blockFilter && String(block.block_number) !== blockFilter) || (stateFilter && block.decision !== stateFilter)) continue;
      if (!groups.has(block.block_number)) groups.set(block.block_number, []);
      groups.get(block.block_number).push({source, block});
      count++;
    }
  }
  const result = document.createDocumentFragment();
  for (const number of packet.scope.blocks) {
    const rows = groups.get(number);
    if (!rows) continue;
    const section = element('section', undefined, 'block');
    const header = element('div', undefined, 'block-heading');
    const coverage = rows[0].block.coverage;
    header.append(element('h3', 'Block ' + number.toLocaleString('en-US')),
      element('p', 'Archive examined ' + coverage.receipts_examined + ' of ' + coverage.receipts +
        ' receipts · ' + coverage.logs_examined + ' of ' + coverage.logs + ' logs'));
    section.append(header, ...rows.map(({source, block}) => observation(source, block)));
    result.append(section);
  }
  byId('results').replaceChildren(result);
  byId('result-count').textContent = count + (count === 1 ? ' comparison' : ' comparisons');
  byId('diagnostic-note').hidden = !byId('show-diagnostics').checked;
  byId('empty').hidden = count !== 0;
}

function renderPacket(data, bytes, raw) {
  if (data?.schema !== 'vision/replay-compare@1' || !/^[0-9a-f]{64}$/.test(data.sha256) ||
      !Array.isArray(data.sources) || !Array.isArray(data.scope?.blocks) ||
      data.archive?.repository !== 'https://github.com/ethereum/portal-spec-tests' ||
      !/^[0-9a-f]{40}$/.test(data.archive.revision)) {
    throw new Error('Expected a Vision replay comparison packet (version 1).');
  }
  packet = data;
  archiveBase = packet.archive.repository + '/blob/' + packet.archive.revision;
  byId('vault').textContent = packet.scope.address;
  const instant = new Date(packet.capture.captured_at);
  if (Number.isNaN(instant.getTime())) throw new Error('The packet has no valid capture time.');
  byId('captured-at').dateTime = packet.capture.captured_at;
  byId('captured-at').textContent = instant.toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, ' UTC');
  const publicBlocks = packet.sources.filter(source => source.kind === 'public_capture').flatMap(source => source.blocks);
  const complete = publicBlocks.filter(block => ['matched', 'verified_zero', 'disagreement'].includes(block.decision));
  const attempted = publicBlocks.filter(block => block.observed?.attempted);
  byId('capture-summary').textContent = complete.length + ' of ' + publicBlocks.length +
    ' provider comparisons completed. ' + attempted.length + ' attempted during this capture.';
  byId('block-filter').replaceChildren(sourceOption('All blocks', ''),
    ...packet.scope.blocks.map(number => sourceOption(number.toLocaleString('en-US'), String(number))));
  byId('state-filter').replaceChildren(sourceOption('All decisions', ''),
    ...Object.entries(decisions).map(([key, label]) => sourceOption(label, key)));
  restoreView();
  byId('archive-link').href = packet.archive.repository + '/tree/' + packet.archive.revision;
  byId('license-link').href = archiveBase + '/LICENSE';
  byId('sources').replaceChildren(...packet.sources.map(source => {
    const entry = element('li');
    entry.append(element('strong', source.label + '. '), document.createTextNode(source.description));
    if (source.endpoint) entry.append(document.createTextNode(' '), element('code', source.endpoint));
    return entry;
  }));
  renderResults();
  byId('packet-digest').textContent = packet.sha256;
  byId('packet-json').textContent = raw;
  if (downloadUrl) URL.revokeObjectURL(downloadUrl);
  downloadUrl = URL.createObjectURL(new Blob([bytes], {type: 'application/json'}));
  byId('download-packet').href = downloadUrl;
  byId('capture').hidden = false;
  byId('report').hidden = false;
}

async function loadPacket() {
  const status = byId('load-status');
  byId('retry-packet').hidden = true;
  byId('report').hidden = true;
  byId('capture').hidden = true;
  status.textContent = 'Loading the reviewer packet…';
  try {
    const response = await fetch('./packet.json', {headers: {'Accept': 'application/json'}});
    if (!response.ok) throw new Error('Server returned HTTP ' + response.status + '.');
    const bytes = await response.arrayBuffer();
    const raw = new TextDecoder('utf-8', {fatal: true}).decode(bytes);
    renderPacket(JSON.parse(raw), bytes, raw);
    status.textContent = '';
  } catch (err) {
    status.textContent = 'Replay comparison unavailable. ' + err.message;
    byId('retry-packet').hidden = false;
  }
}

for (const key of viewKeys) byId(key + '-filter').addEventListener('change', saveView);
byId('show-diagnostics').addEventListener('change', () => { setSourceOptions(); saveView(); });
window.addEventListener('popstate', () => { if (packet) { restoreView(); renderResults(); } });
byId('retry-packet').addEventListener('click', loadPacket);
byId('reset-filters').addEventListener('click', () => {
  byId('block-filter').value = '';
  byId('source-filter').value = '';
  byId('state-filter').value = '';
  byId('show-diagnostics').checked = false;
  setSourceOptions();
  saveView();
  byId('block-filter').focus();
});
if (['localhost', '127.0.0.1'].includes(location.hostname) && ['/replay/', '/replay/index.html'].includes(location.pathname)) {
  byId('previous-report').href = '/#transfer-review';
} else if (location.pathname.startsWith('/Vision/')) {
  byId('previous-report').href = '/Vision/v1.2/';
}
loadPacket();

// A finite, decorative assembly sequence. It reads no packet data; moving the
// illustration never changes a filter, a record or a downloadable observation.
const motionButton = byId('replay-motion');
motionButton.hidden = false;
motionButton.addEventListener('click', () => {
  const instrument = byId('instrument');
  instrument.classList.remove('sequence');
  void instrument.offsetWidth;
  instrument.classList.add('sequence');
});
