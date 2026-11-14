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
const KEY_TOKEN      = 'xkeeper_api_token';     // サーバーの API_TOKEN と一致させる簡易永続トークン
const KEY_QUEUE      = 'xkeeper_offline_queue';
const KEY_RESULT_LOG = 'xkeeper_result_log';   // ダウンロードキュー結果の履歴
const DEFAULT_SERVER = 'http://localhost:8989';
const MAX_RESULT_LOG = 50;                     // 保持する最大件数

// ── ストレージ (storage.local: sync より安定、Chrome アカウント不要) ──────────

async function getServerUrl() {
  const d = await chrome.storage.local.get(KEY_SERVER);
  return (d[KEY_SERVER] || DEFAULT_SERVER).replace(/\/$/, '');
}

/** 保存済み API トークン (未設定なら空文字) */
async function getApiToken() {
  const d = await chrome.storage.local.get(KEY_TOKEN);
  return (d[KEY_TOKEN] || '').trim();
}

/**
 * 入力されたサーバー URL を正規化する。
 * scheme 補完 → 末尾スラッシュ除去。http/https 以外や不正な URL は null を返す。
 */
function normalizeServerUrl(raw) {
  let s = (raw || '').trim();
  if (!s) return null;
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(s)) s = `http://${s}`;
  try {
    const u = new URL(s);
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
    return `${u.origin}${u.pathname.replace(/\/+$/, '')}`;
  } catch {
    return null;
  }
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

/**
 * サーバー API への fetch。保存済みトークンがあれば X-API-Token を付与する。
 * (サーバーが API_TOKEN 未設定ならヘッダーは無視されるので後方互換)
 */
async function apiFetch(path, options = {}, ms = 5000) {
  const base  = await getServerUrl();
  const token = await getApiToken();
  const headers = { ...(options.headers || {}) };
  if (token) headers['X-API-Token'] = token;
  return fetchWithTimeout(`${base}${path}`, { ...options, headers }, ms);
}

async function postUrls(urls) {
  const res  = await apiFetch('/api/queue', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ urls }),
  }, 5000);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    // 4xx は恒久的な拒否 (非対応 URL / トークン不一致)。オフラインキューには入れない。
    const err = new Error(data.error || `HTTP ${res.status}`);
    err.status   = res.status;
    err.rejected = data.rejected || [];
    throw err;
  }
  return data;
}

async function checkHealth() {
  try {
    const res = await apiFetch('/api/health', {}, 3000);
    return res.status === 200;
  } catch {
    return false;
  }
}

// ── 送信デデュープ / バッジ通知 ────────────────────────────────────────────────

/**
 * 同一タブ + 同一 URL の短期再送を抑止する。
 * onUpdated(complete) と onActivated の連続発火や二度押しがこの経路に来る。
 */
const DEDUPE_TTL_MS = 5000;
const _recentSends  = new Map();   // `${tabId}|${url}` -> timestamp

function isDuplicateSend(tabId, url) {
  const now = Date.now();
  for (const [key, ts] of _recentSends) {
    if (now - ts > DEDUPE_TTL_MS) _recentSends.delete(key);
  }
  const key = `${tabId ?? '-'}|${url}`;
  if (_recentSends.has(key)) return true;
  _recentSends.set(key, now);
  return false;
}

