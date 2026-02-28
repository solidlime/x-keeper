'use strict';

// ── DOM 参照 ──────────────────────────────────────────────────────────────────

const $serverUrl        = document.getElementById('server-url');
const $btnTest          = document.getElementById('btn-test');
const $btnSave          = document.getElementById('btn-save');
const $btnGallery       = document.getElementById('btn-gallery');
const $statusBadge      = document.getElementById('status-badge');
const $queueSection     = document.getElementById('queue-section');
const $queueList        = document.getElementById('queue-list');
const $queueCount       = document.getElementById('queue-count');
const $btnFlush         = document.getElementById('btn-flush');
const $btnClear         = document.getElementById('btn-clear-queue');
const $apiQueueSection  = document.getElementById('api-queue-section');
const $apiQueueList     = document.getElementById('api-queue-list');
const $apiQueueCount    = document.getElementById('api-queue-count');
const $btnClearApiQueue = document.getElementById('btn-clear-api-queue');
const $queuedItemsSection = document.getElementById('queued-items-section');
const $queuedItemsList    = document.getElementById('queued-items-list');
const $queuedItemsCount   = document.getElementById('queued-items-count');
const $btnClearQueued     = document.getElementById('btn-clear-queued');
const $btnExport        = document.getElementById('btn-export');
const $btnImport        = document.getElementById('btn-import');
const $importFile       = document.getElementById('import-file');
const $historyCount     = document.getElementById('history-count');
const $resultLogSec     = document.getElementById('result-log-section');
const $resultLogList    = document.getElementById('result-log-list');
const $logCount         = document.getElementById('log-count');
const $serverLogSec     = document.getElementById('server-log-section');
const $serverLogList    = document.getElementById('server-log-list');

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

/**
 * サーバーの処理待ちキュー（直接ダウンロードキュー）を表示する。
 * 各アイテムに個別削除ボタンを付ける。
 */
function renderApiQueue(items) {
  if (!items || items.length === 0) {
    $apiQueueSection.style.display = 'none';
    return;
  }
  $apiQueueSection.style.display = '';
  $apiQueueCount.textContent = `(${items.length} 件)`;
  $apiQueueList.innerHTML = '';
  for (const item of items) {
    const url = item.url || '';
    const div = document.createElement('div');
    div.className = 'api-queue-item';
    div.innerHTML = `
      <span class="api-queue-url" title="${url}">${url}</span>
      <button class="api-queue-del" data-url="${url}">削除</button>
    `;
    $apiQueueList.appendChild(div);
  }
  // イベント委譲で削除ボタンを処理する
  $apiQueueList.querySelectorAll('.api-queue-del').forEach((btn) => {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      const res = await send({ type: 'DELETE_API_QUEUE_ITEM', url: btn.dataset.url });
      if (res.ok) {
        btn.closest('.api-queue-item').remove();
        const remaining = $apiQueueList.querySelectorAll('.api-queue-item').length;
        if (remaining === 0) {
          $apiQueueSection.style.display = 'none';
        } else {
          $apiQueueCount.textContent = `(${remaining} 件)`;
        }
      } else {
        btn.disabled = false;
        alert(`削除失敗: ${res.error}`);
      }
    });
  });
}

/** ISO 文字列を「HH:MM」または「M/D HH:MM」に変換する */
function formatTime(iso) {
  const d = new Date(iso);
  const now = new Date();
  const today = now.toDateString() === d.toDateString();
  const hhmm = d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
  if (today) return hhmm;
  return `${d.getMonth() + 1}/${d.getDate()} ${hhmm}`;
}

/** サーバー側のダウンロード処理結果（最新5件）を表示する */
function renderServerLog(logs) {
  if (!logs || logs.length === 0) {
    $serverLogSec.style.display = 'none';
    return;
  }
  $serverLogSec.style.display = '';
  $serverLogList.innerHTML = logs.map((entry) => {
    const url = (entry.urls || [])[0] || '';
    const isSuccess = entry.status === 'success';
    const statusLabel = isSuccess ? '成功' : '失敗';
    const statusClass = isSuccess ? 'success' : 'failure';
    const detail = isSuccess
      ? (entry.file_count != null ? ` ${entry.file_count}件` : '')
      : (entry.error ? ` — ${entry.error}` : '');
    return `<div class="log-entry">
      <div class="log-url" title="${url}">${url}</div>
      <div class="log-meta">
        <span class="log-status ${statusClass}">${statusLabel}${detail}</span>
        <span class="log-time">${formatTime(entry.ts)}</span>
      </div>
    </div>`;
  }).join('');
}

