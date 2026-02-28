/**
 * x-keeper Chrome 拡張 — コンテンツスクリプト
 *
 * X (Twitter) / Pixiv のページに保存ボタンを注入し、
 * Service Worker 経由でダウンロード済み ID・URL をリアルタイム同期する。
 * HTTP 通信はすべてサービスワーカーに委譲 (chrome.runtime.sendMessage)。
 */

'use strict';

// ── ストレージキー定数 ────────────────────────────────────────────────────────

const KEY_SERVER       = 'xkeeper_server_url';
const KEY_QUEUED       = 'xkeeper_queued_ids';    // キューに追加済みの tweet ID (X 専用)
const KEY_QUEUED_URLS  = 'xkeeper_queued_urls';   // キューに追加済みの URL (X 以外のサイト用)
const KEY_QUEUED_ITEMS = 'xkeeper_queued_items';  // ポップアップ表示用メタデータ [{url, title}]
const DEFAULT_SERVER   = 'http://localhost:8989';

// ── ローカル状態 ──────────────────────────────────────────────────────────────

/** サーバーがダウンロード完了と報告した tweet ID のセット (Service Worker ポーリング経由で同期) */
let _downloadedIds = new Set();

/** サーバーがダウンロード完了と報告した URL のセット (Pixiv / Imgur 等 tweet_id なしサイト用) */
let _downloadedUrls = new Set();

/** このクライアントがキューに追加済みの tweet ID のセット (storage.local で永続化, X 専用) */
let _queuedIds = new Set();

/** このクライアントがキューに追加済みの URL のセット (storage.local で永続化, X 以外のサイト用) */
let _queuedUrls = new Set();

/**
 * Extension context invalidated フラグ。
 * 一度 true になると以降の chrome API 呼び出しを即座にスキップして
 * 警告ログの繰り返しを防ぐ。
 */
let _contextInvalidated = false;

// ── ストレージユーティリティ ──────────────────────────────────────────────────

async function getServerUrl() {
  const d = await storageGet(KEY_SERVER);
  return (d[KEY_SERVER] || DEFAULT_SERVER).replace(/\/$/, '');
}

/**
 * chrome.storage.local から値を読み取る。
 * Extension context が invalidated の場合は空オブジェクトを返す。
 */
async function storageGet(keys) {
  if (_contextInvalidated) return {};
  try {
    return await chrome.storage.local.get(keys);
  } catch (e) {
    _contextInvalidated = true;
    console.warn('[x-keeper] storage.get 失敗 — Extension context invalidated。ページをリロードしてください。');
    return {};
  }
}

/**
 * chrome.storage.local に値を書き込む。
 * Extension context が invalidated の場合は静かにスキップする。
 */
async function storageSet(items) {
  if (_contextInvalidated) return;
  try {
    await chrome.storage.local.set(items);
  } catch (e) {
    _contextInvalidated = true;
    console.warn('[x-keeper] storage.set 失敗 — Extension context invalidated。ページをリロードしてください。');
  }
}

/**
 * chrome.runtime.sendMessage のラッパー。
 * Extension context が invalidated の場合は null を返す（例外を握り潰す）。
 * chrome.runtime.sendMessage は context invalidated 時に同期的に throw するため、
 * storageGet/Set 同様に保護が必要。
 * @param {object} msg - Service Worker に送るメッセージ
 * @returns {Promise<any>} レスポンス、またはエラー時は null
 */
function runtimeSendMessage(msg) {
  if (_contextInvalidated) return Promise.resolve(null);
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage(msg, (res) => {
        if (chrome.runtime.lastError) {
          const errMsg = chrome.runtime.lastError.message || '';
          if (errMsg.includes('Extension context invalidated')) {
            if (!_contextInvalidated) {
              _contextInvalidated = true;
              console.warn('[x-keeper] Extension context invalidated — ページをリロードしてください。');
            }
          } else {
            console.warn('[x-keeper] sendMessage 失敗:', errMsg);
          }
          resolve(null);
          return;
        }
        resolve(res);
      });
    } catch (e) {
      if (!_contextInvalidated) {
        _contextInvalidated = true;
        console.warn('[x-keeper] Extension context invalidated — ページをリロードしてください。');
      }
      resolve(null);
    }
  });
}

