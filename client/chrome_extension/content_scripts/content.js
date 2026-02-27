/**
 * x-keeper Chrome 拡張 — コンテンツスクリプト
 *
 * X (Twitter) / Pixiv のページに保存ボタンを注入し、
 * サーバーの SSE エンドポイントからダウンロード済み ID をリアルタイム同期する。
 * HTTP 通信はすべてサービスワーカーに委譲 (chrome.runtime.sendMessage)。
 */

'use strict';

// ── ストレージキー定数 ────────────────────────────────────────────────────────

const KEY_SERVER = 'xkeeper_server_url';
const KEY_QUEUED = 'xkeeper_queued_ids';   // このクライアントがキューに追加したツイートID
const DEFAULT_SERVER = 'http://localhost:8989';

// ── ローカル状態 ──────────────────────────────────────────────────────────────

/** サーバーがダウンロード完了と報告した tweet ID のセット (SSE で同期) */
let _downloadedIds = new Set();

/** このクライアントがキューに追加済みの tweet ID のセット (storage.local で永続化) */
let _queuedIds = new Set();

/** 現在のSSE接続 */
let _eventSource = null;

/** SSE再接続タイマー */
let _reconnectTimer = null;

// ── ストレージユーティリティ ──────────────────────────────────────────────────

async function getServerUrl() {
  const d = await chrome.storage.local.get(KEY_SERVER);
  return (d[KEY_SERVER] || DEFAULT_SERVER).replace(/\/$/, '');
}

/** キュー済みIDをストレージから読み込んでローカルセットを初期化する */
async function loadQueuedIds() {
  const d = await chrome.storage.local.get(KEY_QUEUED);
  _queuedIds = new Set(d[KEY_QUEUED] || []);
}

/** キュー済みIDをストレージに保存する */
async function saveQueuedIds() {
  await chrome.storage.local.set({ [KEY_QUEUED]: [..._queuedIds] });
}

// ── SSE 同期 ──────────────────────────────────────────────────────────────────

/**
 * サーバーの SSE エンドポイントに接続してダウンロード済み ID を同期する。
 * - 接続時: 全IDリスト (snapshot イベント) を受信してローカルセットを初期化
 * - 以後: 新規追加分 (update イベント) を随時受信
 * - 切断時: 5秒後に自動再接続
 */
async function connectSSE() {
  if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
  if (_eventSource) { _eventSource.close(); _eventSource = null; }

  const base = await getServerUrl();
  const es = new EventSource(`${base}/api/history/stream`);
  _eventSource = es;

  es.addEventListener('snapshot', (e) => {
    _downloadedIds = new Set(JSON.parse(e.data));
    // ダウンロード完了済みIDはキュー済みセットから削除する
    for (const id of _downloadedIds) _queuedIds.delete(id);
    updateAllTweetBadges();
  });

  es.addEventListener('update', (e) => {
    const newIds = JSON.parse(e.data);
    for (const id of newIds) {
      _downloadedIds.add(id);
      _queuedIds.delete(id);  // ダウンロード完了 → キュー済みから昇格
    }
    updateBadgesForIds(new Set(newIds));
    // キュー済みセットが変化したのでストレージも更新
    saveQueuedIds();
  });

  es.onerror = () => {
    es.close();
    _eventSource = null;
    _reconnectTimer = setTimeout(connectSSE, 5000);
  };
}

// ── バッジ管理 ────────────────────────────────────────────────────────────────

/** data-xk-tweet-id 属性から tweet ID を取得するヘルパー */
function getTweetId(article) {
  return article.dataset.xkTweetId || null;
}

/**
 * ページ上の全ツイートカードのバッジを現在の ID セットで再描画する。
 * MutationObserver コールバックや SSE snapshot 受信時に呼ぶ。
 */
function updateAllTweetBadges() {
  document.querySelectorAll('article[data-xk-tweet-id]').forEach((article) => {
    const id = getTweetId(article);
    if (id) applyBadgeState(article, id);
  });
}

/**
 * 指定 ID セットに対応するツイートカードのバッジを更新する。
 * SSE update イベント受信時に呼ぶ（全件更新より軽量）。
 */
function updateBadgesForIds(ids) {
  for (const id of ids) {
    const article = document.querySelector(`article[data-xk-tweet-id="${id}"]`);
    if (article) applyBadgeState(article, id);
  }
}

/**
 * ツイートカードにバッジ状態を適用する。
 * - downloaded: 緑の ✓ バッジ (画像右下) + ボタンを緑に
 * - queued: 青の ⋯ バッジ (画像右下) + ボタンを青に
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
 */
function queueUrl(url, btn, tweetId) {
  if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }

  // キュー済み状態を即時反映（サーバー応答を待たない）
  if (tweetId) {
    _queuedIds.add(tweetId);
    saveQueuedIds();
    const article = btn?.closest('article[data-xk-tweet-id]');
    if (article) applyBadgeState(article, tweetId);
  }

  chrome.runtime.sendMessage({ type: 'QUEUE_URL', url }, (res) => {
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

  // /username/media
  const mm = path.match(/^\/([^/]+)\/media$/);
  if (mm) {
    setFloatingBtn('全メディアを保存', '#1d9bf0', (btn) =>
      queueUrl(`https://x.com/${mm[1]}/media`, btn, null)
    );
  }
}

function setupXTwitter() {
  // サービスワーカーからの NAVIGATE メッセージを受信して UI を更新する
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'NAVIGATE') onXNavigate();
  });

  // popstate (ブラウザ戻る/進む)
  window.addEventListener('popstate', onXNavigate);

  // タイムライン上のツイートカード監視
  new MutationObserver(() => {
    document.querySelectorAll('article[data-testid="tweet"]:not([data-xk])').forEach(addTweetCardBtn);
  }).observe(document.body, { childList: true, subtree: true });

  onXNavigate();
}

// ── Pixiv ─────────────────────────────────────────────────────────────────────

function onPixivNavigate() {
  removeFloatingBtn();
  if (!/\/artworks\/\d+/.test(location.pathname)) return;
  const url = location.href.split('?')[0];
  setFloatingBtn('x-keeper で保存', '#0096fa', (btn) => queueUrl(url, btn, null));
}

function setupPixiv() {
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'NAVIGATE') setTimeout(onPixivNavigate, 80);
  });
  window.addEventListener('popstate', onPixivNavigate);
  onPixivNavigate();
}

// ── 初期化 ────────────────────────────────────────────────────────────────────

(async function init() {
  const host = location.hostname;

  // キュー済みIDをストレージから復元
  await loadQueuedIds();

  if (host === 'x.com' || host === 'twitter.com') {
    // SSE 接続を開始してからページ構築
    connectSSE();
    setupXTwitter();
  } else if (host === 'www.pixiv.net') {
    setupPixiv();
  }
})();