function renderResultLog(log) {
  if (!log || log.length === 0) {
    $resultLogSec.style.display = 'none';
    return;
  }
  $resultLogSec.style.display = '';
  $logCount.textContent = `(${log.length} 件)`;
  $resultLogList.innerHTML = log.map((entry) => {
    const urls = entry.urls || [];
    const urlStr = urls[0] || '';
    const statusLabel = entry.status === 'queued' ? '送信済' : 'オフライン';
    const statusClass = entry.status === 'queued' ? 'queued' : 'offline';
    const rejected = (entry.rejected || []).length;
    const extra = rejected > 0 ? ` (${rejected} 件スキップ)` : '';
    return `<div class="log-entry">
      <div class="log-url" title="${urlStr}">${urlStr}</div>
      <div class="log-meta">
        <span class="log-status ${statusClass}">${statusLabel}${extra}</span>
        <span class="log-time">${formatTime(entry.ts)}</span>
      </div>
    </div>`;
  }).join('');
}

/**
 * content.js が chrome.storage.local に保存したキュー済みアイテムを表示する。
 * xkeeper_queued_items: [{url, title}] 形式のメタデータを使い、
 * タイトル + クリッカブルリンクで一覧表示する。
 * 件数が 0 の場合はセクション非表示。
 */
/**
 * キュー済みアイテムの1件分の DOM を生成する。
 * - タイトル (クリッカブルリンク)
 * - URL (薄い文字で表示)
 * - × ボタン (個別キャンセル: ローカルストレージ + サーバーキューから削除)
 * @param {{url: string, title: string}} item
 * @param {HTMLElement} container - アイテムを格納している親要素
 */
function createQueuedItemEl(item, container) {
  const div = document.createElement('div');
  div.style.cssText = [
    'padding:5px 0',
    'border-bottom:1px solid #1e293b',
    'display:flex',
    'flex-direction:column',
    'gap:2px',
  ].join(';');

  // タイトル行 (リンク + × ボタン)
  const titleRow = document.createElement('div');
  titleRow.style.cssText = 'display:flex;align-items:center;gap:4px;';

  const a = document.createElement('a');
  a.href = item.url;
  a.target = '_blank';
  a.rel = 'noopener';
  a.title = item.url;
  a.style.cssText = [
    'flex:1',
    'font-size:11px',
    'color:#60a5fa',
    'overflow:hidden',
    'text-overflow:ellipsis',
    'white-space:nowrap',
    'text-decoration:none',
    'min-width:0',
  ].join(';');
  a.textContent = item.title || item.url;
  a.addEventListener('mouseenter', () => { a.style.textDecoration = 'underline'; });
  a.addEventListener('mouseleave', () => { a.style.textDecoration = 'none'; });

  // 個別キャンセルボタン
  const cancelBtn = document.createElement('button');
  cancelBtn.textContent = '×';
  cancelBtn.title = 'キャンセル';
  cancelBtn.style.cssText = [
    'flex-shrink:0',
    'padding:1px 5px',
    'font-size:10px',
    'border-radius:4px',
    'background:#7f1d1d',
    'color:#fca5a5',
    'border:none',
    'cursor:pointer',
    'line-height:1.4',
  ].join(';');
  cancelBtn.addEventListener('click', async () => {
    cancelBtn.disabled = true;

    // 1. xkeeper_queued_items から削除
    const d1 = await chrome.storage.local.get('xkeeper_queued_items');
    const newItems = (d1.xkeeper_queued_items || []).filter(i => i.url !== item.url);
    await chrome.storage.local.set({ xkeeper_queued_items: newItems });

    // 2. xkeeper_queued_ids / xkeeper_queued_urls からも削除
    const m = item.url.match(/\/status\/(\d+)/);
    if (m) {
      const d2 = await chrome.storage.local.get('xkeeper_queued_ids');
      const ids = (d2.xkeeper_queued_ids || []).filter(id => id !== m[1]);
      await chrome.storage.local.set({ xkeeper_queued_ids: ids });
    } else {
      const d2 = await chrome.storage.local.get('xkeeper_queued_urls');
      const urls = (d2.xkeeper_queued_urls || []).filter(u => u !== item.url);
      await chrome.storage.local.set({ xkeeper_queued_urls: urls });
    }

    // 3. サーバーの API キューからも削除を試みる (失敗してもローカルは削除済み)
    send({ type: 'DELETE_API_QUEUE_ITEM', url: item.url }).catch(() => {});

    // DOM から除去して件数を更新する
    div.remove();
    const remaining = container.querySelectorAll('[data-xk-queued-item]').length;
    if (remaining === 0) {
      $queuedItemsSection.style.display = 'none';
    } else {
      $queuedItemsCount.textContent = `(${remaining} 件)`;
    }
  });

  titleRow.appendChild(a);
  titleRow.appendChild(cancelBtn);

  // URL 表示行
  const urlSpan = document.createElement('span');
  urlSpan.style.cssText = [
    'font-size:10px',
    'color:#475569',
    'overflow:hidden',
    'text-overflow:ellipsis',
    'white-space:nowrap',
    'font-family:monospace',
  ].join(';');
  urlSpan.textContent = item.url;

  div.dataset.xkQueuedItem = '1';
  div.appendChild(titleRow);
  div.appendChild(urlSpan);
  return div;
}