/** キュー済みIDをストレージから読み込んでローカルセットを初期化する */
async function loadQueuedIds() {
  const d = await storageGet(KEY_QUEUED);
  _queuedIds = new Set(d[KEY_QUEUED] || []);
}

/** キュー済みIDをストレージに保存する */
async function saveQueuedIds() {
  await storageSet({ [KEY_QUEUED]: [..._queuedIds] });
}

/** キュー済みURLをストレージから読み込んでローカルセットを初期化する (X 以外のサイト用) */
async function loadQueuedUrls() {
  const d = await storageGet(KEY_QUEUED_URLS);
  _queuedUrls = new Set(d[KEY_QUEUED_URLS] || []);
}

/** キュー済みURLをストレージに保存する */
async function saveQueuedUrls() {
  await storageSet({ [KEY_QUEUED_URLS]: [..._queuedUrls] });
}

/**
 * ポップアップ表示用メタデータ ({url, title}) をストレージに追加する。
 * 同一 URL の重複追加はスキップする。
 * @param {string} url
 * @param {string} title - ポップアップで表示するページタイトル
 */
async function addQueuedItem(url, title) {
  const d = await storageGet(KEY_QUEUED_ITEMS);
  const items = d[KEY_QUEUED_ITEMS] || [];
  if (!items.some(i => i.url === url)) {
    items.push({ url, title });
    await storageSet({ [KEY_QUEUED_ITEMS]: items });
  }
}

/**
 * ダウンロード完了済みのアイテムを xkeeper_queued_items から削除する。
 * IDS_UPDATED / URLS_UPDATED 受信後に呼ぶ。
 * - X ツイート URL (/status/{id}): _queuedIds にない id は完了済み
 * - それ以外の URL: _queuedUrls にない URL は完了済み
 */
async function removeCompletedQueuedItems() {
  const d = await storageGet(KEY_QUEUED_ITEMS);
  const items = d[KEY_QUEUED_ITEMS] || [];
  const filtered = items.filter(i => {
    const m = i.url.match(/\/status\/(\d+)/);
    if (m) return _queuedIds.has(m[1]);
    return _queuedUrls.has(i.url);
  });
  if (filtered.length !== items.length) {
    await storageSet({ [KEY_QUEUED_ITEMS]: filtered });
  }
}

// ── ID / URL 同期 (Service Worker 経由) ──────────────────────────────────────

/**
 * Service Worker に GET_IDS メッセージを送りダウンロード済み ID を初期化する。
 *
 * content.js から直接 EventSource を使うと、HTTPS ページ (x.com 等) から
 * HTTP サーバーへの接続が Mixed Content としてブロックされる。
 * Service Worker は HTTP/HTTPS 問わず fetch できるため、ポーリングを委譲する。
 */
async function loadDownloadedIds() {
  console.log('[x-keeper] ダウンロード済み ID を Service Worker に要求中...');
  const res = await runtimeSendMessage({ type: 'GET_IDS' });
  if (!res || !res.ok) {
    console.warn('[x-keeper] GET_IDS レスポンス異常:', res);
    return;
  }
  _downloadedIds = new Set(res.ids);
  for (const id of _downloadedIds) _queuedIds.delete(id);
  console.log(`[x-keeper] ダウンロード済み ID: ${_downloadedIds.size} 件`);
  updateAllTweetBadges();
}

/**
 * Service Worker に GET_URLS メッセージを送り Pixiv / Imgur のダウンロード済み URL を初期化する。
 */
async function loadDownloadedUrls() {
  const res = await runtimeSendMessage({ type: 'GET_URLS' });
  if (!res || !res.ok) return;
  _downloadedUrls = new Set(res.urls);
  // 完了済み URL はキュー済みセットから除去する
  for (const url of _downloadedUrls) _queuedUrls.delete(url);
  updateFloatingBtnState();
  // Pixiv サムネイル一覧のバッジを更新する
  processPixivThumbnails();
}

// ── バッジ管理 (X / Twitter) ──────────────────────────────────────────────────

/** data-xk-tweet-id 属性から tweet ID を取得するヘルパー */
function getTweetId(article) {
  return article.dataset.xkTweetId || null;
}

