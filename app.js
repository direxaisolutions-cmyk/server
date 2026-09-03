// ===== State =====
let activeMainTab = 'verify';
let activeSubTab = 'txn';
let currentResponseData = null;
let lastRequestId = null;
let sseSource = null;
let pollInterval = null;
let localHistory = JSON.parse(localStorage.getItem('vet_history') || '[]');

const BANK_NAMES = {
  cbe:'Commercial Bank of Ethiopia', amhara:'Amhara Bank', telebirr:'Telebirr',
  dashen:'Dashen Bank', awash:'Awash Bank', boa:'Bank of Abyssinia',
  zemen:'Zemen Bank', cbebirr:'CBE Birr', mpesa:'M-Pesa Ethiopia',
  siinqee:'Siinqee Bank', kaafi:'Kaafi Ebirr'
};

function getApiKey(){ return document.getElementById('apiKeyInput').value.trim(); }
function getEndpoint(path){ return '/api/' + path; }

// ===== Init =====
document.addEventListener('DOMContentLoaded', () => {
  renderLocalHistory();
  document.getElementById('toggleApiKey').addEventListener('click', () => {
    const inp = document.getElementById('apiKeyInput');
    inp.type = inp.type === 'password' ? 'text' : 'password';
  });
});

// ===== Main Tabs =====
function switchMainTab(tab){
  activeMainTab = tab;
  document.querySelectorAll('.main-tab').forEach((b,i) => {
    b.classList.toggle('active', b.textContent.toLowerCase().includes(tab));
  });
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  const panel = document.getElementById('panel-'+tab);
  if(panel) panel.classList.add('active');
}

// ===== Sub Tabs (Verify) =====
function switchSubTab(tab){
  activeSubTab = tab;
  document.getElementById('tabTxn').classList.toggle('active', tab==='txn');
  document.getElementById('tabUrl').classList.toggle('active', tab==='url');
  document.getElementById('txnFieldsGroup').style.display = tab==='txn' ? 'flex' : 'none';
  document.getElementById('urlFieldsGroup').style.display = tab==='url' ? 'flex' : 'none';
  document.getElementById('txnInput').required = tab==='txn';
  document.getElementById('urlInput').required = tab==='url';
}

// ===== Toast =====
function showToast(msg){
  const t = document.getElementById('toast');
  t.textContent = msg; t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 3500);
}

// ===== Loading =====
function setLoading(on){
  const btn = document.getElementById('btnSubmit');
  const txt = document.getElementById('btnText');
  const sp = document.getElementById('btnSpinner');
  btn.disabled = on;
  txt.textContent = on ? 'Verifying...' : '🚀 Verify Transaction Now';
  sp.style.display = on ? 'block' : 'none';
}

// ===== VERIFY =====
async function handleVerify(e){
  e.preventDefault();
  const apiKey = getApiKey();
  if(!apiKey){ showToast('Enter your API key first!'); return; }

  const bank = document.getElementById('bankSelect').value;
  const acc = document.getElementById('accountInput').value.trim();
  const waitMs = document.getElementById('waitMsInput').value || '5000';
  const idempKey = document.getElementById('idempotencyInput').value.trim();
  const whUrl = document.getElementById('webhookUrlInput').value.trim();

  const payload = { bank };
  if(activeSubTab === 'txn'){
    const txn = document.getElementById('txnInput').value.trim();
    if(!txn){ showToast('Enter a transaction reference!'); return; }
    payload.referenceNumber = txn;
  } else {
    const url = document.getElementById('urlInput').value.trim();
    if(!url){ showToast('Enter a receipt URL!'); return; }
    payload.receiptUrl = url;
  }
  if(acc){ payload.settlementAccount = acc; payload.accountSuffix = acc; }
  if(whUrl) payload.webhookUrl = whUrl;

  setLoading(true);
  const headers = { 'x-api-key': apiKey, 'Content-Type': 'application/json' };
  if(idempKey) headers['Idempotency-Key'] = idempKey;
  if(whUrl) headers['X-Webhook-Url'] = whUrl;

  try {
    const resp = await fetch(getEndpoint('verify') + '?waitMs=' + waitMs, {
      method: 'POST', headers, body: JSON.stringify(payload)
    });
    const data = await resp.json();
    currentResponseData = data;
    lastRequestId = data.requestId || null;

    if(resp.ok && data.success !== false){
      displayResult(data);
      saveLocal(data, payload);
      showToast(data.verification?.processingStatus === 'queued' ? 'Verification queued!' : 'Verification complete!');
    } else {
      handleApiError(data, resp.status);
    }
  } catch(err){
    showToast('Network error: ' + err.message);
    handleNetworkError(err);
  } finally { setLoading(false); }
}

