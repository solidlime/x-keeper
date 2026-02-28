/**
 * x-keeper Chrome 拡張 — バックグラウンドサービスワーカー
 *
 * 役割:
 *  - x-keeper サーバーへの HTTP リクエスト (コンテンツスクリプトから fetch できないためここで行う)
 *  - オフラインキューの管理 (chrome.storage.local)
 *  - SPA ナビゲーション検知 → コンテンツスクリプトへ通知
 *  - ダウンロード済み ID のポーリング → 全タブへ IDS_UPDATED を通知
 *    (content.js からの直接 SSE 接続は HTTPS ページからの Mixed Content でブロックされるため、
 *     Service Worker が HTTP でポーリングして中継する)
 *  - ダウンロード済み URL のポーリング (Pixiv / Imgur 等 tweet_id なしサイト用)
 */

'use strict';

const KEY_SERVER     = 'xkeeper_server_url';
const KEY_QUEUE      = 'xkeeper_offline_queue';
const KEY_RESULT_LOG = 'xkeeper_result_log';   // ダウンロードキュー結果の履歴
const DEFAULT_SERVER = 'http://localhost:8989';
const MAX_RESULT_LOG = 50;                     // 保持する最大件数

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

// ── ダウンロード済み tweet ID ポーリング ─────────────────────────────────────

/** ポーリングで取得したダウンロード済み tweet ID のキャッシュ */
let _cachedIds = [];

/** 最後に確認したダウンロード件数 (変化検出用。-1 = 未取得) */
let _cachedCount = -1;

/**
 * サーバーからダウンロード済み ID リストをポーリングして _cachedIds を更新する。
 * カウントが変化していれば全タブのコンテンツスクリプトに IDS_UPDATED を通知する。
 *
 * content.js が直接 EventSource を使うと HTTPS ページからの HTTP SSE 接続が
 * Mixed Content としてブロックされるため、Service Worker が中継する。
 */
async function pollDownloadedIds() {
  try {
    const base = await getServerUrl();

    // まずカウントだけ確認して変化がなければ早期リターン (転送量節約)
    const countRes = await fetchWithTimeout(`${base}/api/history/count`, {}, 3000);
    if (countRes.status !== 200) return;
    const { count } = await countRes.json();
    if (count === _cachedCount) return;

    // 変化あり: 全 ID を取得
    const idsRes = await fetchWithTimeout(`${base}/api/history/ids`, {}, 10000);
    if (idsRes.status !== 200) return;
    _cachedIds  = await idsRes.json();
    _cachedCount = count;

    // 全 X / Pixiv タブに通知 (エラーは無視)
    const tabs = await chrome.tabs.query({
      url: ['*://x.com/*', '*://twitter.com/*', '*://www.pixiv.net/*'],
    });
    for (const tab of tabs) {
      chrome.tabs.sendMessage(tab.id, { type: 'IDS_UPDATED', ids: _cachedIds }).catch(() => {});
    }
  } catch {
    // サーバー未接続など: 静かにスキップ
  }
}

// ── ダウンロード済み URL ポーリング (Pixiv / Imgur 等) ───────────────────────

/** ポーリングで取得したダウンロード済み URL のキャッシュ */
let _cachedUrls = [];

/** 最後に確認したダウンロード済み URL 件数 (変化検出用。-1 = 未取得) */
let _cachedUrlCount = -1;

/**
 * サーバーからダウンロード済み URL リストをポーリングして _cachedUrls を更新する。
 * カウントが変化していれば全 Pixiv タブに URLS_UPDATED を通知する。
 */
async function pollDownloadedUrls() {
  try {
    const base = await getServerUrl();

    const countRes = await fetchWithTimeout(`${base}/api/history/urls/count`, {}, 3000);
    if (countRes.status !== 200) return;
    const { count } = await countRes.json();
    if (count === _cachedUrlCount) return;

    const urlsRes = await fetchWithTimeout(`${base}/api/history/urls`, {}, 10000);
    if (urlsRes.status !== 200) return;
    _cachedUrls    = await urlsRes.json();
    _cachedUrlCount = count;

    // Pixiv タブに通知 (将来的に他のサイトも追加する場合はここを拡張する)
    const tabs = await chrome.tabs.query({ url: ['*://www.pixiv.net/*'] });
    for (const tab of tabs) {
      chrome.tabs.sendMessage(tab.id, { type: 'URLS_UPDATED', urls: _cachedUrls }).catch(() => {});
    }
  } catch {
    // サーバー未接続など: 静かにスキップ
  }
}

// 1 分ごとにポーリング (Manifest V3 alarm: Service Worker が起きていなくても実行される)
chrome.alarms.create('poll-ids', { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'poll-ids') {
    pollDownloadedIds();
    pollDownloadedUrls();
  }
});

// ── 結果ログ ──────────────────────────────────────────────────────────────────