/**
 * ページ上の全ツイートカードのバッジを現在の ID セットで再描画する。
 * MutationObserver コールバックや IDS_UPDATED 受信時に呼ぶ。
 */
function updateAllTweetBadges() {
  document.querySelectorAll('article[data-xk-tweet-id]').forEach((article) => {
    const id = getTweetId(article);
    if (id) applyBadgeState(article, id);
  });
  // メディア欄のグリッドバッジも同時に更新する
  document.querySelectorAll('[data-xk-grid-id]').forEach((el) => {
    applyGridBadge(el, el.dataset.xkGridId);
  });
}

/**
 * ツイートカードにバッジ状態を適用する。
 * - downloaded: 緑の ✓ バッジ (画像右下) + ボタンを緑に
 * - queued: 青の … バッジ (画像右下) + ボタンを青に
 * - none: バッジ削除 + ボタンをグレーに
 */
function applyBadgeState(article, tweetId) {
  const state = _downloadedIds.has(tweetId) ? 'downloaded'
              : _queuedIds.has(tweetId)     ? 'queued'
              : 'none';

  // 画像バッジの更新
  updateMediaBadges(article, state);

  // アクションバーボタンの色を更新
  const btn = article.querySelector('[data-xk-btn]');
  if (btn) {
    if (state === 'downloaded') {
      btn.style.color = '#00ba7c';
      btn.title = 'x-keeper — ダウンロード済み';
    } else if (state === 'queued') {
      btn.style.color = '#1d9bf0';
      btn.title = 'x-keeper — キュー済み';
    } else {
      btn.style.color = '#71767b';
      btn.title = 'x-keeper で保存';
    }
  }
}

/**
 * ツイートカード内の全メディア要素に状態バッジを付与する。
 * 既存のバッジ (.xk-badge) は先に削除して描き直す。
 */
function updateMediaBadges(article, state) {
  article.querySelectorAll('.xk-badge').forEach(el => el.remove());
  if (state === 'none') return;

  const color = state === 'downloaded' ? '#00ba7c' : '#1d9bf0';
  const label = state === 'downloaded' ? '✓' : '…';
  const title = state === 'downloaded' ? 'ダウンロード済み' : 'キュー済み';

  const containers = article.querySelectorAll(
    '[data-testid="tweetPhoto"], [data-testid="videoComponent"]'
  );
  for (const container of containers) {
    const badge = document.createElement('div');
    badge.className = 'xk-badge';
    badge.title = title;
    badge.style.cssText = [
      'position:absolute',
      'bottom:6px',
      'right:6px',
      'z-index:10',
      'width:22px',
      'height:22px',
      'border-radius:50%',
      `background:${color}`,
      'color:#fff',
      'font-size:13px',
      'font-weight:700',
      'display:flex',
      'align-items:center',
      'justify-content:center',
      'box-shadow:0 1px 4px rgba(0,0,0,.6)',
      'pointer-events:none',
      'line-height:1',
    ].join(';');
    badge.textContent = label;

    // container が position:static だと absolute が効かないので relative に変更
    if (getComputedStyle(container).position === 'static') {
      container.style.position = 'relative';
    }
    container.appendChild(badge);
  }
}

// ── バッジ管理 (メディア欄グリッド) ──────────────────────────────────────────

/**
 * メディア欄 (/username/media) のグリッドアイテムにバッジを重ねる。
 * 画像リンク要素 (a[href*="/status/"]) を対象にする。
 */
function applyGridBadge(linkEl, tweetId) {
  // DOM から切り離されている要素は操作しない (Extension context invalidated 対策)
  if (!linkEl || !document.contains(linkEl)) return;
  linkEl.querySelectorAll('.xk-grid-badge').forEach(el => el.remove());

  const state = _downloadedIds.has(tweetId) ? 'downloaded'
              : _queuedIds.has(tweetId)     ? 'queued'
              : 'none';
  if (state === 'none') return;

  const color = state === 'downloaded' ? '#00ba7c' : '#1d9bf0';
  const label = state === 'downloaded' ? '✓' : '…';
  const title = state === 'downloaded' ? 'ダウンロード済み' : 'キュー済み';

  const badge = document.createElement('div');
  badge.className = 'xk-grid-badge';
  badge.title = title;
  badge.style.cssText = [
    'position:absolute',
    'bottom:6px',
    'right:6px',
    'z-index:10',
    'width:22px',
    'height:22px',
    'border-radius:50%',
    `background:${color}`,
    'color:#fff',
    'font-size:13px',
    'font-weight:700',
    'display:flex',
    'align-items:center',
    'justify-content:center',
    'box-shadow:0 1px 4px rgba(0,0,0,.6)',
    'pointer-events:none',
    'line-height:1',
  ].join(';');
  badge.textContent = label;

  if (getComputedStyle(linkEl).position === 'static') {
    linkEl.style.position = 'relative';
  }
  linkEl.appendChild(badge);
}