// ===== Display Result =====
function displayResult(res){
  const card = document.getElementById('resultCard');
  card.style.display = 'block';

  const d = Array.isArray(res.data) && res.data.length ? res.data[0] : (res.data || {});
  const bankKey = d.bank || document.getElementById('bankSelect').value;

  document.getElementById('resBankName').textContent = d.bank_name || BANK_NAMES[bankKey] || 'Bank';
  document.getElementById('resBankIcon').textContent = (bankKey||'').toUpperCase().slice(0,3);
  document.getElementById('resTxnId').textContent = 'Ref: ' + (res.requestId || d.referenceNumber || d.transactionNumber || '—');

  // Status
  const isVerified = res.verification?.verified || d.verified || false;
  const pStatus = res.verification?.processingStatus;
  const badge = document.getElementById('resStatusBadge');

  if(pStatus === 'queued' || pStatus === 'running'){
    badge.className = 'status-badge pending'; badge.textContent = '⏳ ' + (pStatus||'Pending');
  } else if(res.duplicate){
    badge.className = 'status-badge duplicate'; badge.textContent = '⚠ Duplicate';
  } else if(!isVerified){
    badge.className = 'status-badge failed'; badge.textContent = '✕ Failed';
  } else {
    badge.className = 'status-badge verified'; badge.textContent = '✓ Verified';
  }

  // Amount
  const amt = d.amount != null ? Number(d.amount).toLocaleString('en-US',{minimumFractionDigits:2}) : '0.00';
  document.getElementById('resAmount').innerHTML = amt + ' <span>' + (d.currency||'ETB') + '</span>';

  // Details
  document.getElementById('resPayerName').textContent = d.senderName || d.payer_name || '—';
  document.getElementById('resPayerAcc').textContent = 'Acc: ' + (d.senderAccount || d.payer_account || '—');
  document.getElementById('resReceiverName').textContent = d.receiverName || d.receiver_name || '—';
  document.getElementById('resReceiverAcc').textContent = 'Acc: ' + (d.receiverAccount || d.receiver_account || '—');

  const ts = d.timestamp || d.transaction_date;
  document.getElementById('resDate').textContent = ts ? new Date(ts).toLocaleString('en-US',{dateStyle:'medium',timeStyle:'short'}) : '—';
  document.getElementById('resMethod').textContent = 'Method: Verify.ET API';
  document.getElementById('resDescription').textContent = d.description || 'No note';

  // Settlement match
  const sm = d.settlementAccountMatch;
  const smSec = document.getElementById('settlementMatchSection');
  if(sm){
    smSec.style.display = 'block';
    document.getElementById('settlementGrid').innerHTML = [
      di('Match', sm.matched ? '✓ Yes' : '✕ No'),
      di('Confidence', sm.matchConfidence || '—'),
      di('Type', sm.matchType || '—'),
      di('Reason', sm.reason || '—'),
      di('Receiver Acc', sm.receiverAccount || '—'),
      di('Matched Account', sm.matchedSettlementAccount || '—'),
    ].join('');
  } else { smSec.style.display = 'none'; }

  // Confirmation history
  const ch = d.confirmationHistory;
  const chSec = document.getElementById('confirmationSection');
  if(ch){
    chSec.style.display = 'block';
    document.getElementById('confirmationGrid').innerHTML = [
      di('First Confirmation', ch.isFirstConfirmation ? 'Yes ✓' : 'No'),
      di('Confirmed Before', ch.confirmedBefore ? 'Yes ⚠' : 'No'),
      di('Count', ch.confirmationCount || 0),
      di('First At', ch.firstConfirmedAt ? new Date(ch.firstConfirmedAt).toLocaleString() : '—'),
    ].join('');
  } else { chSec.style.display = 'none'; }

  // Queued section
  const qs = document.getElementById('queuedSection');
  if(pStatus === 'queued' || pStatus === 'running'){
    qs.style.display = 'block';
    document.getElementById('queuedMessage').textContent =
      'Request ID: ' + (res.requestId||'—') + (res.estimatedWaitMs ? ' • Est. wait: '+res.estimatedWaitMs+'ms' : '');
  } else { qs.style.display = 'none'; }

  document.getElementById('jsonBox').textContent = JSON.stringify(res, null, 2);
  card.scrollIntoView({ behavior:'smooth', block:'nearest' });
}

