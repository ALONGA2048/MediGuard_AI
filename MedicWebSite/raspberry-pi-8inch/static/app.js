'use strict';
const $ = (s) => document.querySelector(s);
const escapeHTML = (s) => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let catalog = [], cart = {}, mode = '自取', category = '全部', pendingRecord = null, submitting = false;
try { ({ cart = {}, mode = '自取', pendingRecord = null } = JSON.parse(localStorage.getItem('mg8-draft') || '{}')); } catch { /* damaged draft starts empty */ }
function persist() { try { localStorage.setItem('mg8-draft', JSON.stringify({cart, mode, pendingRecord})); } catch { toast('瀏覽器無法保存草稿，請勿重新整理'); } }
let toastTimer;
function toast(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').hidden = true, 5000); }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '服務未就緒');
  return result;
}
function renderCatalog() {
  const query = $('#search').value.trim().toLowerCase();
  const items = catalog.filter(p => (category === '全部' || p.category === category) && p.name.toLowerCase().includes(query));
  $('#catalog').innerHTML = items.map(p => `<button class="product" data-add="${escapeHTML(p.id)}" aria-label="加入 ${escapeHTML(p.name)}"><div class="product-art ${['mint','blue','peach','lilac'].includes(p.color)?p.color:'mint'}"><span>${escapeHTML(p.symbol)}</span></div><div class="product-copy"><h3>${escapeHTML(p.name)}</h3><p>${escapeHTML(p.description)}</p><div class="product-bottom"><span>每${escapeHTML(p.unit)}</span><span class="add-icon">＋</span></div></div>${cart[p.id]?`<span class="badge">${cart[p.id]}</span>`:''}</button>`).join('') || '<p>沒有符合的品項。</p>';
}
function renderCart() {
  const items = catalog.filter(p => cart[p.id]);
  $('#line-count').textContent = items.length;
  const total = items.reduce((n,p) => n + cart[p.id], 0);
  $('#quantity').textContent = `${total} 件`;
  $('#submit').disabled = !total || submitting;
  $('#clear').disabled = !total || submitting;
  $('#cart').innerHTML = items.length ? items.map(p => `<div class="cart-row"><h3>${escapeHTML(p.name)}</h3><div class="counter"><span class="unit">單位：${escapeHTML(p.unit)}</span><div class="counter-controls"><button data-adjust="${escapeHTML(p.id)}" data-delta="-1" aria-label="減少 ${escapeHTML(p.name)}">−</button><strong>${cart[p.id]}</strong><button data-adjust="${escapeHTML(p.id)}" data-delta="1" aria-label="增加 ${escapeHTML(p.name)}">＋</button></div></div></div>`).join('') : '<div class="empty"><span class="empty-icon">▧</span><b>清單還是空的</b><p>從左側選擇需要的品項<br>開始準備這次交付</p></div>';
  document.querySelectorAll('[data-mode]').forEach(b => b.classList.toggle('selected', b.dataset.mode === mode));
}
function change(id, delta) {
  if (submitting || pendingRecord) return toast('請先完成或重試目前送出的清單');
  const quantity = (cart[id] || 0) + delta;
  if (quantity > 99) return toast('單項最多 99 件');
  if (quantity <= 0) delete cart[id]; else cart[id] = quantity;
  persist(); renderCatalog(); renderCart();
}
$('#catalog').addEventListener('click', e => { const b = e.target.closest('[data-add]'); if (b) change(b.dataset.add,1); });
$('#cart').addEventListener('click', e => { const b = e.target.closest('[data-adjust]'); if (b) change(b.dataset.adjust,Number(b.dataset.delta)); });
$('#search').addEventListener('input', renderCatalog);
$('#filters').addEventListener('click', e => { const b = e.target.closest('[data-category]'); if (!b) return; category = b.dataset.category; document.querySelectorAll('[data-category]').forEach(el => el.classList.toggle('selected',el === b)); renderCatalog(); });
document.querySelectorAll('[data-mode]').forEach(b => b.addEventListener('click', () => { if (pendingRecord || submitting) return toast('請先完成目前送出的清單'); mode = b.dataset.mode; persist(); renderCart(); }));
$('#clear').addEventListener('click', () => { if (pendingRecord) return toast('送出結果未確認，請重試確認保存以避免重複'); $('#confirm-text').textContent = '即將清空目前的草稿清單。'; $('#confirm').dataset.action = 'clear'; $('#commit').textContent = '確認清空'; $('#confirm').showModal(); });
$('#submit').addEventListener('click', () => { $('#confirm-text').textContent = `${mode}，共 ${Object.values(cart).reduce((a,b)=>a+b,0)} 件。此動作保存交付紀錄，不執行付款或藥物辨識。`; $('#confirm').dataset.action = 'save'; $('#commit').textContent = '確認保存'; $('#confirm').showModal(); });
$('#cancel-confirm').addEventListener('click', () => $('#confirm').close());
$('#commit').addEventListener('click', async () => {
  if (submitting) return;
  if ($('#confirm').dataset.action === 'clear') {cart = {}; persist(); renderCatalog(); renderCart(); $('#confirm').close(); return;}
  submitting = true; $('#commit').disabled = true;
  try {
    // Preserve the same UUID AND payload after an ambiguous network failure.
    pendingRecord ||= {id:crypto.randomUUID(),device:'local',created_at:new Date().toISOString(),mode,items:catalog.filter(p=>cart[p.id]).map(p=>({id:p.id,name:p.name,quantity:cart[p.id]}))};
    persist();
    await api('/api/records',pendingRecord);
    cart = {}; pendingRecord = null; persist(); $('#confirm').close(); toast('已保存到樹莓派，連線後自動傳送');
    renderCatalog(); await refreshStatus();
  } catch (error) { toast(`保存未確認：${error.message}。請按確認保存重試。`); }
  finally { submitting = false; $('#commit').disabled = false; renderCart(); }
});
async function refreshStatus() {
  try { const status = await api('/api/status'); $('#device').textContent = status.device; $('#connection').textContent = status.pending ? `● ${status.pending} 筆待傳` : status.configured ? '● 同步已設定' : '● 本機模式'; $('#sync-detail').textContent = `${status.sync.message} · 待傳 ${status.pending} 筆`; }
  catch { $('#connection').textContent = '● 本機服務離線'; }
}
async function history() {
  try { const rows = await api('/api/records'); $('#history').innerHTML = rows.map(r => `<article class="history-row"><h3>${escapeHTML(r.mode)} · ${escapeHTML(new Date(r.created_at).toLocaleString('zh-TW'))}</h3><p>${r.items.map(p => `${escapeHTML(p.name)} × ${p.quantity}`).join('、')}</p><p>${escapeHTML(r.device)} · ${escapeHTML(r.id)}</p><div class="history-state">${r.received?'↓ 遠端接收':r.synced?'✓ 已同步':'◷ 本機已存，等待同步'}</div></article>`).join('') || '<p>還沒有交付紀錄。</p>'; } catch (e) {toast(e.message);}
}
function switchView(showHistory) { $('#pick-view').hidden = showHistory; $('#history-view').hidden = !showHistory; $('#pick-tab').classList.toggle('active',!showHistory); $('#history-tab').classList.toggle('active',showHistory); if (showHistory) history(); }
$('#pick-tab').addEventListener('click', () => switchView(false));
$('#history-tab').addEventListener('click', () => switchView(true));
$('#sync').addEventListener('click', async () => {try {await api('/api/sync',{}); toast('已要求同步；狀態將自動更新');} catch(e){toast(e.message);} });
$('#export').addEventListener('click', async () => {try {const rows = await api('/api/records'); const url = URL.createObjectURL(new Blob([JSON.stringify(rows,null,2)],{type:'application/json'})); const a = document.createElement('a'); a.href=url; a.download=`mediguard-${new Date().toISOString().slice(0,10)}.json`; a.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){toast(e.message);} });
function clock() { $('#clock').textContent = new Date().toLocaleString('zh-TW',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}); }
async function initialize() {
  try {catalog = await api('/api/catalog'); cart = Object.fromEntries(Object.entries(cart).filter(([id,n]) => catalog.some(p=>p.id===id) && Number.isInteger(n) && n>0 && n<=99)); renderCatalog(); renderCart(); if(pendingRecord) toast('上次保存結果未確認，請按確認送出清單重試。');}
  catch {toast('無法讀取品項，請檢查本機服務並重新整理');}
  refreshStatus(); clock();
}
setInterval(() => {refreshStatus(); if(!$('#history-view').hidden) history();},10000); setInterval(clock,1000); initialize();