/**
 * メディア欄グリッドの各リンク要素を処理してバッジを付ける。
 * MutationObserver から定期的に呼ばれる。
 * /username/media ページのみで呼ばれることを前提とする。
 */
function processMediaGridItems() {
  // メディア欄では各メディアが <a href="/username/status/TWEETID"> で囲まれる
  // article[data-testid="tweet"] の内部リンクは通常のタイムライン処理が担当するため除外する
  document.querySelectorAll('a[href*="/status/"]:not([data-xk-grid-id])').forEach((a) => {
    // タイムラインの article 内リンクはタイムライン処理が担当するためスキップする
    if (a.closest('article[data-testid="tweet"]')) return;
    // pbs.twimg.com 画像または動画を含む場合のみ処理する
    if (!a.querySelector('img[src*="pbs.twimg.com"]') &&
        !a.querySelector('video') &&
        !a.querySelector('[data-testid="videoComponent"]')) return;

    const href = a.getAttribute('href') || '';
    const m = href.match(/\/status\/(\d+)/);
    if (!m) return;

    const tweetId = m[1];
    a.dataset.xkGridId = tweetId;

    // 右下にダウンロードボタンを追加する (バッジとは別の操作ボタン)
    if (!a.querySelector('.xk-grid-btn')) {
      const btn = document.createElement('button');
      btn.className = 'xk-grid-btn';
      btn.title = 'x-keeper で保存';
      btn.style.cssText = [
        'position:absolute',
        'top:6px',
        'left:6px',
        'z-index:11',
        'width:26px',
        'height:26px',
        'border-radius:50%',
        'border:none',
        'background:rgba(15,20,25,.75)',
        'color:#fff',
        'font-size:14px',
        'display:flex',
        'align-items:center',
        'justify-content:center',
        'cursor:pointer',
        'box-shadow:0 1px 4px rgba(0,0,0,.5)',
        'opacity:0',
        'transition:opacity .15s',
        'line-height:1',
      ].join(';');
      btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M12 16l-5-5 1.4-1.4 2.6 2.6V4h2v8.2l2.6-2.6L17 11l-5 5zm-6 4v-2h12v2H6z"/></svg>';
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        e.preventDefault();
        const tweetUrl = `https://x.com${href.split('?')[0]}`;
        queueUrl(tweetUrl, null, tweetId);
        // キュー後はバッジを即時更新する
        applyGridBadge(a, tweetId);
      });
      // 親コンテナのホバーでボタンを表示する
      const parent = a.parentElement;
      if (parent) {
        parent.addEventListener('mouseenter', () => { btn.style.opacity = '1'; });
        parent.addEventListener('mouseleave', () => { btn.style.opacity = '0'; });
      }
      if (getComputedStyle(a).position === 'static') a.style.position = 'relative';
      a.appendChild(btn);
    }

    applyGridBadge(a, tweetId);
  });
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function toast(msg, isError) {
  const el = document.createElement('div');
  const bg = isError ? '#ef4444' : '#1d9bf0';
  el.style.cssText = [
    'position:fixed',
    'bottom:20px',
    'left:50%',
    'transform:translateX(-50%)',
    'z-index:2147483647',
    'padding:10px 18px',
    'border-radius:8px',
    `background:${bg}`,
    'color:#fff',
    'font-size:13px',
    'font-weight:600',
    'box-shadow:0 4px 12px rgba(0,0,0,.4)',
    'transition:opacity .3s',
    'pointer-events:none',
    'white-space:nowrap',
  ].join(';');
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 2500);
}

// ── キュー送信 ────────────────────────────────────────────────────────────────