/** キュー送信の結果を chrome.storage.local に記録する (最新 MAX_RESULT_LOG 件) */
async function appendResultLog(entry) {
  const d = await chrome.storage.local.get(KEY_RESULT_LOG);
  const log = d[KEY_RESULT_LOG] || [];
  log.unshift(entry);  // 最新を先頭に
  if (log.length > MAX_RESULT_LOG) log.length = MAX_RESULT_LOG;
  await chrome.storage.local.set({ [KEY_RESULT_LOG]: log });
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
            // 送信成功を結果ログに記録
            await appendResultLog({
              ts: new Date().toISOString(),
              status: 'queued',
              urls,
              accepted: data.accepted || [],
              rejected: data.rejected || [],
            });
            // ダウンロードキューに追加できたので ID・URL キャッシュを即時更新する
            pollDownloadedIds();
            pollDownloadedUrls();
            sendResponse({ ok: true, data });
          } catch (e) {
            for (const u of urls) await enqueueOffline(u);
            // オフラインキュー保存を結果ログに記録
            await appendResultLog({
              ts: new Date().toISOString(),
              status: 'offline',
              urls,
            });
            sendResponse({ ok: false, error: String(e) });
          }
          break;
        }

        case 'FLUSH_QUEUE':
          await flushQueue();
          sendResponse({ ok: true, queue: await getQueue() });
          break;

        case 'GET_STATUS': {
          const [online, queue, serverUrl, logData] = await Promise.all([
            checkHealth(), getQueue(), getServerUrl(),
            chrome.storage.local.get(KEY_RESULT_LOG),
          ]);
          // オンライン時のみ履歴件数とサーバー処理ログを取得する
          let historyCount = null;
          let serverLogs = [];
          let apiQueue = [];
          if (online) {
            try {
              const r = await fetchWithTimeout(`${serverUrl}/api/history/count`, {}, 3000);
              if (r.status === 200) historyCount = (await r.json()).count ?? null;
            } catch { /* ignore */ }
            try {
              const r = await fetchWithTimeout(`${serverUrl}/api/logs/recent`, {}, 3000);
              if (r.status === 200) serverLogs = await r.json();
            } catch { /* ignore */ }
            try {
              const r = await fetchWithTimeout(`${serverUrl}/api/queue/status`, {}, 3000);
              if (r.status === 200) apiQueue = await r.json();
            } catch { /* ignore */ }
          }
          const resultLog = logData[KEY_RESULT_LOG] || [];
          sendResponse({ ok: true, online, queue, serverUrl, historyCount, resultLog, serverLogs, apiQueue });
          break;
        }

        case 'GET_IDS': {
          // 必ずサーバーから最新の ID を取得してから返す
          // (Service Worker 起動直後は _cachedIds が空のため await してから返す)
          await pollDownloadedIds();
          sendResponse({ ok: true, ids: _cachedIds });
          break;
        }

        case 'GET_URLS': {
          // Pixiv / Imgur 等のダウンロード済み URL を取得してから返す
          await pollDownloadedUrls();
          sendResponse({ ok: true, urls: _cachedUrls });
          break;
        }

        case 'SET_SERVER_URL': {
          // URL に scheme がなければ補完する
          let url = (msg.url || '').trim().replace(/\/$/, '');
          if (url && !url.startsWith('http://') && !url.startsWith('https://')) {
            url = `http://${url}`;
          }
          await chrome.storage.local.set({ [KEY_SERVER]: url });
          // サーバー URL が変わったのでキャッシュをリセットして再取得する
          _cachedCount    = -1;
          _cachedUrlCount = -1;
          pollDownloadedIds();
          pollDownloadedUrls();
          sendResponse({ ok: true, url });
          break;
        }

        case 'DELETE_API_QUEUE_ITEM': {
          // サーバーの直接ダウンロードキューから指定 URL を削除する
          try {
            const base = await getServerUrl();
            const res = await fetchWithTimeout(
              `${base}/api/queue/item`,
              {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: msg.url }),
              },
              5000,
            );
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
            sendResponse({ ok: true });
          } catch (e) {
            sendResponse({ ok: false, error: String(e) });
          }
          break;
        }

        case 'CLEAR_API_QUEUE': {
          // サーバーの直接ダウンロードキューを全件削除する
          try {
            const base = await getServerUrl();
            const res = await fetchWithTimeout(
              `${base}/api/queue/clear`,
              { method: 'POST' },
              5000,
            );
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
            sendResponse({ ok: true, deleted: data.deleted });
          } catch (e) {
            sendResponse({ ok: false, error: String(e) });
          }
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
            const data = await res.json();
            // HTTP エラー (400, 503 等) はサービスワーカー側で ok:false に変換する
            if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
            sendResponse({ ok: true, result: data });
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

// ── 起動時 ────────────────────────────────────────────────────────────────────

flushQueue();
pollDownloadedIds();
pollDownloadedUrls();
