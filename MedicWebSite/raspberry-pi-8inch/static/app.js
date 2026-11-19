import { parseCheckPrescription, checkPrediction } from './workflow.js';

const $ = selector => document.querySelector(selector);
const lighting = { lightMode: 'white', brightness: 85 };
let prescription = null, checked = [], stage = 'idle', preview = false, busy = false;
let reader = null, decoderPromise = null, scanTimer = null, accepting = false;
let generation = 0, pendingRequest = null;
try { pendingRequest = sessionStorage.getItem('mediguard-pending-capture'); } catch { /* optional recovery marker */ }

function message(selector, text = '') { $(selector).textContent = text; $(selector).hidden = !text; }
function clearMessages() { message('#error'); message('#notice'); }
function setBusy(value) {
  busy = value;
  for (const selector of ['#start', '#cancel-scan', '#reset', '#open-camera', '#capture', '#stop-camera', '#next-prescription', '#recover', '#dismiss-recovery']) {
    $(selector).disabled = value || (selector === '#start' && !!pendingRequest);
  }
}
function setStage(value) {
  stage = value;
  for (const name of ['idle', 'scan', 'verify', 'complete']) $(`#${name}-view`).hidden = name !== value;
  for (const name of ['scan', 'verify', 'complete']) $(`#step-${name}`).classList.toggle('active', value === name || (value === 'idle' && name === 'scan'));
}
async function api(path, body, timeout = 12000) {
  const response = await fetch(path, {
    cache: 'no-store', signal: AbortSignal.timeout(timeout),
    ...(body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  });
  const data = await response.json();
  if (!response.ok || data.success === false) throw new Error(data.message || data.error || `操作失敗 HTTP ${response.status}`);
  return data;
}
function rememberRequest(id) {
  pendingRequest = id;
  try {
    if (id) sessionStorage.setItem('mediguard-pending-capture', id);
    else sessionStorage.removeItem('mediguard-pending-capture');
  } catch { /* The server still deduplicates the request ID. */ }
}
function stopDecoder() { clearInterval(scanTimer); scanTimer = null; }
function detachPreview() {
  stopDecoder(); preview = false;
  $('#camera-image').removeAttribute('src'); $('#camera-view').hidden = true;
  $('#capture').hidden = true; $('#stop-camera').hidden = true; $('#open-camera').hidden = false;
}
async function stopPreview() {
  detachPreview();
  await api('/api/device/preview/stop', {});
}
async function startPreview(slot) {
  $('#photo-pair').hidden = true;
  await api('/api/device/preview/start', lighting);
  $(slot).append($('#camera-view'));
  $('#camera-view').hidden = false;
  $('#camera-image').src = `/api/device/preview/stream?camera=1&session=${Date.now()}`;
  preview = true;
  $('#open-camera').hidden = true; $('#capture').hidden = stage !== 'verify'; $('#stop-camera').hidden = stage !== 'verify';
}
// Load the bundled decoder only when a scan is requested; there is no CDN.
async function getReader() {
  if (!decoderPromise) decoderPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script'); script.src = '/vendor/zxing-browser.min.js';
    script.onload = () => resolve(); script.onerror = () => { decoderPromise = null; script.remove(); reject(new Error('QR 解碼程式載入失敗，請重新啟動掃描。')); };
    document.head.append(script);
  });
  await decoderPromise;
  return reader ||= new window.ZXingBrowser.BrowserQRCodeReader();
}
function renderPrescription() {
  $('#prescription-meta').textContent = `${prescription.clinic} · ${prescription.id}`;
  $('#progress-count').textContent = `${checked.length} / ${prescription.medicines.length}`;
  $('#progress').max = prescription.medicines.length; $('#progress').value = checked.length;
  $('#medicines').replaceChildren(...prescription.medicines.map((medicine, index) => {
    const done = checked.includes(medicine.name), row = document.createElement('li');
    row.classList.toggle('is-checked', done);
    const icon = document.createElement('span'); icon.textContent = done ? '✓' : String(index + 1);
    const copy = document.createElement('div'), name = document.createElement('strong'), state = document.createElement('small');
    name.textContent = medicine.name; state.textContent = done ? '核對成功' : '待核對';
    copy.append(name, state); row.append(icon, copy); return row;
  }));
}
async function acceptPrescription(text) {
  if (accepting || stage !== 'scan') return;
  const parsed = parseCheckPrescription(text);
  accepting = true; setBusy(true); stopDecoder();
  try {
    await stopPreview();
    prescription = parsed; checked = []; clearMessages();
    renderPrescription(); setStage('verify');
    $('#operation-status').textContent = '藥單已讀取。放入一項藥品，再開啟鏡頭對準。';
  } finally { accepting = false; setBusy(false); }
}
async function beginScan() {
  if (busy || pendingRequest) return;
  clearMessages(); generation += 1; setStage('scan'); setBusy(true);
  const current = generation;
  $('#scan-status').textContent = '正在開啟 Camera 1…';
  try {
    const qrReader = await getReader();
    await startPreview('#scan-camera-slot');
    $('#scan-status').textContent = '正在掃描；請完整拍入藥單 QR Code。';
    const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 360;
    const context = canvas.getContext('2d', { willReadFrequently: true });
    scanTimer = setInterval(() => {
      if (stage !== 'scan' || accepting || current !== generation) return;
      const image = $('#camera-image');
      if (!image.naturalWidth) return;
      const height = Math.min(1280, Math.round(canvas.width * image.naturalHeight / image.naturalWidth));
      if (canvas.height !== height) canvas.height = height;
      let text;
      try { context.drawImage(image, 0, 0, canvas.width, canvas.height); text = qrReader.decodeFromCanvas(canvas).getText(); }
      catch { return; /* No QR in this frame. */ }
      void acceptPrescription(text).catch(error => {
        message('#error', error.message);
        $('#scan-status').textContent = '請重新放置有效的藥單 QR Code，或使用圖片／文字讀取。';
      });
    }, 1000);
  } catch (error) { message('#error', error.message); $('#scan-status').textContent = '鏡頭未就緒，可改用 QR 圖片或 USB 掃碼器。'; }
  finally { setBusy(false); }
}
async function reset() {
  if (busy || pendingRequest) return;
  clearMessages(); setBusy(true); generation += 1;
  try { await stopPreview(); }
  catch (error) { message('#error', error.message); }
  finally {
    prescription = null; checked = []; $('#medicines').replaceChildren(); $('#qr-text').value = '';
    $('#front-photo').removeAttribute('src'); $('#back-photo').removeAttribute('src'); $('#photo-pair').hidden = true;
    setStage('idle'); setBusy(false);
  }
}
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitForCapture(id) {
  const deadline = Date.now() + 150000;
  while (Date.now() < deadline) {
    const state = await api(`/api/device/requests/${id}`);
    if (state.status === 'completed') return state.result;
    if (['failed', 'uncertain'].includes(state.status)) {
      if (state.status === 'failed') rememberRequest(null);
      throw new Error(state.error || '無法確認拍攝結果。');
    }
    await sleep(1500);
  }
  throw new Error('尚未收到拍攝確認；請查詢前次拍攝，不要重複送出。');
}
async function waitForRecognition(captureId) {
  const deadline = Date.now() + 330000;
  while (Date.now() < deadline) {
    const state = await api(`/api/device/captures/${captureId}/verification`);
    if (state.status === 'completed') return state.result;
    if (['failed', 'not_configured'].includes(state.status)) {
      rememberRequest(null);
      throw new Error(state.status === 'not_configured' ? '辨識服務尚未設定，請聯絡管理者確認 MedicServer 連線。' : 'Server 辨識或圖片上傳失敗，請檢查硬體與 MedicServer 日誌。');
    }
    await sleep(2000);
  }
  throw new Error('Server 核對等待逾時；可查詢前次拍攝結果，不會自動重送。');
}
async function processCapture(result) {
  detachPreview();
  if (!result?.captureId || !/^[0-9a-f-]{36}$/.test(result.captureId)) throw new Error('裝置未回傳有效拍攝編號。');
  $('#photo-pair').hidden = false;
  $('#front-photo').src = `/api/device/captures/${result.captureId}/camera/1`;
  $('#back-photo').src = `/api/device/captures/${result.captureId}/camera/2`;
  $('#operation-status').textContent = '兩張照片已擷取，等待 server 上傳與辨識結果…';
  if (result.backendUpload?.status === 'not_configured') {
    rememberRequest(null);
    throw new Error('照片已擷取，但辨識服務尚未設定，請聯絡管理者確認 MedicServer 連線。');
  }
  const recognition = await waitForRecognition(result.captureId);
  const prediction = recognition?.fused_result ? recognition.fused_result.final_prediction : recognition?.yolo_result?.prediction;
  rememberRequest(null); $('#recovery').hidden = true;
  if (!prescription) {
    message('#notice', `前次拍攝已完成，辨識結果：${prediction || '未辨識'}。原藥單未保存，請重新掃藥單進行下一次核對。`);
    return;
  }
  const match = checkPrediction(prescription, checked, prediction, recognition?.outcome);
  checked = match.checked; renderPrescription();
  const notice = match.kind === 'matched' ? `已核對：${prediction}。請更換下一項藥品。`
    : match.kind === 'duplicate' ? '這項藥品已核對，請更換尚未核對的藥品。'
    : recognition?.outcome === 'NEEDS_REVIEW' ? 'Server 回覆需要人工確認，本項未標記成功。'
    : `本次未能核對藥單項目（${prediction || '未辨識'}），請確認藥品或交由專業人員核對。`;
  message('#notice', notice); $('#operation-status').textContent = '本次拍攝已完成。';
  if (checked.length === prescription.medicines.length) {
    $('#complete-message').textContent = `本次藥單的 ${checked.length} 項藥品皆已依 server 結果完成比對。`;
    message('#notice', '本次藥單全部項目已核對完成。');
    setStage('complete');
  }
}
function showRecovery() { $('#recovery').hidden = !pendingRequest; setBusy(false); }
async function capture() {
  if (busy || !preview || !prescription) return;
  clearMessages(); setBusy(true); stopDecoder();
  const id = pendingRequest || crypto.randomUUID(); rememberRequest(id);
  $('#operation-status').textContent = '正在擷取 Camera 1／Camera 2，請勿移動藥品…';
  try {
    await api('/api/device/capture', { requestId: id });
    await processCapture(await waitForCapture(id));
  } catch (error) { message('#error', error.message); detachPreview(); }
  finally { setBusy(false); showRecovery(); }
}