/** 送信結果をタブのバッジで通知する (OK / ! を 3 秒表示) */
async function flashBadge(tabId, ok) {
  if (typeof tabId !== 'number') return;
  try {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: ok ? '#166534' : '#7f1d1d' });
    await chrome.action.setBadgeText({ tabId, text: ok ? 'OK' : '!' });
    setTimeout(() => {
      chrome.action.setBadgeText({ tabId, text: '' }).catch(() => {});
    }, 3000);
  } catch {
    // タブが閉じられた等: 通知できなくても処理は続行する
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
    // まずカウントだけ確認して変化がなければ早期リターン (転送量節約)
    const countRes = await apiFetch('/api/history/count', {}, 3000);
    if (countRes.status !== 200) return;
    const { count } = await countRes.json();
    if (count === _cachedCount) return;

    // 変化あり: 全 ID を取得
    const idsRes = await apiFetch('/api/history/ids', {}, 10000);
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
    const countRes = await apiFetch('/api/history/urls/count', {}, 3000);
    if (countRes.status !== 200) return;
    const { count } = await countRes.json();
    if (count === _cachedUrlCount) return;

    const urlsRes = await apiFetch('/api/history/urls', {}, 10000);
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

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    try {
      switch (msg.type) {

        case 'QUEUE_URL': {
          const urls  = [].concat(msg.url);
          const tabId = sender?.tab?.id;
          // 同一タブ + 同一 URL の短期再送を抑止する
          if (urls.length === 1 && isDuplicateSend(tabId, urls[0])) {
            flashBadge(tabId, true);
            sendResponse({ ok: true, duplicate: true, data: { accepted: urls, rejected: [] } });
            break;
          }
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
            flashBadge(tabId, true);
            sendResponse({ ok: true, data });
          } catch (e) {
            const permanent = typeof e.status === 'number' && e.status >= 400 && e.status < 500;
            if (permanent) {
              // 非対応 URL / トークン不一致: 再送しても通らないのでオフラインキューに入れない
              await appendResultLog({
                ts: new Date().toISOString(),
                status: 'rejected',
                urls,
                error: e.message,
                rejected: e.rejected || [],
              });
              flashBadge(tabId, false);
              sendResponse({ ok: false, error: e.message, rejected: e.rejected || [] });
              break;
            }
            for (const u of urls) await enqueueOffline(u);
            // オフラインキュー保存を結果ログに記録
            await appendResultLog({
              ts: new Date().toISOString(),
              status: 'offline',
              urls,
            });
            flashBadge(tabId, false);
            sendResponse({ ok: false, error: String(e), offline: true });
          }
          break;
        }

        case 'FLUSH_QUEUE':
          await flushQueue();
          sendResponse({ ok: true, queue: await getQueue() });
          break;

        case 'GET_STATUS': {
          const [online, queue, serverUrl, apiToken, logData] = await Promise.all([
            checkHealth(), getQueue(), getServerUrl(), getApiToken(),
            chrome.storage.local.get(KEY_RESULT_LOG),
          ]);
          // オンライン時のみ履歴件数とサーバー処理ログを取得する
          let historyCount = null;
          let authOk = null;   // null = 未判定, false = トークン不一致 (401)
          let serverLogs = [];
          let apiQueue = [];
          if (online) {
            try {
              const r = await apiFetch('/api/history/count', {}, 3000);
              if (r.status === 200) {
                historyCount = (await r.json()).count ?? null;
                authOk = true;
              } else if (r.status === 401) {
                authOk = false;
              }
            } catch { /* ignore */ }
            try {
              const r = await apiFetch('/api/logs/recent', {}, 3000);
              if (r.status === 200) serverLogs = await r.json();
            } catch { /* ignore */ }
            try {
              const r = await apiFetch('/api/queue/status', {}, 3000);
              if (r.status === 200) apiQueue = await r.json();
            } catch { /* ignore */ }
          }
          const resultLog = logData[KEY_RESULT_LOG] || [];
          sendResponse({
            ok: true, online, queue, serverUrl, apiToken, authOk,
            historyCount, resultLog, serverLogs, apiQueue,
          });
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
          const url = normalizeServerUrl(msg.url);
          if (!url) {
            sendResponse({ ok: false, error: 'URL が不正です (http:// または https:// のみ)' });
            break;
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

        case 'SET_API_TOKEN': {
          const token = (msg.token || '').trim();
          await chrome.storage.local.set({ [KEY_TOKEN]: token });
          // 設定直後に新トークンで疎通を確かめる (401 ならトークン不一致)
          const online = await checkHealth();
          sendResponse({ ok: true, hasToken: !!token, online });
          break;
        }

        case 'DELETE_API_QUEUE_ITEM': {
          // サーバーの直接ダウンロードキューから指定 URL を削除する
          try {
            const res = await apiFetch(
              '/api/queue/item',
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
            const res = await apiFetch('/api/queue/clear', { method: 'POST' }, 5000);
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
            const res = await apiFetch('/api/history/export', {}, 10000);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            sendResponse({ ok: true, data: await res.text() });
          } catch (e) {
            sendResponse({ ok: false, error: String(e) });
          }
          break;
        }

        case 'IMPORT_HISTORY': {
          try {
            const res = await apiFetch(
              '/api/history/import',
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
  // content script 未注入のページ (chrome:// 等) では失敗するが、想定内なので無視する
  chrome.tabs.sendMessage(details.tabId, { type: 'NAVIGATE', url: details.url })
    .catch(() => {});
});

// ── 右クリックメニュー ───────────────────────────────────────────────────────

const MENU_SEND_PAGE = 'xkeeper-send-page';

// 拡張のインストール/更新時に作り直す (removeAll で重複作成を防ぐ)
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create(
      { id: MENU_SEND_PAGE, title: 'このページを x-keeper に送る', contexts: ['page', 'link'] },
      () => void chrome.runtime.lastError,   // 重複作成エラーは無視する
    );
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== MENU_SEND_PAGE) return;
  const url = info.linkUrl || info.pageUrl;
  if (!url) return;
  // QUEUE_URL と同じ経路 (デデュープ・結果ログ・バッジ通知)
  const res = await chrome.runtime.sendMessage({ type: 'QUEUE_URL', url }).catch(() => null);
  flashBadge(tab?.id, !!res?.ok);
});

// ── 起動時 ────────────────────────────────────────────────────────────────────

flushQueue();
pollDownloadedIds();
pollDownloadedUrls();
