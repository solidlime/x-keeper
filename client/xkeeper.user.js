// ==UserScript==
// @name         x-keeper Client
// @namespace    https://github.com/solidlime/x-keeper
// @version      1.1.0
// @description  X (Twitter) / Pixiv のメディアを x-keeper サーバーに送信してダウンロードする
// @match        https://x.com/*
// @match        https://twitter.com/*
// @match        https://www.pixiv.net/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @connect      *
// ==/UserScript==

'use strict';

// ── 設定 ──────────────────────────────────────────────────────────────────────

const KEY_SERVER = 'xkeeper_server_url';
const KEY_QUEUE = 'xkeeper_offline_queue';
const DEFAULT_SERVER = 'http://localhost:8989';

function serverUrl() {
  return (GM_getValue(KEY_SERVER, DEFAULT_SERVER) || DEFAULT_SERVER).replace(/\/$/, '');
}

function offlineQueue() {
  try { return JSON.parse(GM_getValue(KEY_QUEUE, '[]') || '[]'); }
  catch { return []; }
}

function saveQueue(q) { GM_setValue(KEY_QUEUE, JSON.stringify(q)); }

function enqueueOffline(url) {
  const q = offlineQueue();
  if (!q.includes(url)) { q.push(url); saveQueue(q); }
}

// ── HTTP ──────────────────────────────────────────────────────────────────────

function postUrls(urls, onOk, onErr) {
  GM_xmlhttpRequest({
    method: 'POST',
    url: `${serverUrl()}/api/queue`,
    headers: { 'Content-Type': 'application/json' },
    data: JSON.stringify({ urls: [].concat(urls) }),
    timeout: 5000,
    onload: (r) => r.status === 202 ? onOk(JSON.parse(r.responseText)) : onErr(new Error(`HTTP ${r.status}`)),
    onerror: onErr,
    ontimeout: () => onErr(new Error('timeout')),
  });
}

function checkHealth(cb) {
  GM_xmlhttpRequest({
    method: 'GET',
    url: `${serverUrl()}/api/health`,
    timeout: 3000,
    onload: (r) => cb(r.status === 200),
    onerror: () => cb(false),
    ontimeout: () => cb(false),
  });
}

// ── オフラインキュー ──────────────────────────────────────────────────────────

function flushQueue() {
  const q = offlineQueue();
  if (!q.length) return;
  postUrls(q,
    (d) => { console.log(`[x-keeper] オフラインキュー送信: ${d.accepted.length} 件`); saveQueue([]); },
    (e) => console.warn('[x-keeper] オフラインキュー送信失敗:', e)
  );
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function toast(msg, isError) {
  const el = document.createElement('div');
  el.style.cssText = `position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:2147483647;padding:10px 18px;border-radius:8px;background:${isError ? '#ef4444' : '#1d9bf0'};color:#fff;font-size:13px;font-weight:600;box-shadow:0 4px 12px rgba(0,0,0,.4);transition:opacity .3s;pointer-events:none;white-space:nowrap;`;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 2500);
}

// ── キュー送信 ────────────────────────────────────────────────────────────────

function queueUrl(url, btn) {
  const urls = [].concat(url);
  if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }
  postUrls(urls,
    () => {
      toast('x-keeper にキューを追加しました ✓');
      if (btn) { btn.disabled = false; btn.style.opacity = '1'; btn.style.color = '#00ba7c'; }
      flushQueue();
    },
    (e) => {
      urls.forEach(enqueueOffline);
      toast('サーバー未接続。次回接続時に送信します', true);
      if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
      console.warn('[x-keeper] 送信失敗:', e);
    }
  );
}

// ── フローティングボタン ──────────────────────────────────────────────────────
// DOM に依存せず確実に表示されるよう position:fixed で実装する。

const FAB_ID = 'xkeeper-fab';