/**
 * URL をサービスワーカー経由でサーバーのダウンロードキューに追加する。
 * tweet_id が取得できた場合はキュー済み状態を即時反映する。
 * runtimeSendMessage を使用して Extension context invalidated 時の Uncaught Error を防止する。
 */
async function queueUrl(url, btn, tweetId) {
  if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }

  // ポップアップ表示用タイトル: ページタイトルをそのまま使う
  const itemTitle = document.title || url;

  // キュー済み状態を即時反映（サーバー応答を待たない）
  if (tweetId) {
    // X: tweet_id ベースのバッジ状態更新
    _queuedIds.add(tweetId);
    saveQueuedIds();
    addQueuedItem(url, itemTitle);
    const article = btn?.closest('article[data-xk-tweet-id]');
    if (article) applyBadgeState(article, tweetId);
  } else {
    // X 以外のサイト (Pixiv 等): URL ベースのキュー済み状態管理
    _queuedUrls.add(url);
    saveQueuedUrls();
    addQueuedItem(url, itemTitle);
    updateFloatingBtnState();
  }

  const res = await runtimeSendMessage({ type: 'QUEUE_URL', url });
  if (!res) {
    toast('拡張機能を再読み込みしてください', true);
    if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
    return;
  }
  if (res.ok) {
    toast('x-keeper にキューを追加しました ✓');
  } else {
    toast('サーバー未接続。次回接続時に送信します', true);
  }
  if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
}

// ── Pixiv サムネイルバッジ ─────────────────────────────────────────────────────

/**
 * Pixiv ページ (検索結果・ユーザー作品一覧等) の artwork サムネイルリンクに
 * ダウンロード済みバッジを付与する。
 *
 * Pixiv は React SPA のため MutationObserver で DOM 追加を検知して呼ぶ。
 * 対象: a[href*="/artworks/"] で img を含む要素 (カードサムネイル)
 * 除外: data-xk-pixiv-id が付いたもの (処理済み) と現在開いているページ自体
 */
function processPixivThumbnails() {
  document.querySelectorAll('a[href*="/artworks/"]:not([data-xk-pixiv-id])').forEach((a) => {
    // img のないリンク (テキストリンク等) は対象外
    if (!a.querySelector('img')) return;

    const href = a.getAttribute('href') || '';
    const m = href.match(/\/artworks\/(\d+)/);
    if (!m) return;

    const artworkId = m[1];
    a.dataset.xkPixivId = artworkId;

    // ダウンロード済みURL形式: https://www.pixiv.net/artworks/{id}
    const canonicalUrl = `https://www.pixiv.net/artworks/${artworkId}`;
    if (!_downloadedUrls.has(canonicalUrl)) return;

    // 既存バッジがあれば何もしない
    if (a.querySelector('.xk-pixiv-badge')) return;

    const badge = document.createElement('div');
    badge.className = 'xk-pixiv-badge';
    badge.title = 'x-keeper — ダウンロード済み';
    badge.style.cssText = [
      'position:absolute',
      'top:4px',
      'left:4px',
      'z-index:10',
      'width:22px',
      'height:22px',
      'border-radius:50%',
      'background:#00ba7c',
      'color:#fff',
      'font-size:13px',
      'font-weight:700',
      'display:flex',
      'align-items:center',
      'justify-content:center',
      'box-shadow:0 1px 4px rgba(0,0,0,.6)',
      'pointer-events:none',
      'line-height:1',
    ].join(';');
    badge.textContent = '✓';

    if (getComputedStyle(a).position === 'static') {
      a.style.position = 'relative';
    }
    a.appendChild(badge);
  });
}

// ── フローティングボタン ──────────────────────────────────────────────────────

const FAB_ID = 'xkeeper-fab';