function di(label, value){
  return '<div class="detail-item"><div class="label">'+label+'</div><div class="value">'+value+'</div></div>';
}

function handleApiError(data, status){
  const card = document.getElementById('resultCard');
  card.style.display = 'block';
  const bankKey = document.getElementById('bankSelect').value;
  document.getElementById('resBankName').textContent = BANK_NAMES[bankKey]||'Bank';
  document.getElementById('resBankIcon').textContent = bankKey.toUpperCase().slice(0,3);
  const badge = document.getElementById('resStatusBadge');
  badge.className = 'status-badge failed';
  badge.textContent = '✕ Error ('+status+')';
  document.getElementById('resAmount').innerHTML = '0.00 <span>ETB</span>';
  document.getElementById('resTxnId').textContent = 'Status: '+status;
  document.getElementById('resPayerName').textContent = data.message||'Failed';
  document.getElementById('resPayerAcc').textContent = '';
  document.getElementById('settlementMatchSection').style.display = 'none';
  document.getElementById('confirmationSection').style.display = 'none';
  document.getElementById('queuedSection').style.display = 'none';
  document.getElementById('jsonBox').textContent = JSON.stringify(data, null, 2);
  showToast('Error: '+(data.message||'Request failed'));
}

function handleNetworkError(err){
  document.getElementById('resultCard').style.display = 'block';
  document.getElementById('resStatusBadge').className = 'status-badge failed';
  document.getElementById('resStatusBadge').textContent = '✕ Network Error';
  document.getElementById('resPayerName').textContent = err.message;
  document.getElementById('settlementMatchSection').style.display = 'none';
  document.getElementById('confirmationSection').style.display = 'none';
  document.getElementById('queuedSection').style.display = 'none';
}

// ===== STREAM (SSE) =====
function startStream(){
  const reqId = document.getElementById('streamRequestId').value.trim();
  if(!reqId){ showToast('Enter a Request ID'); return; }
  const apiKey = getApiKey();
  if(!apiKey){ showToast('Enter your API key!'); return; }

  stopStream();
  const container = document.getElementById('streamEventsContainer');
  const list = document.getElementById('streamEventsList');
  const statusDot = document.getElementById('streamStatusDot');
  container.style.display = 'block';
  list.innerHTML = '';
  statusDot.textContent = '● Connecting';
  statusDot.className = 'stream-status';
  document.getElementById('btnStopStream').style.display = 'block';

  // SSE requires GET – use EventSource via fetch workaround for custom headers
  const url = getEndpoint('verify/'+reqId+'/events');
  const es = new EventSource(url + '?apiKey=' + encodeURIComponent(apiKey));
  sseSource = es;

  // We'll use fetch-based SSE since EventSource doesn't support headers
  // Fall back to fetch streaming
  stopStream();
  fetchSSE(url, apiKey, list, statusDot);
}