function makeFloatingBtn(label, color, onClick) {
  const btn = document.createElement('button');
  btn.id = FAB_ID;
  btn.style.cssText = `position:fixed;bottom:80px;right:16px;z-index:2147483646;display:inline-flex;align-items:center;gap:6px;padding:10px 16px;border:none;border-radius:9999px;background:${color};color:#fff;font-size:13px;font-weight:700;cursor:pointer;box-shadow:0 2px 12px rgba(0,0,0,.4);transition:opacity .15s,transform .15s;`;
  btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 16l-5-5 1.4-1.4 2.6 2.6V4h2v8.2l2.6-2.6L17 11l-5 5zm-6 4v-2h12v2H6z"/></svg><span>${label}</span>`;
  btn.addEventListener('mouseenter', () => { btn.style.opacity = '0.85'; btn.style.transform = 'scale(1.04)'; });
  btn.addEventListener('mouseleave', () => { btn.style.opacity = '1'; btn.style.transform = ''; });
  btn.addEventListener('click', (e) => { e.stopPropagation(); onClick(btn); });
  return btn;
}

function removeFloatingBtn() {
  document.getElementById(FAB_ID)?.remove();
}

// ── X / Twitter ───────────────────────────────────────────────────────────────

/** article 要素から /username/status/TWEETID 形式のリンクを探して返す */
function tweetUrlFromArticle(article) {
  for (const a of article.querySelectorAll('a[href]')) {
    const href = a.getAttribute('href') || '';
    if (/^\/\w+\/status\/\d+$/.test(href)) return `https://x.com${href}`;
  }
  return null;
}

/** メディア（画像・動画）が含まれているか */
function hasMedia(article) {
  return !!(
    article.querySelector('[data-testid="tweetPhoto"]') ||
    article.querySelector('[data-testid="videoComponent"]') ||
    article.querySelector('[data-testid="videoPlayer"]') ||
    article.querySelector('img[src*="pbs.twimg.com/media/"]')
  );
}

/** タイムラインのツイートカードにインラインボタンを追加する */
function addInlineBtn(article) {
  if (article.dataset.xk) return;
  if (!hasMedia(article)) return;
  const url = tweetUrlFromArticle(article);
  if (!url) return;

  // reply / like ボタンを含む group を action bar とみなす
  let bar = null;
  for (const g of article.querySelectorAll('[role="group"]')) {
    if (g.querySelector('[data-testid="reply"]') || g.querySelector('[data-testid="like"]')) {
      bar = g; break;
    }
  }
  if (!bar) bar = article.querySelector('[role="group"]');
  if (!bar) return;

  article.dataset.xk = '1';

  const btn = document.createElement('button');
  btn.title = 'x-keeper で保存';
  btn.style.cssText = 'display:inline-flex;align-items:center;padding:0 8px;height:36px;border:none;border-radius:9999px;background:transparent;color:#71767b;cursor:pointer;font-size:12px;gap:4px;transition:background .15s,color .15s;flex-shrink:0;';
  btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 16l-5-5 1.4-1.4 2.6 2.6V4h2v8.2l2.6-2.6L17 11l-5 5zm-6 4v-2h12v2H6z"/></svg>`;
  btn.addEventListener('mouseenter', () => { btn.style.background = 'rgba(29,155,240,.1)'; btn.style.color = '#1d9bf0'; });
  btn.addEventListener('mouseleave', () => { btn.style.background = 'transparent'; btn.style.color = '#71767b'; });
  btn.addEventListener('click', (e) => { e.stopPropagation(); e.preventDefault(); queueUrl(url, btn); });
  bar.appendChild(btn);
}

let lastXPath = '';

function onXNavigate() {
  const path = location.pathname;
  if (path === lastXPath) return;
  lastXPath = path;
  removeFloatingBtn();

  // ツイート詳細ページ
  const sm = path.match(/^\/([^/]+)\/status\/(\d+)/);
  if (sm) {
    const url = `https://x.com/${sm[1]}/status/${sm[2]}`;
    document.body.appendChild(makeFloatingBtn('このツイートを保存', '#1d9bf0', (btn) => queueUrl(url, btn)));
    return;
  }

  // ユーザーメディアページ
  const mm = path.match(/^\/([^/]+)\/media$/);
  if (mm) {
    const url = `https://x.com/${mm[1]}/media`;
    document.body.appendChild(makeFloatingBtn('全メディアを保存', '#1d9bf0', (btn) => queueUrl(url, btn)));
  }
}