function setFloatingBtn(label, color, onClick) {
  document.getElementById(FAB_ID)?.remove();

  const btn = document.createElement('button');
  btn.id = FAB_ID;
  btn.style.cssText = [
    'position:fixed',
    'bottom:80px',
    'right:16px',
    'z-index:2147483646',
    'display:inline-flex',
    'align-items:center',
    'gap:6px',
    'padding:10px 16px',
    'border:none',
    'border-radius:9999px',
    `background:${color}`,
    'color:#fff',
    'font-size:13px',
    'font-weight:700',
    'cursor:pointer',
    'box-shadow:0 2px 12px rgba(0,0,0,.4)',
    'transition:opacity .15s,transform .15s',
    'line-height:1',
  ].join(';');
  btn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 16l-5-5 1.4-1.4 2.6 2.6V4h2v8.2l2.6-2.6L17 11l-5 5zm-6 4v-2h12v2H6z"/></svg><span>${label}</span>`;
  btn.addEventListener('mouseenter', () => { btn.style.opacity = '0.85'; btn.style.transform = 'scale(1.04)'; });
  btn.addEventListener('mouseleave', () => { btn.style.opacity = '1'; btn.style.transform = ''; });
  btn.addEventListener('click', (e) => { e.stopPropagation(); onClick(btn); });
  document.body.appendChild(btn);
}

function removeFloatingBtn() {
  document.getElementById(FAB_ID)?.remove();
}

// ── X (Twitter) ──────────────────────────────────────────────────────────────

/** article 内の /username/status/ID 形式リンクから tweet URL と tweet ID を取得する */
function tweetInfoFromArticle(article) {
  for (const a of article.querySelectorAll('a[href]')) {
    const href = a.getAttribute('href') || '';
    const m = href.match(/^\/\w+\/status\/(\d+)$/);
    if (m) return { url: `https://x.com${href}`, id: m[1] };
  }
  return null;
}

/** ツイートに画像または動画が含まれているか */
function hasMedia(article) {
  return !!(
    article.querySelector('[data-testid="tweetPhoto"]') ||
    article.querySelector('[data-testid="videoComponent"]') ||
    article.querySelector('[data-testid="videoPlayer"]') ||
    article.querySelector('img[src*="pbs.twimg.com/media/"]')
  );
}

/** タイムラインのツイートカードにダウンロードボタンとバッジを追加する */
function addTweetCardBtn(article) {
  if (article.dataset.xk) return;
  if (!hasMedia(article)) return;
  const info = tweetInfoFromArticle(article);
  if (!info) return;

  // reply / like が含まれる group をアクションバーとして選択する
  let bar = null;
  for (const g of article.querySelectorAll('[role="group"]')) {
    if (g.querySelector('[data-testid="reply"]') || g.querySelector('[data-testid="like"]')) {
      bar = g; break;
    }
  }
  if (!bar) bar = article.querySelector('[role="group"]');
  if (!bar) return;

  article.dataset.xk = '1';
  // tweet ID を article に記録して後からバッジ操作に使えるようにする
  article.dataset.xkTweetId = info.id;

  const btn = document.createElement('button');
  btn.dataset.xkBtn = '1';
  btn.title = 'x-keeper で保存';
  btn.style.cssText = [
    'display:inline-flex',
    'align-items:center',
    'padding:0 12px',
    'height:38px',
    'border:none',
    'border-radius:9999px',
    'background:transparent',
    'color:#71767b',
    'cursor:pointer',
    'gap:4px',
    'transition:background .15s,color .15s',
    'flex-shrink:0',
  ].join(';');
  btn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 16l-5-5 1.4-1.4 2.6 2.6V4h2v8.2l2.6-2.6L17 11l-5 5zm-6 4v-2h12v2H6z"/></svg>`;
  btn.addEventListener('mouseenter', () => {
    if (!_downloadedIds.has(info.id) && !_queuedIds.has(info.id)) {
      btn.style.background = 'rgba(29,155,240,.1)';
      btn.style.color = '#1d9bf0';
    }
  });
  btn.addEventListener('mouseleave', () => {
    btn.style.background = 'transparent';
    // ホバー解除後は現在の状態に合わせた色に戻す
    applyBadgeState(article, info.id);
  });
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    e.preventDefault();
    queueUrl(info.url, btn, info.id);
  });
  bar.appendChild(btn);

  // 初回表示時にバッジ状態を適用する
  applyBadgeState(article, info.id);
}