async function fetchSSE(url, apiKey, list, statusDot){
  try {
    const resp = await fetch(url, {
      headers: { 'x-api-key': apiKey, 'Accept': 'text/event-stream' }
    });
    statusDot.textContent = '● Connected';
    statusDot.className = 'stream-status connected';
    document.getElementById('btnStopStream').style.display = 'block';

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    sseSource = { close: () => reader.cancel() };

    while(true){
      const {done, value} = await reader.read();
      if(done) break;
      buffer += decoder.decode(value, {stream:true});
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for(const line of lines){
        if(line.startsWith('event:')){
          const evType = line.replace('event:','').trim();
          addStreamEvent(list, evType, '');
        } else if(line.startsWith('data:')){
          const evData = line.replace('data:','').trim();
          addStreamEvent(list, 'data', evData);
          try {
            const parsed = JSON.parse(evData);
            if(parsed.processingStatus === 'completed' || parsed.processingStatus === 'failed'){
              statusDot.textContent = '● Complete';
            }
          } catch(e){}
        }
      }
    }
    statusDot.textContent = '● Stream ended';
  } catch(err){
    statusDot.textContent = '● Error';
    statusDot.className = 'stream-status error';
    addStreamEvent(list, 'error', err.message);
  }
}

function addStreamEvent(list, type, data){
  const div = document.createElement('div');
  div.className = 'stream-event' + (type==='done' ? ' done' : type==='error' ? ' error' : '');
  div.innerHTML = '<span class="stream-event-type">'+type+'</span> ' + (data||'');
  list.appendChild(div);
  list.scrollTop = list.scrollHeight;
}

function stopStream(){
  if(sseSource){ sseSource.close(); sseSource = null; }
  document.getElementById('btnStopStream').style.display = 'none';
}

function autoStreamFromResult(){
  if(!lastRequestId){ showToast('No request ID available'); return; }
  switchMainTab('stream');
  document.getElementById('streamRequestId').value = lastRequestId;
  startStream();
}

// ===== POLL =====
async function pollOnce(){
  const reqId = document.getElementById('pollRequestId').value.trim();
  if(!reqId){ showToast('Enter a Request ID'); return; }
  const apiKey = getApiKey();
  if(!apiKey){ showToast('Enter your API key!'); return; }

  const container = document.getElementById('pollResultContainer');
  container.style.display = 'block';
  container.innerHTML = '<div class="result-box">Polling...</div>';

  try {
    const resp = await fetch(getEndpoint('verify/'+reqId), {
      headers: { 'x-api-key': apiKey }
    });
    const data = await resp.json();
    container.innerHTML = '<div class="result-box">' + escHtml(JSON.stringify(data, null, 2)) + '</div>';

    const ps = data.data?.processingStatus;
    if(ps === 'completed' || ps === 'failed'){
      showToast('Status: ' + ps);
    }
  } catch(err){
    container.innerHTML = '<div class="result-box" style="color:var(--danger-text)">Error: '+escHtml(err.message)+'</div>';
  }
}

function startAutoPoll(){
  const reqId = document.getElementById('pollRequestId').value.trim();
  if(!reqId){ showToast('Enter a Request ID'); return; }
  document.getElementById('btnAutoPoll').style.display = 'none';
  document.getElementById('btnStopPoll').style.display = 'block';
  showToast('Auto-polling every 1.5s...');
  pollOnce();
  pollInterval = setInterval(async () => {
    await pollOnce();
    const container = document.getElementById('pollResultContainer');
    try {
      const text = container.querySelector('.result-box')?.textContent || '';
      const parsed = JSON.parse(text);
      if(parsed.data?.processingStatus === 'completed' || parsed.data?.processingStatus === 'failed'){
        stopAutoPoll();
        showToast('Polling complete: ' + parsed.data.processingStatus);
      }
    } catch(e){}
  }, 1500);
}