function setupXTwitter() {
  // SPA ナビゲーション検知: pushState をフックして URL 変化を捕捉する
  const origPush = history.pushState.bind(history);
  history.pushState = function (...args) { origPush(...args); onXNavigate(); };
  window.addEventListener('popstate', onXNavigate);

  // タイムラインの動的ツイートを監視
  new MutationObserver(() => {
    document.querySelectorAll('article[data-testid="tweet"]:not([data-xk])').forEach(addInlineBtn);
  }).observe(document.body, { childList: true, subtree: true });

  onXNavigate();
  document.querySelectorAll('article[data-testid="tweet"]').forEach(addInlineBtn);
}

// ── Pixiv ─────────────────────────────────────────────────────────────────────

let lastPixivPath = '';

function onPixivNavigate() {
  const path = location.pathname;
  if (path === lastPixivPath) return;
  lastPixivPath = path;
  removeFloatingBtn();

  if (!/\/artworks\/\d+/.test(path)) return;
  const url = location.href.split('?')[0];
  const btn = makeFloatingBtn('x-keeper で保存', '#0096fa', (b) => queueUrl(url, b));
  document.body.appendChild(btn);
}

function setupPixiv() {
  const origPush = history.pushState.bind(history);
  history.pushState = function (...args) { origPush(...args); setTimeout(onPixivNavigate, 50); };
  window.addEventListener('popstate', onPixivNavigate);
  onPixivNavigate();
}

// ── Tampermonkey メニュー ─────────────────────────────────────────────────────

GM_registerMenuCommand('⚙ サーバー URL を設定', () => {
  const next = prompt('x-keeper サーバーの URL を入力:', serverUrl());
  if (!next?.trim()) return;
  GM_setValue(KEY_SERVER, next.trim().replace(/\/$/, ''));
  checkHealth((ok) => {
    if (ok) { toast('接続成功 ✓'); flushQueue(); }
    else toast('接続できませんでした', true);
  });
});

GM_registerMenuCommand('📤 オフラインキューを今すぐ送信', () => {
  const q = offlineQueue();
  if (!q.length) { toast('オフラインキューは空です'); return; }
  toast(`${q.length} 件を送信しています…`);
  flushQueue();
});

GM_registerMenuCommand('📋 履歴をエクスポート (TMH互換)', () => {
  GM_xmlhttpRequest({
    method: 'GET',
    url: `${serverUrl()}/api/history/export`,
    timeout: 10000,
    onload: (r) => {
      if (r.status !== 200) { toast('エクスポート失敗', true); return; }
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([r.responseText], { type: 'application/json' }));
      a.download = `xkeeper-history-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      toast('エクスポート完了 ✓');
    },
    onerror: () => toast('エクスポート失敗 (サーバー未接続)', true),
  });
});

GM_registerMenuCommand('📥 履歴をインポート (TMH互換)', () => {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.json';
  input.addEventListener('change', () => {
    const file = input.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      GM_xmlhttpRequest({
        method: 'POST',
        url: `${serverUrl()}/api/history/import`,
        headers: { 'Content-Type': 'application/json' },
        data: e.target.result,
        timeout: 10000,
        onload: (r) => {
          if (r.status === 200) toast(`インポート完了: ${JSON.parse(r.responseText).imported} 件 ✓`);
          else toast('インポート失敗', true);
        },
        onerror: () => toast('インポート失敗 (サーバー未接続)', true),
      });
    };
    reader.readAsText(file);
  });
  input.click();
});

// ── 初期化 ────────────────────────────────────────────────────────────────────

(function init() {
  flushQueue();
  const host = location.hostname;
  if (host === 'x.com' || host === 'twitter.com') setupXTwitter();
  else if (host === 'www.pixiv.net') setupPixiv();
})();
