'use strict';

// ── DOM 参照 ──────────────────────────────────────────────────────────────────

const $serverUrl    = document.getElementById('server-url');
const $btnTest      = document.getElementById('btn-test');
const $btnSave      = document.getElementById('btn-save');
const $statusBadge  = document.getElementById('status-badge');
const $queueSection = document.getElementById('queue-section');
const $queueList    = document.getElementById('queue-list');
const $queueCount   = document.getElementById('queue-count');
const $btnFlush     = document.getElementById('btn-flush');
const $btnClear     = document.getElementById('btn-clear-queue');
const $btnExport    = document.getElementById('btn-export');
const $btnImport    = document.getElementById('btn-import');
const $importFile   = document.getElementById('import-file');
const $historyCount = document.getElementById('history-count');

// ── ヘルパー ──────────────────────────────────────────────────────────────────

/**
 * サービスワーカーにメッセージを送り、レスポンスを返す。
 * サービスワーカーが未起動の場合は自動的に起動されるが、
 * lastError を必ずチェックして握り潰す。
 */
function send(msg) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(msg, (res) => {
      if (chrome.runtime.lastError) {
        // サービスワーカーが起動中 or まだ準備できていない
        console.warn('[x-keeper]', chrome.runtime.lastError.message);
        resolve({ ok: false, error: chrome.runtime.lastError.message });
        return;
      }
      resolve(res || { ok: false, error: 'no response' });
    });
  });
}

function setStatus(online) {
  $statusBadge.textContent = online ? '接続中' : '未接続';
  $statusBadge.className   = online ? 'online'  : 'offline';
}

function renderHistoryCount(count) {
  $historyCount.textContent = count != null ? `${count.toLocaleString()} 件ダウンロード済み` : '';
}

function renderQueue(queue) {
  if (!queue || queue.length === 0) {
    $queueSection.style.display = 'none';
    return;
  }
  $queueSection.style.display = '';
  $queueCount.textContent = `(${queue.length} 件)`;
  $queueList.innerHTML = queue
    .map(u => `<p title="${u}">${u}</p>`)
    .join('');
}

// ── 初期化 ────────────────────────────────────────────────────────────────────

async function init() {
  const res = await send({ type: 'GET_STATUS' });
  if (!res.ok) {
    // サービスワーカーが起動中の可能性があるので少し待ってリトライ
    await new Promise(r => setTimeout(r, 800));
    const retry = await send({ type: 'GET_STATUS' });
    if (!retry.ok) return;
    applyStatus(retry);
    return;
  }
  applyStatus(res);
}

function applyStatus(res) {
  $serverUrl.value = res.serverUrl || '';
  setStatus(res.online);
  renderQueue(res.queue);
  renderHistoryCount(res.historyCount ?? null);
}

init();

// ── サーバー URL 設定 ─────────────────────────────────────────────────────────

$btnTest.addEventListener('click', async () => {
  $btnTest.disabled = true;
  $btnTest.textContent = '…';

  const raw = $serverUrl.value.trim();
  if (!raw) {
    $btnTest.textContent = '空白';
    setTimeout(() => { $btnTest.disabled = false; $btnTest.textContent = 'テスト'; }, 1500);
    return;
  }

  // URL 保存 (scheme 補完はサービスワーカー側で行う)
  const saveRes = await send({ type: 'SET_SERVER_URL', url: raw });
  if (saveRes.url) $serverUrl.value = saveRes.url; // 補完後の URL をフィールドに反映

  // 接続テスト
  const statusRes = await send({ type: 'GET_STATUS' });
  const online = statusRes.ok ? statusRes.online : false;
  setStatus(online);
  renderQueue(statusRes.queue || []);

  // テスト結果を表示 (URL は保存済みなので失敗でも保存は成功)
  $btnTest.textContent = online ? '接続 ✓' : '未接続 ✗';
  setTimeout(() => { $btnTest.disabled = false; $btnTest.textContent = 'テスト'; }, 2000);
});

$btnSave.addEventListener('click', async () => {
  const raw = $serverUrl.value.trim();
  if (!raw) return;
  const res = await send({ type: 'SET_SERVER_URL', url: raw });
  if (res.url) $serverUrl.value = res.url;
  $btnSave.textContent = '保存済 ✓';
  setTimeout(() => { $btnSave.textContent = '保存'; }, 1500);
});

// ── オフラインキュー ──────────────────────────────────────────────────────────

$btnFlush.addEventListener('click', async () => {
  $btnFlush.disabled = true;
  $btnFlush.textContent = '送信中…';
  const res = await send({ type: 'FLUSH_QUEUE' });
  renderQueue(res.queue || []);
  // 接続状態を再取得
  const status = await send({ type: 'GET_STATUS' });
  if (status.ok) setStatus(status.online);
  $btnFlush.disabled = false;
  $btnFlush.textContent = '今すぐ送信';
});

$btnClear.addEventListener('click', async () => {
  await chrome.storage.local.remove('xkeeper_offline_queue');
  renderQueue([]);
});

// ── 履歴エクスポート ──────────────────────────────────────────────────────────

$btnExport.addEventListener('click', async () => {
  $btnExport.disabled = true;
  $btnExport.textContent = '…';
  const res = await send({ type: 'EXPORT_HISTORY' });
  $btnExport.disabled = false;
  $btnExport.textContent = 'エクスポート';
  if (!res.ok) { alert(`エクスポート失敗: ${res.error}`); return; }

  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([res.data], { type: 'application/json' }));
  a.download = `xkeeper-history-${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
});

// ── 履歴インポート ────────────────────────────────────────────────────────────

$btnImport.addEventListener('click', () => $importFile.click());

$importFile.addEventListener('change', () => {
  const file = $importFile.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async (e) => {
    $btnImport.disabled = true;
    $btnImport.textContent = '…';
    const res = await send({ type: 'IMPORT_HISTORY', data: e.target.result });
    $btnImport.disabled = false;
    if (res.ok) {
      $btnImport.textContent = `${res.result.imported} 件 ✓`;
      // インポート後に件数を最新化する
      const status = await send({ type: 'GET_STATUS' });
      if (status.ok) renderHistoryCount(status.historyCount ?? null);
      setTimeout(() => { $btnImport.textContent = 'インポート'; }, 2000);
    } else {
      $btnImport.textContent = 'インポート';
      alert(`インポート失敗: ${res.error}`);
    }
  };
  reader.readAsText(file);
  $importFile.value = '';
});