async function loadQueuedItems() {
  const data  = await chrome.storage.local.get('xkeeper_queued_items');
  const items = data.xkeeper_queued_items || [];

  if (items.length === 0) {
    $queuedItemsSection.style.display = 'none';
    return;
  }

  $queuedItemsSection.style.display = '';
  $queuedItemsCount.textContent = `(${items.length} 件)`;

  $queuedItemsList.innerHTML = '';
  for (const item of items) {
    $queuedItemsList.appendChild(createQueuedItemEl(item, $queuedItemsList));
  }
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
  renderApiQueue(res.apiQueue || []);
  renderHistoryCount(res.historyCount ?? null);
  renderServerLog(res.serverLogs || []);
  renderResultLog(res.resultLog || []);
}

init();
loadQueuedItems();

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
  renderApiQueue(statusRes.apiQueue || []);

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

// ── ギャラリーリンク ──────────────────────────────────────────────────────────

$btnGallery.addEventListener('click', async () => {
  const res = await send({ type: 'GET_STATUS' });
  const base = (res.ok && res.serverUrl) ? res.serverUrl : 'http://localhost:8989';
  chrome.tabs.create({ url: `${base}/gallery` });
});

// ── オフラインキュー ──────────────────────────────────────────────────────────

$btnFlush.addEventListener('click', async () => {
  $btnFlush.disabled = true;
  $btnFlush.textContent = '送信中…';
  const res = await send({ type: 'FLUSH_QUEUE' });
  renderQueue(res.queue || []);
  // 接続状態を再取得
  const status = await send({ type: 'GET_STATUS' });
  if (status.ok) {
    setStatus(status.online);
    renderResultLog(status.resultLog || []);
    renderApiQueue(status.apiQueue || []);
  }
  $btnFlush.disabled = false;
  $btnFlush.textContent = '今すぐ送信';
});

$btnClear.addEventListener('click', async () => {
  await chrome.storage.local.remove('xkeeper_offline_queue');
  renderQueue([]);
});

// ── サーバー処理待ちキュー ────────────────────────────────────────────────────

$btnClearApiQueue.addEventListener('click', async () => {
  $btnClearApiQueue.disabled = true;
  $btnClearApiQueue.textContent = '削除中…';
  const res = await send({ type: 'CLEAR_API_QUEUE' });
  if (res.ok) {
    renderApiQueue([]);
  } else {
    alert(`全件削除失敗: ${res.error}`);
  }
  $btnClearApiQueue.disabled = false;
  $btnClearApiQueue.textContent = '全件削除';
});

// ── キュー済みアイテムクリア ──────────────────────────────────────────────────

$btnClearQueued.addEventListener('click', async () => {
  await chrome.storage.local.remove(['xkeeper_queued_ids', 'xkeeper_queued_urls', 'xkeeper_queued_items']);
  $queuedItemsSection.style.display = 'none';
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