function onXNavigate() {
  const path = location.pathname;
  removeFloatingBtn();

  // /username/status/TWEETID
  const sm = path.match(/^\/([^/]+)\/status\/(\d+)/);
  if (sm) {
    setFloatingBtn('このツイートを保存', '#1d9bf0', (btn) =>
      queueUrl(`https://x.com/${sm[1]}/status/${sm[2]}`, btn, sm[2])
    );
    return;
  }

  // /username/media — 全メディア一括保存ボタン (個別バッジは MutationObserver が担当)
  const mm = path.match(/^\/([^/]+)\/media$/);
  if (mm) {
    setFloatingBtn('全メディアを保存', '#1d9bf0', (btn) =>
      queueUrl(`https://x.com/${mm[1]}/media`, btn, null)
    );
  }
}

function setupXTwitter() {
  // サービスワーカーからのメッセージを受信して UI を更新する
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'NAVIGATE') onXNavigate();
    // Service Worker からの ID 更新通知: バッジを再描画しキュー済みアイテムを削除する
    if (msg.type === 'IDS_UPDATED') {
      _downloadedIds = new Set(msg.ids);
      for (const id of _downloadedIds) _queuedIds.delete(id);
      updateAllTweetBadges();
      saveQueuedIds();
      removeCompletedQueuedItems();
    }
  });

  // popstate (ブラウザ戻る/進む)
  window.addEventListener('popstate', onXNavigate);

  // タイムライン上のツイートカード + メディア欄グリッドアイテムを監視
  new MutationObserver(() => {
    document.querySelectorAll('article[data-testid="tweet"]:not([data-xk])').forEach(addTweetCardBtn);
    // メディア欄 (/username/media) でのグリッドバッジ処理
    if (/^\/[^/]+\/media$/.test(location.pathname)) {
      processMediaGridItems();
    }
  }).observe(document.body, { childList: true, subtree: true });

  onXNavigate();
}

// ── Pixiv ─────────────────────────────────────────────────────────────────────

/**
 * 現在のPixivページのURLと状態を見てフローティングボタンを更新する。
 * downloaded > queued > none の優先順位で表示する。
 */
function updateFloatingBtnState() {
  if (!/\/artworks\/\d+/.test(location.pathname)) return;
  const url = location.href.split('?')[0];

  if (_downloadedUrls.has(url)) {
    // ダウンロード済み: 緑でクリック不可 (再ダウンロードは不要)
    setFloatingBtn('ダウンロード済み ✓', '#00ba7c', () => {});
  } else if (_queuedUrls.has(url)) {
    // キュー済み: 青で表示
    setFloatingBtn('キュー済み …', '#1d9bf0', (btn) => queueUrl(url, btn, null));
  } else {
    // 未保存: デフォルト色
    setFloatingBtn('x-keeper で保存', '#0096fa', (btn) => queueUrl(url, btn, null));
  }
}

function onPixivNavigate() {
  removeFloatingBtn();
  if (!/\/artworks\/\d+/.test(location.pathname)) return;
  updateFloatingBtnState();
}

function setupPixiv() {
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'NAVIGATE') setTimeout(onPixivNavigate, 80);
    // Service Worker からの URL 更新通知: ボタン状態とサムネイルバッジを再描画しキュー済みアイテムを削除する
    if (msg.type === 'URLS_UPDATED') {
      _downloadedUrls = new Set(msg.urls);
      for (const url of _downloadedUrls) _queuedUrls.delete(url);
      saveQueuedUrls();
      updateFloatingBtnState();
      processPixivThumbnails();
      removeCompletedQueuedItems();
    }
  });
  window.addEventListener('popstate', onPixivNavigate);

  // Pixiv は SPA のため DOM 変化を監視してサムネイルバッジを随時付与する
  new MutationObserver(() => {
    processPixivThumbnails();
  }).observe(document.body, { childList: true, subtree: true });

  onPixivNavigate();
}

// ── 初期化 ────────────────────────────────────────────────────────────────────

(async function init() {
  const host = location.hostname;

  // キュー済み ID / URL をストレージから復元
  await loadQueuedIds();
  await loadQueuedUrls();

  if (host === 'x.com' || host === 'twitter.com') {
    // ダウンロード済み ID を Service Worker 経由で取得してからページ構築
    loadDownloadedIds();
    setupXTwitter();
  } else if (host === 'www.pixiv.net') {
    // ダウンロード済み URL を Service Worker 経由で取得してからボタン表示
    loadDownloadedUrls();
    setupPixiv();
  }
})();