function stopAutoPoll(){
  if(pollInterval){ clearInterval(pollInterval); pollInterval = null; }
  document.getElementById('btnAutoPoll').style.display = 'block';
  document.getElementById('btnStopPoll').style.display = 'none';
}

function autoPollFromResult(){
  if(!lastRequestId){ showToast('No request ID available'); return; }
  switchMainTab('poll');
  document.getElementById('pollRequestId').value = lastRequestId;
  startAutoPoll();
}

// ===== HISTORY =====
async function fetchHistory(){
  const apiKey = getApiKey();
  if(!apiKey){ showToast('Enter your API key!'); return; }

  const params = new URLSearchParams();
  const bank = document.getElementById('histBank').value;
  const status = document.getElementById('histStatus').value;
  const limit = document.getElementById('histLimit').value;
  const offset = document.getElementById('histOffset').value;
  if(bank) params.set('bank', bank);
  if(status) params.set('status', status);
  if(limit) params.set('limit', limit);
  if(offset) params.set('offset', offset);

  const container = document.getElementById('historyResultContainer');
  container.style.display = 'block';
  container.innerHTML = '<div class="result-box">Loading history...</div>';

  try {
    const resp = await fetch(getEndpoint('verify/history') + '?' + params.toString(), {
      headers: { 'x-api-key': apiKey }
    });
    const data = await resp.json();

    if(data.success && Array.isArray(data.data) && data.data.length){
      let html = '<table class="history-table"><thead><tr><th>Request ID</th><th>Bank</th><th>Status</th><th>Verified</th><th>Duration</th><th>Date</th></tr></thead><tbody>';
      for(const item of data.data){
        html += '<tr>';
        html += '<td class="mono">' + (item.requestId||'—').slice(0,12) + '…</td>';
        html += '<td>' + (BANK_NAMES[item.bank]||item.bank||'—') + '</td>';
        html += '<td>' + (item.status||'—') + '</td>';
        html += '<td>' + (item.verified ? '✓' : '✕') + '</td>';
        html += '<td>' + (item.durationMs ? item.durationMs+'ms' : '—') + '</td>';
        html += '<td>' + (item.createdAt ? new Date(item.createdAt).toLocaleDateString() : '—') + '</td>';
        html += '</tr>';
      }
      html += '</tbody></table>';
      if(data.meta) html += '<div class="history-meta-info">Showing '+data.data.length+' of '+data.meta.total+' results</div>';
      container.innerHTML = html;
    } else {
      container.innerHTML = '<div class="result-box">' + escHtml(JSON.stringify(data, null, 2)) + '</div>';
    }
  } catch(err){
    container.innerHTML = '<div class="result-box" style="color:var(--danger-text)">Error: '+escHtml(err.message)+'</div>';
  }
}

// ===== WEBHOOK TEST =====
async function testWebhook(){
  const apiKey = getApiKey();
  if(!apiKey){ showToast('Enter your API key!'); return; }
  const whUrl = document.getElementById('testWebhookUrl').value.trim();
  if(!whUrl){ showToast('Enter a webhook URL!'); return; }
  const scenario = document.getElementById('webhookScenario').value;

  const container = document.getElementById('webhookResultContainer');
  container.style.display = 'block';
  container.innerHTML = '<div class="result-box">Sending test webhook...</div>';

  try {
    const resp = await fetch(getEndpoint('verify/test-webhook'), {
      method: 'POST',
      headers: { 'x-api-key': apiKey, 'Content-Type': 'application/json' },
      body: JSON.stringify({ webhookUrl: whUrl, scenario })
    });
    const data = await resp.json();
    container.innerHTML = '<div class="result-box">' + escHtml(JSON.stringify(data, null, 2)) + '</div>';
    showToast(resp.ok ? 'Test webhook sent!' : 'Webhook test failed');
  } catch(err){
    container.innerHTML = '<div class="result-box" style="color:var(--danger-text)">Error: '+escHtml(err.message)+'</div>';
  }
}

