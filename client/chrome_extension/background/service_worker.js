/**
 * x-keeper Chrome 拡張 — バックグラウンドサービスワーカー
 *
 * 役割:
 *  - x-keeper サーバーへの HTTP リクエスト (コンテンツスクリプトから fetch できないためここで行う)
 *  - オフラインキューの管理 (chrome.storage.local)
 *  - SPA ナビゲーション検知 → コンテンツスクリプトへ通知
 */

'use strict';

const KEY_SERVER = 'xkeeper_server_url';
const KEY_QUEUE  = 'xkeeper_offline_queue';
const DEFAULT_SERVER = 'http://localhost:8989';

// ── ストレージ (storage.local: sync より安定、Chrome アカウント不要) ──────────

async function getServerUrl() {
  const d = await chrome.storage.local.get(KEY_SERVER);
  return (d[KEY_SERVER] || DEFAULT_SERVER).replace(/\/$/, '');
}

async function getQueue() {
  const d = await chrome.storage.local.get(KEY_QUEUE);
  return d[KEY_QUEUE] || [];
}

async function setQueue(q) {
  await chrome.storage.local.set({ [KEY_QUEUE]: q });
}

async function enqueueOffline(url) {
  const q = await getQueue();
  if (!q.includes(url)) { q.push(url); await setQueue(q); }
}

// ── HTTP ──────────────────────────────────────────────────────────────────────

/** fetch に手動タイムアウトを付ける (AbortSignal.timeout より広い互換性) */
function fetchWithTimeout(url, options, ms) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  return fetch(url, { ...options, signal: ctrl.signal })
    .finally(() => clearTimeout(timer));
}

async function postUrls(urls) {
  const base = await getServerUrl();
  const res = await fetchWithTimeout(
    `${base}/api/queue`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ urls }),
    },
    5000,
  );
  if (res.status !== 202) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function checkHealth() {
  try {
    const base = await getServerUrl();
    const res = await fetchWithTimeout(`${base}/api/health`, {}, 3000);
    return res.status === 200;
  } catch {
    return false;
  }
}

async function flushQueue() {
  const q = await getQueue();
  if (!q.length) return;
  try {
    await postUrls(q);
    await setQueue([]);
    console.log(`[x-keeper] オフラインキュー送信: ${q.length} 件`);
  } catch (e) {
    console.warn('[x-keeper] オフラインキュー送信失敗:', e);
  }
}

// ── メッセージハンドラ ─────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      switch (msg.type) {

        case 'QUEUE_URL': {
          const urls = [].concat(msg.url);
          try {
            const data = await postUrls(urls);
            await flushQueue();
            sendResponse({ ok: true, data });
          } catch (e) {
            for (const u of urls) await enqueueOffline(u);
            sendResponse({ ok: false, error: String(e) });
          }
          break;
        }

        case 'FLUSH_QUEUE':
          await flushQueue();
          sendResponse({ ok: true, queue: await getQueue() });
          break;

        case 'GET_STATUS': {
          const [online, queue, serverUrl] = await Promise.all([
            checkHealth(), getQueue(), getServerUrl(),
          ]);
          sendResponse({ ok: true, online, queue, serverUrl });
          break;
        }

        case 'SET_SERVER_URL': {
          // URL に scheme がなければ補完する
          let url = (msg.url || '').trim().replace(/\/$/, '');
          if (url && !url.startsWith('http://') && !url.startsWith('https://')) {
            url = `http://${url}`;
          }
          await chrome.storage.local.set({ [KEY_SERVER]: url });
          sendResponse({ ok: true, url });
          break;
        }

        case 'EXPORT_HISTORY': {
          try {
            const base = await getServerUrl();
            const res = await fetchWithTimeout(`${base}/api/history/export`, {}, 10000);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            sendResponse({ ok: true, data: await res.text() });
          } catch (e) {
            sendResponse({ ok: false, error: String(e) });
          }
          break;
        }

        case 'IMPORT_HISTORY': {
          try {
            const base = await getServerUrl();
            const res = await fetchWithTimeout(
              `${base}/api/history/import`,
              {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: msg.data,
              },
              10000,
            );
            sendResponse({ ok: true, result: await res.json() });
          } catch (e) {
            sendResponse({ ok: false, error: String(e) });
          }
          break;
        }

        default:
          sendResponse({ ok: false, error: `unknown type: ${msg.type}` });
      }
    } catch (e) {
      // 予期せぬエラーを握り潰さず sendResponse に乗せる
      sendResponse({ ok: false, error: String(e) });
    }
  })();
  return true; // 非同期レスポンスのためにチャンネルを保持する
});

// ── SPA ナビゲーション検知 ────────────────────────────────────────────────────

chrome.webNavigation.onHistoryStateUpdated.addListener((details) => {
  if (details.frameId !== 0) return;
  chrome.tabs.sendMessage(details.tabId, { type: 'NAVIGATE', url: details.url })
    .catch(() => {});
});

// ── 起動時: オフラインキューのフラッシュ試行 ─────────────────────────────────

flushQueue();