$('#start').addEventListener('click', beginScan);
$('#cancel-scan').addEventListener('click', reset);
$('#reset').addEventListener('click', reset);
$('#next-prescription').addEventListener('click', reset);
$('#open-camera').addEventListener('click', async () => {
  if (busy || pendingRequest) return;
  clearMessages(); setBusy(true);
  try { await startPreview('#verify-camera-slot'); $('#operation-status').textContent = '將一項藥品對準紅色十字，再按擷取送出。'; }
  catch (error) { message('#error', error.message); }
  finally { setBusy(false); }
});
$('#capture').addEventListener('click', capture);
$('#stop-camera').addEventListener('click', async () => {
  if (busy) return; setBusy(true);
  try { await stopPreview(); } catch (error) { message('#error', error.message); }
  finally { setBusy(false); }
});
$('#manual-toggle').addEventListener('click', () => { $('#manual-form').hidden = !$('#manual-form').hidden; if (!$('#manual-form').hidden) $('#qr-text').focus(); });
$('#manual-form').addEventListener('submit', event => {
  event.preventDefault(); if (busy) return;
  void acceptPrescription($('#qr-text').value).catch(error => message('#error', error.message));
});
$('#qr-file').addEventListener('change', async event => {
  const file = event.target.files?.[0]; if (!file || busy) return;
  if (file.size > 5 * 1024 * 1024) { message('#error', '請使用 5 MB 以下的清晰 QR 圖片。'); event.target.value = ''; return; }
  const url = URL.createObjectURL(file); stopDecoder(); clearMessages();
  try { const qrReader = await getReader(); const code = await qrReader.decodeFromImageUrl(url); await acceptPrescription(code.getText()); }
  catch (error) { message('#error', error.message || '圖片中找不到有效藥單 QR Code。'); }
  finally { URL.revokeObjectURL(url); event.target.value = ''; }
});
$('#recover').addEventListener('click', async () => {
  if (busy || !pendingRequest) return;
  setBusy(true); clearMessages();
  try { await processCapture(await waitForCapture(pendingRequest)); }
  catch (error) { message('#error', error.message); }
  finally { setBusy(false); showRecovery(); }
});
$('#dismiss-recovery').addEventListener('click', () => {
  if (busy || !window.confirm('已確認硬體／server 的上次紀錄？清除此標記不會取消已送出的辨識作業。')) return;
  rememberRequest(null); showRecovery();
});
$('#camera-image').addEventListener('error', () => { if (preview) message('#error', '鏡頭串流中斷，請關閉鏡頭後重試。'); });
window.addEventListener('pagehide', () => {
  stopDecoder(); $('#camera-image').removeAttribute('src');
  if (!busy) void fetch('/api/device/preview/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', keepalive: true }).catch(() => {});
});
async function refreshConnection() {
  try { await api('/api/device/status', undefined, 5000); $('#connection').textContent = '● 雙鏡頭已連線'; }
  catch { $('#connection').textContent = '● 鏡頭服務未連線'; }
}
showRecovery(); void refreshConnection();
setInterval(() => { if (!busy) void refreshConnection(); }, 30000);