// ===== BANK STATUS =====
async function fetchStatus(){
  const container = document.getElementById('statusResultContainer');
  container.style.display = 'block';
  container.innerHTML = '<div class="result-box">Checking system status...</div>';

  const apiKey = getApiKey();
  const headers = apiKey ? { 'x-api-key': apiKey } : {};

  try {
    const resp = await fetch(getEndpoint('uptime'), { headers });
    const data = await resp.json();

    if(data.success && data.data){
      const items = Array.isArray(data.data) ? data.data : [data.data];
      let html = '<div class="status-grid">';
      for(const item of items){
        const isUp = item.status === 'up' || item.operational;
        html += '<div class="status-card '+(isUp?'up':'down')+'">';
        html += '<div class="status-name">'+(BANK_NAMES[item.bank]||item.name||item.bank||'System')+'</div>';
        html += '<div class="status-indicator">'+(isUp?'● Operational':'● Down')+'</div>';
        html += '</div>';
      }
      html += '</div>';
      container.innerHTML = html;
    } else {
      container.innerHTML = '<div class="result-box">' + escHtml(JSON.stringify(data, null, 2)) + '</div>';
    }
  } catch(err){
    container.innerHTML = '<div class="result-box" style="color:var(--danger-text)">Error: '+escHtml(err.message)+'</div>';
  }
}

// ===== JSON / Copy =====
function toggleJsonView(){
  const box = document.getElementById('jsonBox');
  box.style.display = box.style.display === 'block' ? 'none' : 'block';
}

function copyReceiptSummary(){
  if(!currentResponseData) return;
  const d = Array.isArray(currentResponseData.data)&&currentResponseData.data.length ? currentResponseData.data[0] : (currentResponseData.data||{});
  const summary = `Payment Verification Summary
Status: ${currentResponseData.verification?.verified ? 'Verified' : 'Unverified'}
Ref: ${currentResponseData.requestId||d.referenceNumber||'—'}
Amount: ${d.amount||0} ${d.currency||'ETB'}
Payer: ${d.senderName||'—'} (${d.senderAccount||'—'})
Receiver: ${d.receiverName||'—'} (${d.receiverAccount||'—'})
Date: ${d.timestamp||'—'}`;
  navigator.clipboard.writeText(summary).then(() => showToast('Copied!'));
}

// ===== Local History =====
function saveLocal(res, payload){
  const d = Array.isArray(res.data)&&res.data.length ? res.data[0] : (res.data||{});
  localHistory.unshift({
    id: d.referenceNumber||d.transactionNumber||res.requestId||'—',
    bank: (payload.bank||'').toUpperCase(),
    amount: d.amount||0, currency: d.currency||'ETB',
    date: new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}),
    fullData: res
  });
  if(localHistory.length > 15) localHistory.pop();
  localStorage.setItem('vet_history', JSON.stringify(localHistory));
  renderLocalHistory();
}

function renderLocalHistory(){
  const list = document.getElementById('localHistoryList');
  if(!localHistory.length){ list.innerHTML = '<div class="empty-state">No verifications yet.</div>'; return; }
  list.innerHTML = localHistory.map((it,i) =>
    `<div class="history-item" onclick="loadLocal(${i})">
      <div class="history-meta"><div class="history-id">${it.bank} — ${it.id}</div><div class="history-sub">${it.date}</div></div>
      <div class="history-amount">${Number(it.amount).toLocaleString()} ${it.currency}</div>
    </div>`
  ).join('');
}

function loadLocal(i){
  const item = localHistory[i];
  if(item?.fullData){ currentResponseData = item.fullData; displayResult(item.fullData); showToast('Loaded: '+item.id); }
}

function clearLocalHistory(){
  localHistory = []; localStorage.removeItem('vet_history');
  renderLocalHistory(); showToast('History cleared');
}

function escHtml(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
